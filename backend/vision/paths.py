"""Filesystem locations for vision inputs and outputs.

Media, weights, and every generated artefact live outside the repository under
``UNIHACK_DIR`` (default ``/home/coro/Desktop/unihack``; override with the
``UNIHACK_DIR`` environment variable). Only pixel-coordinate configuration is
kept in the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VISION_DIR = Path(__file__).resolve().parent
DEFAULT_CAMERAS_JSON = VISION_DIR / "config" / "cameras.json"
MAPPING_CANDIDATES_JSON = REPO_ROOT / "scenarios" / "london_network" / "mapping_candidates.json"
DEFAULT_UNIHACK_DIR = Path("/home/coro/Desktop/unihack")


@dataclass(frozen=True)
class VisionPaths:
    unihack_dir: Path

    @classmethod
    def from_env(cls) -> VisionPaths:
        return cls(Path(os.environ.get("UNIHACK_DIR", str(DEFAULT_UNIHACK_DIR))).expanduser())

    @property
    def clips_dir(self) -> Path:
        return self.unihack_dir / "clips"

    @property
    def weights_dir(self) -> Path:
        return self.unihack_dir / "weights"

    @property
    def output_dir(self) -> Path:
        return self.unihack_dir / "vision_output"

    @property
    def reference_frames_dir(self) -> Path:
        return self.output_dir / "reference_frames"

    @property
    def observations_dir(self) -> Path:
        return self.output_dir / "observations"

    @property
    def run_log_csv(self) -> Path:
        return self.output_dir / "run_log.csv"

    @property
    def eval_dir(self) -> Path:
        return self.output_dir / "eval"

    @property
    def ultralytics_config_dir(self) -> Path:
        return self.unihack_dir / "ultralytics_config"

    def resolve(self, relative: str | Path) -> Path:
        """Resolve a path stored relative to ``UNIHACK_DIR`` in committed config."""
        path = Path(relative)
        return path if path.is_absolute() else self.unihack_dir / path

    def relative(self, path: Path) -> str:
        """Express ``path`` relative to ``UNIHACK_DIR`` for committed config."""
        try:
            return path.resolve().relative_to(self.unihack_dir.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f"{path} is not inside UNIHACK_DIR {self.unihack_dir}") from exc
