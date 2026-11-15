"""ElevenLabs is optional and uses only server-held credentials."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.voice.tts import VoiceSynthesis


class FakeAudioResponse:
    def __enter__(self) -> "FakeAudioResponse":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def read(self) -> bytes:
        return b"fake-mp3"


class VoiceSynthesisTests(unittest.TestCase):
    def test_missing_key_does_not_call_provider(self) -> None:
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "", "ELEVENLABS_VOICE_ID": ""}), patch("backend.voice.tts.urlopen") as opener:
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                VoiceSynthesis().render("Hello")
            opener.assert_not_called()

    def test_renders_and_caches_exact_text(self) -> None:
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-secret", "ELEVENLABS_VOICE_ID": "test-voice"}), patch("backend.voice.tts.urlopen", return_value=FakeAudioResponse()) as opener:
            speech = VoiceSynthesis()
            self.assertEqual(speech.render("Traffic alert"), b"fake-mp3")
            self.assertEqual(speech.render("Traffic alert"), b"fake-mp3")
            self.assertEqual(opener.call_count, 1)
            request = opener.call_args.args[0]
            self.assertIn(b"Traffic alert", request.data)
            self.assertEqual(request.get_header("Xi-api-key"), "test-secret")

    def test_cache_is_bounded_and_text_is_normalized(self) -> None:
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-secret", "ELEVENLABS_VOICE_ID": "test-voice"}), patch("backend.voice.tts.urlopen", return_value=FakeAudioResponse()) as opener:
            speech = VoiceSynthesis(max_cache_entries=1)
            speech.render("Traffic   alert")
            speech.render("Traffic alert")
            self.assertEqual(opener.call_count, 1)
            speech.render("Second alert")
            speech.render("Traffic alert")
            self.assertEqual(opener.call_count, 3)


if __name__ == "__main__":
    unittest.main()
