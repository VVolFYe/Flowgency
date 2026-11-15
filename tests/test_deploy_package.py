"""Prove deploy archives contain verified payloads and exclude local secrets."""

from __future__ import annotations

import hashlib
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from deploy.package_source import create_archive, pointer_metadata


class DeployPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.repository = self.root / "checkout"
        self.repository.mkdir()
        self.git("init", "-q")
        self.payload = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 8
        self.video = self.repository / "video.mp4"
        self.video.write_bytes(
            b"version https://git-lfs.github.com/spec/v1\n"
            + f"oid sha256:{hashlib.sha256(self.payload).hexdigest()}\n".encode()
            + f"size {len(self.payload)}\n".encode()
        )
        (self.repository / "source.txt").write_text("committed source", encoding="utf-8")
        self.git("add", "source.txt", "video.mp4")
        self.git("-c", "user.name=Deploy Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.ref = self.git("rev-parse", "HEAD").strip()
        self.destination = self.root / "source.tar.gz"

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repository, text=True)

    def test_exact_commit_with_hydrated_video_and_no_local_secrets(self) -> None:
        self.video.write_bytes(self.payload)
        (self.repository / ".env").write_text("SECRET=do-not-package", encoding="utf-8")
        (self.repository / "source.txt").write_text("uncommitted edit", encoding="utf-8")
        self.assertEqual(create_archive(self.repository, self.ref, self.destination), 1)
        with tarfile.open(self.destination) as archive:
            self.assertNotIn(".env", archive.getnames())
            self.assertEqual(archive.extractfile("video.mp4").read(), self.payload)
            self.assertEqual(archive.extractfile("source.txt").read(), b"committed source")

    def test_pointer_instead_of_payload_blocks_publication(self) -> None:
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            create_archive(self.repository, self.ref, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_name("source.tar.gz.partial").exists())

    def test_same_size_corruption_is_rejected(self) -> None:
        self.video.write_bytes(b"x" * len(self.payload))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            create_archive(self.repository, self.ref, self.destination)

    def test_missing_payload_is_rejected(self) -> None:
        self.video.unlink()
        with self.assertRaisesRegex(ValueError, "payload missing"):
            create_archive(self.repository, self.ref, self.destination)

    def test_malformed_pointer_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "malformed"):
            pointer_metadata(b"version https://git-lfs.github.com/spec/v1\ninvalid\n")

    def test_existing_destination_is_not_overwritten(self) -> None:
        self.destination.write_bytes(b"keep this")
        with self.assertRaises(FileExistsError):
            create_archive(self.repository, self.ref, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"keep this")


if __name__ == "__main__":
    unittest.main()
