"""Assemble a markdown report from the cohort table, summary and figures."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .config import Config


def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _rel(path: Path, start: Path) -> str:
    try:
        return str(path.relative_to(start)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def build_report(
    cfg: Config,
    cohort: pd.DataFrame,
    summary: pd.DataFrame,
    cohort_figs: Dict[str, Path],
    user_figs: Optional[Dict[str, Path]] = None,
) -> Path:
    cfg.ensure_dirs()
    out_path = cfg.reports_dir / "report.md"
    base = cfg.reports_dir
    lines: List[str] = []

    n = len(cohort)
    lines.append("# Battery Usage Analysis — Cohort Report\n")
    lines.append(f"Generated over **{n} users** from bucket `{cfg.s3['bucket']}`.\n")

    # ---- cohort summary table ----
    lines.append("## Cohort summary\n")
    lines.append("Distribution of key metrics across the cohort:\n")
    lines.append("| metric | mean | median | std | min | max |")
    lines.append("|---|---|---|---|---|---|")
    for metric, row in summary.iterrows():
        lines.append(
            f"| {metric} | {_fmt(row['mean'])} | {_fmt(row['median'])} | "
            f"{_fmt(row['std'])} | {_fmt(row['min'])} | {_fmt(row['max'])} |"
        )
    lines.append("")

    # ---- cohort figures ----
    if cohort_figs:
        lines.append("## Cohort figures\n")
        for name, path in cohort_figs.items():
            title = name.replace("cohort_", "").replace(".png", "").replace("_", " ").title()
            lines.append(f"### {title}\n")
            lines.append(f"![{title}]({_rel(path, base)})\n")

    # ---- usage personas ----
    if "persona_label" in cohort.columns and cohort["persona"].nunique() > 1:
        lines.append("## Usage personas\n")
        grp = cohort.groupby("persona_label")
        lines.append("| persona | users | AC time ratio | mean % rem. | cycles/yr | SOH % (peak) |")
        lines.append("|---|---|---|---|---|---|")
        for lbl, g in grp:
            _empty = pd.Series(dtype=float)
            lines.append(
                f"| {lbl} | {len(g)} | {_fmt(g['ac_time_ratio'].mean())} | "
                f"{_fmt(g['mean_pct_remaining'].mean())} | {_fmt(g.get('cycles_per_year', _empty).mean())} | "
                f"{_fmt(g.get('soh_peak_pct', _empty).mean())} |"
            )
        lines.append("")

    # ---- per-user table ----
    lines.append("## Per-user metrics\n")
    show_cols = [c for c in [
        "display_id", "device_model", "observation_days", "n_samples",
        "soh_peak_pct", "soh_design_pct", "capacity_fade_pct",
        "cycle_count_last", "cycles_per_year", "ac_time_ratio",
        "mean_pct_remaining", "n_discharge_sessions", "mean_dod_pct",
    ] if c in cohort.columns]
    lines.append("| " + " | ".join(show_cols) + " |")
    lines.append("|" + "|".join("---" for _ in show_cols) + "|")
    for _, r in cohort.iterrows():
        cells = []
        for c in show_cols:
            v = r[c]
            cells.append(_fmt(v) if isinstance(v, float) else (str(v) if pd.notna(v) else "—"))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # ---- per-user detail figures ----
    if user_figs:
        lines.append("## Per-user detail (sample)\n")
        for name, path in user_figs.items():
            lines.append(f"![{name}]({_rel(path, base)})\n")

    lines.append("\n---\n")
    lines.append("### Notes & caveats\n")
    lines.append(
        "- `acdcMode`: 1 = on AC, 0 = on battery (confirmed against capacity trend).\n"
        "- SOH (vs peak) uses the highest observed full-charge capacity as the healthy "
        "reference; SOH (vs design) uses the battery's design capacity. New packs can read >100%.\n"
        "- `ac_time_ratio` and other time-weighted ratios cap inter-sample gaps "
        f"at {cfg.analysis['max_sample_gap_hours']} h to avoid counting logger-asleep periods.\n"
        "- Battery time-series files are cumulative; only the latest per user is analysed.\n"
        "- `fade_pct_per_year` / `fade_pct_per_100_cycles` are *post-peak* rates (fade since the "
        "healthiest observed sample over the interval since that sample); short post-peak spans "
        "are suppressed to avoid noise.\n"
        "- Users are shown by pseudonymous `display_id`; the raw id mapping stays in the "
        "git-ignored `cohort_features.csv` / `manifest.json`.\n"
        "- Cohort selection is seeded random over users with real history — not a uniform "
        "sample of the whole fleet.\n"
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {out_path}")
    return out_path
