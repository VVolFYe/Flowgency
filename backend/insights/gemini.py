"""Server-side Gemini review of analytics summaries (google-genai SDK).

Modeled on backend/voice/tts.py: the API key is read lazily from the process
environment on every call, no key or statistics are accepted from the browser,
and results are cached in memory so repeated clicks do not spend quota.
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

from pydantic import BaseModel, ValidationError

# Newest flash model that answered this prompt within TIMEOUT_S when checked (2026-11-15);
# gemini-3.8-flash was listed but returned 503 high-demand / 504 deadline. Override with GEMINI_MODEL.
DEFAULT_MODEL = "gemini-3.5-flash"
# One attempt, under the 30 s Next.js proxy timeout. Flash answers this prompt in ~10-20 s.
TIMEOUT_S = 25

SYSTEM_INSTRUCTION = """\
You are a traffic-engineering analyst reviewing results from Flowgency, a SUMO
traffic simulation with fixed-time and adaptive signal control, plus camera
(vision) vehicle counts.

Rules:
- Use only the numbers in the provided JSON. Cite concrete values with units
  (for example "average waiting time 41.2 s fixed vs 35.7 s adaptive").
- Never invent metrics, units, locations or causes that the data does not support.
  null means unknown or not measured, not zero; say so when it matters.
- When both fixed and adaptive results exist, compare them on waiting time,
  queues, throughput and emergency-vehicle handling, and state which is better
  and by how much. If only one mode exists, review it on its own.
- Queues are simulated SUMO halting counts; vision counts are camera
  observations. Do not present one as the other.
- Suggestions must be actionable for signal timing or the experiment setup.
- Caveats cover validation failures, small samples, unfinished or stopped runs,
  and the listed limitations.
- Be concise: a 2-3 sentence summary and at most 5 short items per list.
"""


class InsightReview(BaseModel):
    summary: str
    key_findings: list[str]
    suggestions: list[str]
    caveats: list[str]


class InsightsNotConfigured(RuntimeError):
    """GEMINI_API_KEY is missing or the google-genai SDK is not installed."""


class InsightsGenerationFailed(RuntimeError):
    """Gemini could not be reached or returned an unusable response."""


def api_key_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def configured_model() -> str:
    return os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def _default_client(api_key: str) -> Any:
    try:
        from google import genai
        from google.genai import types
    except ModuleNotFoundError as exc:
        raise InsightsNotConfigured(
            "google-genai is not installed on the backend (pip install -r backend/requirements.txt)"
        ) from exc
    # The SDK default is 5 attempts with up to 60 s back-off; the user can click again instead.
    retry = types.HttpRetryOptions(attempts=1)
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000, retry_options=retry))


def _generation_config() -> Any:
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=InsightReview,
        temperature=0.2,
        # Summarizing a small JSON document needs little reasoning; low thinking keeps latency short.
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )


def _failure_detail(exc: Exception) -> str:
    """Short reason for the 502 detail; google-genai APIError carries Google's code and message (never the key)."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    if isinstance(code, int) and isinstance(message, str) and message:
        return f"Gemini request failed ({code}: {message[:160]})"
    return f"Gemini request failed ({type(exc).__name__})"


class GeminiInsights:
    def __init__(
        self,
        *,
        client_factory: Callable[[str], Any] | None = None,
        config_factory: Callable[[], Any] | None = None,
        max_cache_entries: int = 32,
    ) -> None:
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be positive")
        self._client_factory = client_factory or _default_client
        self._config_factory = config_factory or _generation_config
        self._cache: OrderedDict[tuple[Hashable, str], InsightReview] = OrderedDict()
        self._max_cache_entries = max_cache_entries
        self._lock = threading.Lock()

    def review(self, source_key: Hashable, context: dict[str, Any]) -> tuple[InsightReview, str, bool]:
        """Return ``(review, model, cached)`` for a compact analytics context.

        ``source_key`` identifies the data (run ids or analytics entry id); it is
        combined with the model name as the cache key.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:  # read lazily, like ELEVENLABS_API_KEY
            raise InsightsNotConfigured("Gemini is not configured on the backend (set GEMINI_API_KEY)")
        model = configured_model()
        cache_key = (source_key, model)
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key], model, True

        client = self._client_factory(api_key)
        prompt = (
            "Review this Flowgency analytics data and answer with the requested JSON.\n\n"
            + json.dumps(context, separators=(",", ":"), ensure_ascii=False)
        )
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=self._config_factory())
        except Exception as exc:  # SDK, HTTP and timeout errors all mean "Gemini failed"
            raise InsightsGenerationFailed(_failure_detail(exc)) from exc

        review = self._parse(response)
        with self._lock:
            self._cache[cache_key] = review
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self._max_cache_entries:
                self._cache.popitem(last=False)
        return review, model, False

    @staticmethod
    def _parse(response: Any) -> InsightReview:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, InsightReview):
            return parsed
        text = getattr(response, "text", None)
        if not text:
            raise InsightsGenerationFailed("Gemini returned an empty response")
        try:
            return InsightReview.model_validate_json(text)
        except ValidationError as exc:
            raise InsightsGenerationFailed("Gemini returned JSON that does not match the review schema") from exc
