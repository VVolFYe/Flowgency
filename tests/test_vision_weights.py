import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.vision import weights
from backend.vision.paths import VisionPaths


class FetchWeightsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.paths = VisionPaths(root / "data")
        self.source = root / "release" / "model.pt"
        self.source.parent.mkdir()
        self.source.write_bytes(b"weights bytes")
        self.sha = hashlib.sha256(b"weights bytes").hexdigest()

    def register(self, sha256: str):
        entry = weights.RegisteredWeights(self.source.as_uri(), sha256)
        return mock.patch.dict(weights.REGISTRY, {"model.pt": entry}, clear=True)

    def test_missing_registered_file_is_downloaded_and_verified(self) -> None:
        with self.register(self.sha):
            path = weights.fetch_weights(self.paths, "model.pt")
        self.assertEqual(path, self.paths.weights_dir / "model.pt")
        self.assertEqual(path.read_bytes(), b"weights bytes")
        self.assertEqual([p.name for p in self.paths.weights_dir.iterdir()], ["model.pt"])

    def test_sha256_mismatch_leaves_no_file(self) -> None:
        with self.register("0" * 64), self.assertRaisesRegex(OSError, "sha256 mismatch"):
            weights.fetch_weights(self.paths, "model.pt")
        self.assertEqual(list(self.paths.weights_dir.iterdir()), [])

    def test_existing_file_is_used_without_download(self) -> None:
        self.paths.weights_dir.mkdir(parents=True)
        (self.paths.weights_dir / "model.pt").write_bytes(b"local copy")
        with self.register("0" * 64):  # a download would fail the hash check
            path = weights.fetch_weights(self.paths, "model.pt")
        self.assertEqual(path.read_bytes(), b"local copy")

    def test_missing_unregistered_file_raises_clear_error(self) -> None:
        with self.register(self.sha), self.assertRaisesRegex(FileNotFoundError, r"weights not found: .*other\.pt"):
            weights.fetch_weights(self.paths, "other.pt")

    def test_registry_urls_match_file_names(self) -> None:
        for name, entry in weights.REGISTRY.items():
            self.assertRegex(entry.url, r"^https://github\.com/[\w.-]+/[\w.-]+/releases/download/[\w.-]+/[\w.-]+$")
            if entry.url.startswith(weights.RELEASES_URL):  # team weights keep their file name
                self.assertRegex(entry.url, rf"^{weights.RELEASES_URL}/weights-v\d+/{name}$")
            self.assertRegex(entry.sha256, "^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
