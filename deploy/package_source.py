"""Archive an exact Git commit, replacing LFS pointers with verified local data.

Run after actions/checkout with lfs: true. Uses only the standard library and Git;
untracked files and worktree edits to ordinary source files never enter the tar.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import subprocess
import tarfile
from pathlib import Path


LFS_HEADER = b"version https://git-lfs.github.com/spec/v1\n"


def pointer_metadata(content: bytes) -> tuple[str, int] | None:
    normalized = content.replace(b"\r\n", b"\n")
    if not normalized.startswith(LFS_HEADER):
        return None
    match = re.fullmatch(
        re.escape(LFS_HEADER) + rb"oid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n?",
        normalized,
    )
    if match is None:
        raise ValueError("Unsupported or malformed Git LFS pointer")
    return match[1].decode("ascii"), int(match[2])


def verified_payload(root: Path, name: str, expected: tuple[str, int]) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"LFS payload missing or outside checkout: {name}")
    oid, size = expected
    if path.stat().st_size != size:
        raise ValueError(f"LFS size mismatch (run Git LFS checkout): {name}")
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != oid:
        raise ValueError(f"LFS SHA-256 mismatch: {name}")
    return path


def create_archive(root: Path, ref: str, destination: Path) -> int:
    if re.fullmatch(r"[0-9a-f]{40}", ref) is None:
        raise ValueError("Expected a full Git commit SHA")
    if destination.exists():
        raise FileExistsError(destination)
    temporary = destination.with_name(destination.name + ".partial")
    count = 0
    # Exclusive creation prevents removing another invocation's partial archive.
    with temporary.open("xb") as output_file:
        try:
            with subprocess.Popen(
                ["git", "archive", "--format=tar", ref],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as process:
                try:
                    with tarfile.open(fileobj=process.stdout, mode="r|") as source_tar:
                        with tarfile.open(fileobj=output_file, mode="w|gz") as target_tar:
                            for member in source_tar:
                                source = source_tar.extractfile(member) if member.isfile() else None
                                if source is not None and member.size <= 1024:
                                    content = source.read()
                                    expected = pointer_metadata(content)
                                    if expected is not None:
                                        path = verified_payload(root, member.name, expected)
                                        member.size = expected[1]
                                        with path.open("rb") as payload:
                                            target_tar.addfile(member, payload)
                                        count += 1
                                        continue
                                    source = io.BytesIO(content)
                                target_tar.addfile(member, source)
                    if process.wait() != 0:
                        raise RuntimeError("git archive failed")
                except BaseException:
                    if process.poll() is None:
                        process.terminate()
                    raise
        except BaseException:
            output_file.close()
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(destination)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    count = create_archive(root, args.ref, args.output)
    print(f"Packaged commit {args.ref}; verified {count} Git LFS payload(s).")


if __name__ == "__main__":
    main()
