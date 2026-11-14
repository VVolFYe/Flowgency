"""Server-side ElevenLabs rendering for previously emitted alert text."""

from __future__ import annotations

import json
import os
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class VoiceSynthesis:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], bytes] = {}
        self._lock = threading.Lock()

    def render(self, text: str) -> bytes:
        """Return MP3 bytes; no key or arbitrary text is accepted from the browser."""
        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID")
        model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        if not api_key or not voice_id:
            raise RuntimeError("ElevenLabs voice is not configured on the backend")
        cache_key = (voice_id, model_id, text)
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id, safe='')}/stream"
        payload = json.dumps({"text": text, "model_id": model_id}).encode("utf-8")
        request = Request(
            url,
            data=payload,
            headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                audio = response.read()
        except HTTPError as exc:
            raise RuntimeError(f"ElevenLabs returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError("ElevenLabs is unavailable") from exc
        if not audio:
            raise RuntimeError("ElevenLabs returned empty audio")
        with self._lock:
            self._cache[cache_key] = audio
        return audio
