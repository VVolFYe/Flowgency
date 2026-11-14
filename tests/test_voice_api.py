"""The audio route accepts only an already emitted alert ID."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.api.app import create_app


class FakeService:
    def voice_alert(self, event_id: str) -> dict | None:
        return {"text": "Traffic alert"} if event_id == "known" else None


class VoiceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app(FakeService())  # type: ignore[arg-type]
        self.endpoint = next(
            route.endpoint for route in app.routes
            if getattr(route, "path", None) == "/api/voice/alerts/{event_id}/audio"
        )

    def test_unknown_event_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(self.endpoint("unknown"))
        self.assertEqual(caught.exception.status_code, 404)

    def test_known_event_returns_mp3_without_browser_text(self) -> None:
        with patch("backend.api.app.VoiceSynthesis.render", return_value=b"mp3") as render:
            response = asyncio.run(self.endpoint("known"))
        self.assertEqual(response.media_type, "audio/mpeg")
        self.assertEqual(response.body, b"mp3")
        render.assert_called_once_with("Traffic alert")


if __name__ == "__main__":
    unittest.main()
