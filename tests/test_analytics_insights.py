"""POST /api/analytics/insights with a mocked Gemini client (no real API calls)."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.analytics import db, load
from backend.api.app import create_app
from backend.api.auth import Auth0TokenVerifier
from backend.insights import summary
from backend.insights.gemini import DEFAULT_MODEL, GeminiInsights

ROOT = Path(__file__).resolve().parents[1]
ANALYTICS = ROOT / "frontend" / "public" / "analytics"
DOMAIN = "flowgency-test.eu.auth0.com"
AUDIENCE = "https://api.flowgency.test"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
REVIEW = {
    "summary": "Adaptive control reduced waiting.",
    "key_findings": ["Average waiting 40 s fixed vs 30 s adaptive."],
    "suggestions": ["Extend the adaptive profile to the remaining controller."],
    "caveats": ["Single seed."],
}


class StaticJwksClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=PRIVATE_KEY.public_key())


class StubSimulationService:
    def open(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.text = json.dumps(REVIEW)

    def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(parsed=None, text=self.text)


def token(permissions: list[str]) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "auth0|test", "iss": f"https://{DOMAIN}/", "aud": AUDIENCE, "iat": now,
         "exp": now + timedelta(minutes=5), "permissions": permissions},
        PRIVATE_KEY, algorithm="RS256", headers={"kid": "test-key"},
    )


def run_payload(run_id: str, mode: str, ended_at: str, waiting: float) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": "simulation_run",
        "run": {"run_id": run_id, "scenario_id": "london_normal", "control_mode": mode, "controller_mode": mode,
                "status": "finished", "ended_at": ended_at, "sim_duration_s": 600.0},
        "summary": {"average_waiting_time_s": waiting, "total_time_loss_s": None},
        "timeseries": {"interval_s": 5, "queue_measurement": "sumo_halting_number",
                       "samples": [{"t_s": 5.0 * i, "network_queue_vehicles": i % 7 if i != 3 else None,
                                    "active_vehicle_count": 10 + i} for i in range(200)]},
        "intersections": [{"traffic_light_id": f"TL{i}", "mean_queue_vehicles": float(i),
                           "max_queue_vehicles": i * 2, "sample_count": 200} for i in range(12)],
        "phases": [{"traffic_light_id": "TL0", "phase_change_count": 40, "completed_green_phases": 20,
                    "mean_green_duration_s": 31.5}],
    }


class InsightsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "analytics.sqlite3"
        environment = mock.patch.dict("os.environ", {db.DB_ENV_VAR: str(self.database), "GEMINI_API_KEY": "test-key"})
        environment.start()
        self.addCleanup(environment.stop)
        self.models = FakeModels()
        self.api_keys: list[str] = []

        def client_factory(api_key: str) -> SimpleNamespace:
            self.api_keys.append(api_key)
            return SimpleNamespace(models=self.models)

        self.app = create_app(
            service=StubSimulationService(),  # type: ignore[arg-type]
            auth0_verifier=Auth0TokenVerifier(DOMAIN, AUDIENCE, StaticJwksClient()),
            insights=GeminiInsights(client_factory=client_factory, config_factory=lambda: {"fake": True}),
        )

    def post(self, body: dict[str, Any], permissions: list[str] | None = None) -> httpx.Response:
        headers = {} if permissions is None else {"Authorization": f"Bearer {token(permissions)}"}

        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.post("/api/analytics/insights", json=body, headers=headers)

        return asyncio.run(send())

    def reader(self, body: dict[str, Any]) -> httpx.Response:
        return self.post(body, ["analytics:read"])

    def test_requires_token_and_analytics_read(self) -> None:
        self.assertEqual(self.post({"entry_id": None}).status_code, 401)
        self.assertEqual(self.post({"entry_id": None}, ["simulation:read"]).status_code, 403)
        self.assertEqual(self.models.calls, [])

    def test_missing_key_is_503(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            response = self.reader({"entry_id": "youtube"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.json()["detail"])

    def test_missing_database_is_503(self) -> None:
        self.assertEqual(self.reader({"entry_id": "youtube"}).status_code, 503)
        self.assertEqual(self.reader({"entry_id": None}).status_code, 503)

    def test_entry_review_uses_compact_prompt_and_is_cached(self) -> None:
        load.load(ANALYTICS / "index.json")
        response = self.reader({"entry_id": "london_normal"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["model"], DEFAULT_MODEL)
        self.assertFalse(body["cached"])
        self.assertEqual(body["source"], {"kind": "entry", "id": "london_normal", "scenario_id": None, "paired": False})
        for field in ("summary", "key_findings", "suggestions", "caveats"):
            self.assertEqual(body[field], REVIEW[field])

        call = self.models.calls[0]
        self.assertEqual(call["model"], DEFAULT_MODEL)
        self.assertEqual(self.api_keys, ["test-key"])
        prompt = call["contents"]
        raw_size = len((ANALYTICS / "london_normal.json").read_text(encoding="utf-8"))
        self.assertLess(len(prompt), raw_size / 3)
        self.assertNotIn("histogram", prompt)
        self.assertNotIn("GS_110249279\":{", prompt)  # per-controller map replaced by a top-N list

        again = self.reader({"entry_id": "london_normal"})
        self.assertTrue(again.json()["cached"])
        self.assertEqual(len(self.models.calls), 1)

    def test_model_override_changes_cache_key(self) -> None:
        load.load(ANALYTICS / "index.json")
        self.reader({"entry_id": "youtube"})
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "gemini-other-flash"}):
            response = self.reader({"entry_id": "youtube"})
        self.assertEqual(response.json()["model"], "gemini-other-flash")
        self.assertFalse(response.json()["cached"])
        self.assertEqual([call["model"] for call in self.models.calls], [DEFAULT_MODEL, "gemini-other-flash"])

    def test_unknown_entry_and_no_runs_are_404(self) -> None:
        load.load(ANALYTICS / "index.json")
        self.assertEqual(self.reader({"entry_id": "nope"}).status_code, 404)
        db.init_db()
        self.assertEqual(self.reader({"entry_id": None}).status_code, 404)
        self.assertEqual(self.models.calls, [])

    def test_latest_run_includes_pair_without_repeating_it(self) -> None:
        for run_id, mode, ended_at, waiting in (
            ("r-fixed", "fixed_timing", "2026-11-14T10:00:00.000Z", 40.0),
            ("r-adaptive", "adaptive_network", "2026-11-14T11:00:00.000Z", 30.0),
        ):
            payload = run_payload(run_id, mode, ended_at, waiting)
            db.insert_run(run_id=run_id, scenario_id="london_normal", control_mode=mode, status="finished",
                          started_at=ended_at, ended_at=ended_at, sim_duration_s=600.0, payload=json.dumps(payload))
        response = self.reader({"entry_id": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source"],
                         {"kind": "latest_run", "id": "r-adaptive", "scenario_id": "london_normal", "paired": True})
        context = json.loads(self.models.calls[0]["contents"].split("\n\n", 1)[1])
        pair = context["fixed_vs_adaptive_live_runs"]
        self.assertEqual(pair["adaptive"], {"same_as": "latest_run", "run_id": "r-adaptive"})
        self.assertEqual(pair["fixed"]["summary"]["average_waiting_time_s"], 40.0)
        self.assertNotIn("\"samples\":[", self.models.calls[0]["contents"])  # raw 5 s samples are trimmed
        self.assertEqual(len(context["latest_run"]["intersections"]["top_5_by_mean_queue"]), 5)

    def insert_run(self, run_id: str, mode: str, ended_at: str, waiting: float) -> None:
        payload = run_payload(run_id, mode, ended_at, waiting)
        db.insert_run(run_id=run_id, scenario_id="london_normal", control_mode=mode, status="finished",
                      started_at=ended_at, ended_at=ended_at, sim_duration_s=600.0, payload=json.dumps(payload))

    def prompt_context(self, call_index: int) -> dict[str, Any]:
        return json.loads(self.models.calls[call_index]["contents"].split("\n\n", 1)[1])

    def test_same_latest_run_twice_calls_gemini_once(self) -> None:
        self.insert_run("r-A", "fixed_timing", "2026-11-14T10:00:00.000Z", 40.0)
        first, second = self.reader({"entry_id": None}), self.reader({"entry_id": None})
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual((first.json()["cached"], second.json()["cached"]), (False, True))
        self.assertEqual(len(self.models.calls), 1)

    def test_new_latest_run_calls_gemini_again_about_the_new_run(self) -> None:
        self.insert_run("r-A", "fixed_timing", "2026-11-14T10:00:00.000Z", 40.0)
        self.assertEqual(self.reader({"entry_id": None}).json()["source"]["id"], "r-A")
        self.insert_run("r-B", "fixed_timing", "2026-11-14T11:00:00.000Z", 25.0)
        self.models.text = json.dumps({**REVIEW, "summary": "Run r-B averaged 25 s waiting."})
        response = self.reader({"entry_id": None})
        self.assertEqual(len(self.models.calls), 2)
        body = response.json()
        self.assertFalse(body["cached"])
        self.assertEqual(body["source"]["id"], "r-B")
        self.assertEqual(body["summary"], "Run r-B averaged 25 s waiting.")
        latest = self.prompt_context(1)["latest_run"]
        self.assertEqual((latest["run"]["run_id"], latest["summary"]["average_waiting_time_s"]), ("r-B", 25.0))

    def test_same_run_id_with_changed_status_and_metrics_calls_gemini_again(self) -> None:
        # The runs table holds each run once, at its end (status CHECK has no "running"),
        # so this patches the DB reads to serve two versions of the same run_id.
        running = run_payload("r-live", "fixed_timing", "2026-11-14T10:00:00.000Z", 12.0)
        running["run"]["status"] = "running"
        finished = run_payload("r-live", "fixed_timing", "2026-11-14T10:10:00.000Z", 38.0)
        with mock.patch.object(db, "latest_run_payload", side_effect=[json.dumps(running), json.dumps(finished)]), \
                mock.patch.object(db, "latest_run_payload_for", return_value=None):
            first, second = self.reader({"entry_id": None}), self.reader({"entry_id": None})
        self.assertEqual((first.json()["source"]["id"], second.json()["source"]["id"]), ("r-live", "r-live"))
        self.assertFalse(second.json()["cached"])
        self.assertEqual(len(self.models.calls), 2)
        self.assertEqual(self.prompt_context(1)["latest_run"]["run"]["status"], "finished")
        self.assertEqual(self.prompt_context(1)["latest_run"]["summary"]["average_waiting_time_s"], 38.0)

    def test_same_entry_is_cached_and_a_different_entry_is_not(self) -> None:
        load.load(ANALYTICS / "index.json")
        self.assertFalse(self.reader({"entry_id": "youtube"}).json()["cached"])
        self.assertTrue(self.reader({"entry_id": "youtube"}).json()["cached"])
        self.assertEqual(len(self.models.calls), 1)
        other = self.reader({"entry_id": "london_normal"}).json()
        self.assertFalse(other["cached"])
        self.assertEqual(other["source"]["id"], "london_normal")
        self.assertEqual(len(self.models.calls), 2)
        self.assertEqual(self.prompt_context(1)["scenario_id"], "london_normal")

    def test_gemini_failure_is_502_and_not_cached(self) -> None:
        load.load(ANALYTICS / "index.json")
        self.models.error = TimeoutError("slow")
        self.assertEqual(self.reader({"entry_id": "youtube"}).status_code, 502)
        self.models.error = None
        self.models.text = "{\"summary\": 1}"
        self.assertEqual(self.reader({"entry_id": "youtube"}).status_code, 502)
        self.models.text = json.dumps(REVIEW)
        self.assertEqual(self.reader({"entry_id": "youtube"}).status_code, 200)
        self.assertEqual(len(self.models.calls), 3)


class SummaryTests(unittest.TestCase):
    def test_series_stats_keeps_unknown_as_none(self) -> None:
        self.assertEqual(summary.series_stats([None, None])["mean"], None)
        stats = summary.series_stats([1, None, 3])
        self.assertEqual((stats["samples"], stats["known"], stats["mean"], stats["last"]), (3, 2, 2.0, 3.0))

    def test_vision_summary_drops_per_second_series(self) -> None:
        payload = json.loads((ANALYTICS / "youtube.json").read_text(encoding="utf-8"))
        result = summary.summarize_payload(payload)
        self.assertNotIn("timeseries", result)
        self.assertEqual(result["totals"], payload["totals"])
        self.assertEqual(result["vehicles_on_approach_stats"]["north"]["samples"],
                         len(payload["timeseries"]["t_s"]))

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            summary.summarize_payload({"kind": "other"})


if __name__ == "__main__":
    unittest.main()
