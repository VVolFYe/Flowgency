"""Accuracy evaluation: eval-set sampling, ground truth I/O, metrics, report.

Pure Python (no CV stack). All times are UTC.

Day/night uses the UTC hour of the clip's window end, which equals London time
in November: by default day = 08:00-15:59, night = 17:00-06:59, and the
twilight hours 07:00-07:59 and 16:00-16:59 are excluded from sampling.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .counting import VEHICLE_CLASSES

# --- day / night ----------------------------------------------------------------------


@dataclass(frozen=True)
class PeriodConfig:
    """Hour ranges as [start, end) in UTC; ranges may wrap past midnight."""

    day: tuple[int, int] = (8, 16)
    night: tuple[int, int] = (17, 7)

    @staticmethod
    def _contains(window: tuple[int, int], hour: int) -> bool:
        start, end = window
        return start <= hour < end if start <= end else hour >= start or hour < end

    def classify(self, moment: datetime) -> str:
        hour = moment.hour
        if self._contains(self.day, hour):
            return "day"
        if self._contains(self.night, hour):
            return "night"
        return "twilight"

    @classmethod
    def parse(cls, day: str, night: str) -> PeriodConfig:
        def window(text: str) -> tuple[int, int]:
            start, _, end = text.partition("-")
            values = (int(start), int(end))
            if not all(0 <= v <= 24 for v in values) or values[0] == values[1]:
                raise ValueError(f"bad hour range {text!r}; use e.g. 08-16 (end exclusive)")
            return values

        config = cls(window(day), window(night))
        overlap = [h for h in range(24) if cls._contains(config.day, h) and cls._contains(config.night, h)]
        if overlap:
            raise ValueError(f"day and night ranges overlap at UTC hours {overlap}")
        return config


# --- eval set ------------------------------------------------------------------------

EVAL_SET_FIELDS = ["intersection_id", "camera_id", "clip", "observed_at_utc", "period", "selection", "seed"]


@dataclass(frozen=True)
class EvalCandidate:
    intersection_id: str
    camera_id: str
    clip: str
    observed_at_utc: str
    period: str


@dataclass
class SampleReport:
    rows: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def sample_eval_set(
    candidates_by_camera: dict[str, list[EvalCandidate]],
    per_camera: int,
    seed: int,
) -> SampleReport:
    """Deterministic day/night-balanced sample of usable clips per camera.

    Half (rounded up for day) from each period; if a period is short, the gap is
    filled from the other period and reported. Twilight clips are never picked.
    """
    report = SampleReport()
    for camera_id in sorted(candidates_by_camera):
        pool = candidates_by_camera[camera_id]
        rng = random.Random(f"{seed}:{camera_id}")
        by_period = {p: sorted((c for c in pool if c.period == p), key=lambda c: c.clip) for p in ("day", "night")}
        want = {"day": (per_camera + 1) // 2, "night": per_camera // 2}
        picked: dict[str, list[EvalCandidate]] = {}
        for period in ("day", "night"):
            picked[period] = rng.sample(by_period[period], min(want[period], len(by_period[period])))
        fill: list[EvalCandidate] = []
        for short, other in (("day", "night"), ("night", "day")):
            missing = want[short] - len(picked[short])
            if missing > 0:
                remaining = [c for c in by_period[other] if c not in picked[other] and c not in fill]
                extra = rng.sample(remaining, min(missing, len(remaining)))
                fill += extra
                report.notes.append(
                    f"{camera_id}: only {len(by_period[short])} usable {short} clips; "
                    f"filled {len(extra)} from {other}"
                    + (f"; still {missing - len(extra)} short" if len(extra) < missing else "")
                )
        chosen = [(c, "primary") for p in ("day", "night") for c in picked[p]] + [(c, "fill") for c in fill]
        for candidate, selection in sorted(chosen, key=lambda item: item[0].clip):
            report.rows.append({
                "intersection_id": candidate.intersection_id,
                "camera_id": candidate.camera_id,
                "clip": candidate.clip,
                "observed_at_utc": candidate.observed_at_utc,
                "period": candidate.period,
                "selection": selection,
                "seed": seed,
            })
    return report


def write_csv(path: Path, fields: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# --- ground truth ----------------------------------------------------------------------

GT_FIELDS = [
    "intersection_id", "camera_id", "clip", "observed_at_utc", "period", "approach_id", "status",
    "total", *VEHICLE_CLASSES, "reason", "labelled_at_utc",
]


def parse_count_entry(text: str) -> tuple[int, dict[str, int] | None]:
    """Parse ``"3"`` or ``"3 car=2 bus=1"`` (unlisted classes are 0, split must sum)."""
    parts = text.split()
    if not parts:
        raise ValueError("enter a count, e.g. 3 or 3 car=2 bus=1")
    try:
        total = int(parts[0])
    except ValueError as exc:
        raise ValueError(f"total {parts[0]!r} is not an integer") from exc
    if total < 0:
        raise ValueError("count must be >= 0")
    if len(parts) == 1:
        return total, None
    split = {c: 0 for c in VEHICLE_CLASSES}
    for part in parts[1:]:
        name, sep, value = part.partition("=")
        if not sep or name not in VEHICLE_CLASSES:
            raise ValueError(f"bad class entry {part!r}; use {'/'.join(VEHICLE_CLASSES)}=N")
        if not value.isdigit():
            raise ValueError(f"class count {value!r} must be a non-negative integer")
        split[name] = int(value)
    if sum(split.values()) != total:
        raise ValueError(f"class split sums to {sum(split.values())}, total is {total}")
    return total, split


@dataclass(frozen=True)
class GroundTruth:
    camera_id: str
    clip: str
    approach_id: str
    total: int
    split: dict[str, int] | None


def load_ground_truth(rows: Iterable[dict[str, str]]) -> tuple[dict[tuple[str, str, str], GroundTruth], set[tuple[str, str]]]:
    """Labelled counts keyed by (camera, clip, approach) and the set of unusable clips."""
    labels: dict[tuple[str, str, str], GroundTruth] = {}
    unusable: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["camera_id"], row["clip"])
        if row["status"] == "unusable":
            unusable.add(key)
            continue
        if row["status"] != "labelled":
            raise ValueError(f"unknown ground-truth status {row['status']!r}")
        split = None
        if all(row.get(c, "") != "" for c in VEHICLE_CLASSES):
            split = {c: int(row[c]) for c in VEHICLE_CLASSES}
        labels[(*key, row["approach_id"])] = GroundTruth(row["camera_id"], row["clip"], row["approach_id"], int(row["total"]), split)
    return labels, unusable


# --- metrics ---------------------------------------------------------------------------

RESULT_FIELDS = [
    "model", "conf", "intersection_id", "camera_id", "clip", "observed_at_utc", "period", "approach_id",
    "gt_total", "pred_total", "error", "abs_error",
    *[f"gt_{c}" for c in VEHICLE_CLASSES], *[f"pred_{c}" for c in VEHICLE_CLASSES],
    "pipeline_status", "runtime_s",
]


@dataclass(frozen=True)
class Pair:
    model: str
    conf: float
    intersection_id: str
    camera_id: str
    clip: str
    period: str
    approach_id: str
    gt: int
    pred: int
    runtime_s: float | None


@dataclass(frozen=True)
class Summary:
    n: int
    gt_sum: int
    pred_sum: int
    rel_error: float | None  # (pred_sum - gt_sum) / gt_sum
    mae: float | None
    exact: float | None
    within1: float | None

    @classmethod
    def of(cls, pairs: Sequence[Pair]) -> Summary:
        n = len(pairs)
        gt_sum = sum(p.gt for p in pairs)
        pred_sum = sum(p.pred for p in pairs)
        errors = [abs(p.pred - p.gt) for p in pairs]
        return cls(
            n,
            gt_sum,
            pred_sum,
            (pred_sum - gt_sum) / gt_sum if gt_sum else None,
            sum(errors) / n if n else None,
            sum(e == 0 for e in errors) / n if n else None,
            sum(e <= 1 for e in errors) / n if n else None,
        )


@dataclass(frozen=True)
class Targets:
    max_overall_rel_error: float = 0.10
    max_mae: float = 1.0
    max_camera_rel_error: float = 0.20


def config_verdict(pairs: Sequence[Pair], targets: Targets = Targets()) -> dict[str, Any]:
    overall = Summary.of(pairs)
    cameras = {cam: Summary.of([p for p in pairs if p.camera_id == cam]) for cam in sorted({p.camera_id for p in pairs})}
    fails = []
    if overall.rel_error is None or abs(overall.rel_error) > targets.max_overall_rel_error:
        fails.append("overall relative error")
    if overall.mae is None or overall.mae > targets.max_mae:
        fails.append("per-clip MAE")
    worst = [c for c, s in cameras.items() if s.rel_error is None or abs(s.rel_error) > targets.max_camera_rel_error]
    if worst:
        jids = {p.camera_id: p.intersection_id for p in pairs}
        fails.append("cameras over limit: " + ", ".join(jids[c] for c in worst))
    runtimes = [p.runtime_s for p in pairs if p.runtime_s is not None]
    return {
        "overall": overall,
        "cameras": cameras,
        "meets_targets": not fails,
        "fails": fails,
        "mean_runtime_s": sum(runtimes) / len(runtimes) if runtimes else None,
    }


def _pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.1f}%" if signed else f"{value * 100:.0f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def summary_row(label: str, s: Summary) -> str:
    return (f"| {label} | {s.n} | {s.gt_sum} | {s.pred_sum} | {_pct(s.rel_error, True)} | "
            f"{_num(s.mae)} | {_pct(s.exact)} | {_pct(s.within1)} |")


SUMMARY_HEADER = ("| | clip-approaches | GT sum | predicted sum | rel. error of sum | MAE/clip | exact | within ±1 |\n"
                  "|---|---|---|---|---|---|---|---|")


def choose_recommendation(verdicts: dict[tuple[str, float], dict[str, Any]]) -> tuple[str, float] | None:
    """Best config meeting targets (lowest MAE, then |rel error|, then runtime); else lowest MAE."""
    if not verdicts:
        return None

    def key(item: tuple[tuple[str, float], dict[str, Any]]) -> tuple:
        cfg, v = item
        overall: Summary = v["overall"]
        return (
            overall.mae if overall.mae is not None else float("inf"),
            abs(overall.rel_error) if overall.rel_error is not None else float("inf"),
            v["mean_runtime_s"] if v["mean_runtime_s"] is not None else float("inf"),
            cfg,
        )

    passing = [item for item in verdicts.items() if item[1]["meets_targets"]]
    return min(passing or verdicts.items(), key=key)[0]


def render_report(
    pairs: Sequence[Pair],
    *,
    targets: Targets,
    periods: PeriodConfig,
    notes: Sequence[str],
    generated_utc: str,
) -> str:
    configs = sorted({(p.model, p.conf) for p in pairs})
    verdicts = {cfg: config_verdict([p for p in pairs if (p.model, p.conf) == cfg], targets) for cfg in configs}
    best = choose_recommendation(verdicts)
    jids = {p.camera_id: p.intersection_id for p in pairs}
    lines = [
        "# Flowgency vision accuracy report",
        "",
        f"Generated {generated_utc}. Ground truth: manual inbound line-crossing counts per visible approach.",
        f"Day = UTC {periods.day[0]:02d}:00-{periods.day[1] - 1:02d}:59, night = UTC {periods.night[0]:02d}:00-"
        f"{(periods.night[1] - 1) % 24:02d}:59 (UTC = London time in November); twilight excluded.",
        f"Targets: |overall relative error of summed counts| <= {targets.max_overall_rel_error:.0%}, "
        f"per-clip MAE <= {targets.max_mae:g} vehicle/approach, no camera worse than {targets.max_camera_rel_error:.0%}.",
        "Relative error = (predicted sum - GT sum) / GT sum; positive means over-counting.",
        "Runtime = YOLO detection (CPU, measured when first computed) + tracking + counting, per clip.",
        "",
    ]
    if notes:
        lines += ["## Notes", "", *[f"- {n}" for n in notes], ""]
    lines += ["## Configurations", "",
              "| model | conf | rel. error of sum | MAE/clip | exact | within ±1 | worst camera | mean runtime/clip | meets targets |",
              "|---|---|---|---|---|---|---|---|---|"]
    for cfg in configs:
        v = verdicts[cfg]
        o: Summary = v["overall"]
        worst = max(v["cameras"].items(), key=lambda kv: abs(kv[1].rel_error) if kv[1].rel_error is not None else float("inf"))
        lines.append(
            f"| {cfg[0]} | {cfg[1]:.2f} | {_pct(o.rel_error, True)} | {_num(o.mae)} | {_pct(o.exact)} | "
            f"{_pct(o.within1)} | {jids.get(worst[0], worst[0])} {_pct(worst[1].rel_error, True)} | "
            f"{_num(v['mean_runtime_s'], 1)} s | "
            f"{'yes' if v['meets_targets'] else 'no: ' + '; '.join(v['fails'])} |"
        )
    lines.append("")
    if best:
        state = "meets all targets" if verdicts[best]["meets_targets"] else "best available, does NOT meet all targets"
        lines += [f"**Recommended: {best[0]} at conf {best[1]:.2f}** ({state}; ranked by MAE, then |relative error|, then runtime).", ""]

    for cfg in configs:
        sel = [p for p in pairs if (p.model, p.conf) == cfg]
        lines += [f"## {cfg[0]} conf {cfg[1]:.2f}", "", "### Overall, day vs night", "", SUMMARY_HEADER,
                  summary_row("overall", Summary.of(sel))]
        for period in ("day", "night"):
            part = [p for p in sel if p.period == period]
            if part:
                lines.append(summary_row(period, Summary.of(part)))
        lines += ["", "### Per camera and approach", "", SUMMARY_HEADER]
        for cam in sorted({p.camera_id for p in sel}):
            cam_pairs = [p for p in sel if p.camera_id == cam]
            jid = cam_pairs[0].intersection_id
            lines.append(summary_row(f"**{jid}** {cam}", Summary.of(cam_pairs)))
            for period in ("day", "night"):
                part = [p for p in cam_pairs if p.period == period]
                if part:
                    lines.append(summary_row(f"{jid} {period}", Summary.of(part)))
            approaches = sorted({p.approach_id for p in cam_pairs})
            if len(approaches) > 1:
                for approach in approaches:
                    lines.append(summary_row(f"{jid} {approach}", Summary.of([p for p in cam_pairs if p.approach_id == approach])))
        lines += ["", "### Worst clips per camera", "", "| camera | clip | period | approach | GT | predicted | error |", "|---|---|---|---|---|---|---|"]
        for cam in sorted({p.camera_id for p in sel}):
            worst = sorted((p for p in sel if p.camera_id == cam), key=lambda p: (-abs(p.pred - p.gt), p.clip, p.approach_id))[:3]
            for p in worst:
                lines.append(f"| {p.intersection_id} {cam} | {p.clip} | {p.period} | {p.approach_id} | {p.gt} | {p.pred} | {p.pred - p.gt:+d} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def group_pairs(pairs: Iterable[Pair]) -> dict[tuple[str, float], list[Pair]]:
    grouped: dict[tuple[str, float], list[Pair]] = defaultdict(list)
    for pair in pairs:
        grouped[(pair.model, pair.conf)].append(pair)
    return grouped
