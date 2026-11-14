"""Weights fetched from GitHub release assets into ``UNIHACK_DIR/weights`` on first use.

Registered: the team-made weights (this repository's ``weights-vN`` releases) and stock COCO yolo11s, which is
kept under the name ``yolo11s_coco.pt`` so Ultralytics cannot download it by that name itself.

A registered file that is missing locally is downloaded, checked against its sha256, and only then moved into
place (under the registry's file name). Files already present are used as they are. Unregistered files are never
downloaded here (other stock COCO weights keep Ultralytics' own download in
:func:`~backend.vision.detect_track.ensure_weights`).

Entries are per file: a new or retrained file goes in its own release (e.g. ``weights-v2``) and only its entry
points there; the others keep their release.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import NamedTuple

from .paths import VisionPaths

RELEASES_URL = "https://github.com/VVolFYe/Flowgency/releases/download"  # + /<release tag>/<file name>


class RegisteredWeights(NamedTuple):
    url: str
    sha256: str


REGISTRY: dict[str, RegisteredWeights] = {
    # Official Ultralytics yolo11s.pt (the release the installed ultralytics 8.4.x downloads from), saved renamed.
    "yolo11s_coco.pt": RegisteredWeights(
        "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11s.pt",
        "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5"),
    "yolo11s_visdrone.pt": RegisteredWeights(
        f"{RELEASES_URL}/weights-v1/yolo11s_visdrone.pt",
        "f2cf0fb80d831336d43496f640a9d705aab3ab963422cb4d83d6ecece6d1da20"),
    "yolo11s_visdrone_544x960.onnx": RegisteredWeights(
        f"{RELEASES_URL}/weights-v1/yolo11s_visdrone_544x960.onnx",
        "0eced7af08218aada32dfa8604a8873521b4e6ed6474e0d65b4768a8e17d6867"),
    "emergency_cls.pt": RegisteredWeights(
        f"{RELEASES_URL}/weights-v2/emergency_cls.pt",
        "a6092ebc5d5d80578d1dbf8a14efec16dfc02ff4edd22068eef6b2ffd3212121"),
}


def fetch_weights(paths: VisionPaths, name: str, what: str = "weights") -> Path:
    """``UNIHACK_DIR/weights/<name>``, downloading and verifying it first when missing and registered."""
    target = paths.weights_dir / name
    if target.exists():
        return target
    entry = REGISTRY.get(name)
    if entry is None:
        raise FileNotFoundError(paths.missing(what, target))
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    print(f"downloading {name} from {entry.url}")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(entry.url, timeout=60) as response, part.open("wb") as out:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != entry.sha256:
            raise OSError(f"sha256 mismatch for {name}: got {digest.hexdigest()}, expected {entry.sha256}")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(target)
    return target
