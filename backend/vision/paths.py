"""Filesystem locations for vision inputs and outputs.

Media, weights, caches, and every generated artefact live in one data folder:
the ``UNIHACK_DIR`` environment variable when set (e.g. a personal folder
outside the repository), otherwise the repository's own ``data/`` folder,
which is gitignored. Only pixel-coordinate configuration and the small shared
samples (``backend/vision/samples/``) are tracked; reading the samples needs no
data folder at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VISION_DIR = Path(__file__).resolve().parent
DEFAULT_CAMERAS_JSON = VISION_DIR / "config" / "cameras.json"
SCENES_DIR = VISION_DIR / "config" / "scenes"
SAMPLES_DIR = VISION_DIR / "samples"
MAPPING_CANDIDATES_JSON = REPO_ROOT / "scenarios" / "london_network" / "mapping_candidates.json"
REPO_DATA_DIR = REPO_ROOT / "data"  # gitignored; the default data folder
DATA_ENV_VAR = "UNIHACK_DIR"


def missing_data_message(what: str, path: Path, data_dir: Path | None = None) -> str:
    """Error text for a required input (clip, video, weights) that is not in the data folder."""
    data_dir = data_dir or VisionPaths.from_env().unihack_dir
    source = (f"{DATA_ENV_VAR}={data_dir}" if os.environ.get(DATA_ENV_VAR)
              else f"the default data folder {data_dir} ({DATA_ENV_VAR} is not set)")
    return (f"{what} not found: {path}. Looked in {source}. Set {DATA_ENV_VAR} to the folder that holds your "
            f"clips/weights, or put the files in the repository's gitignored data/ folder ({REPO_DATA_DIR}) "
            f"using the same layout (see backend/vision/COLLEAGUE_SETUP.md).")


@dataclass(frozen=True)
class VisionPaths:
    unihack_dir: Path

    @classmethod
    def from_env(cls) -> VisionPaths:
        value = os.environ.get(DATA_ENV_VAR)
        return cls(Path(value).expanduser() if value else REPO_DATA_DIR)

    def missing(self, what: str, path: Path) -> str:
        """Error text for a required input that is not in the data folder."""
        return missing_data_message(what, path, self.unihack_dir)

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

    def scene_output_dir(self, scene_id: str) -> Path:
        """Gate-mode outputs for one scene (events, counts, previews, demos)."""
        return self.output_dir / scene_id

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
