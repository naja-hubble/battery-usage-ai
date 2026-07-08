#!/usr/bin/env python
"""OD2 re-analysis - Phase 1: opportunity extractor + END-anchored audit + OLD-vs-NEW.

Re-derives the fuel-gauge "learning opportunity" under the corrected relearn logic
(Type A: full->deep(<=6%)->full; Type B: charging through 60-80% -> full) and compares
it, apples-to-apples, against the OD1 discharge-band opportunity (80/20/80 etc.).

Both sides use the SAME response convention -- END-anchored 72h window, effective step
>= 50 mWh, ok-quality only -- so the OLD vs NEW deltas are real, not convention artifacts
(the OD1 *offline* layer was START-anchored/any-change and would fabricate a fake delta).
The OD1 side is computed with the production online causal detector, which is already
END-anchored + 50 mWh.

Nothing in the OD1 pipeline is modified. Outputs go to data/processed/fcc_relearn_od2/
phase1/ and data/reports/fcc_relearn_od2_comparison_report.md.

Usage:
    python analyze_fcc_relearn_od2_phase1.py [--limit N] [--sensitivity]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from battery_usage.relearn_od2 import (
    Od2Config, TypeADef, TypeBDef, DEFAULT_OD2_CONFIG,
    process_user_od2, add_union_flags, CODE_VERSION,
)
from battery_usage.online_episode_detector import (
    extract_episodes_causal, DEFAULT_ONLINE_CONFIG, EPISODE_THRESHOLDS,
)

REPO = Path(__file__).resolve().parent
PROC = REPO / "data" / "processed"
PARQUET = PROC / "battery_timeseries_all.parquet"
OUT = PROC / "fcc_relearn_od2" / "phase1"
REPORTS = REPO / "data" / "reports"
PRIMARY_W = 72
STATUS_ORDER = ["responded", "no_response", "censored", "unknown"]


# --------------------------------------------------------------------------- #
def load_cohort(limit: int | None) -> pd.DataFrame:
    cols = ["user_id", "timestamp", "chargeStatus", "acdcMode",
            "remainingCapacityInPercentage", "cycleCount", "fullChargeCapacity",
            "soh_design_pct"]
    df = pd.read_parquet(PARQUET, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if limit:
        keep = df["user_id"].drop_duplicates().head(limit)
        df = df[df["user_id"].isin(keep)]
    return df


def extract_all(df: pd.DataFrame, cfg: Od2Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (od2 episode frame with union flags, old-band episode frame)."""
    od2_rows: List[Dict] = []
    old_rows: List[Dict] = []
    groups = df.groupby("user_id", sort=False)
    n = groups.ngroups
    for i, (uid, g) in enumerate(groups):
        od2_rows.extend(process_user_od2(uid, g, cfg))
        old_rows.extend(extract_episodes_causal(g, uid, DEFAULT_ONLINE_CONFIG))
        if (i + 1) % 100 == 0:
            print(f"  ... {i + 1}/{n} users", flush=True)
    od2 = add_union_flags(pd.DataFrame(od2_rows))
    old = pd.DataFrame(old_rows)
    return od2, old


# --------------------------------------------------------------------------- #
def status_counts(sub: pd.DataFrame, w: int) -> Dict[str, int]:
    col = f"response_status_{w}h"
    vc = sub[col].value_counts() if col in sub else pd.Series(dtype=int)
    return {s: int(vc.get(s, 0)) for s in STATUS_ORDER}


def response_rate(sc: Dict[str, int]) -> float:
    denom = sc["responded"] + sc["no_response"]
    return round(sc["responded"] / denom, 4) if denom else float("nan")


def episode_summary(od2: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    """One row per opportunity definition: episode/user counts + ok-quality 72h response."""
    rows = []

    def _row(label, sub, ok_sub):
        sc = status_counts(ok_sub, PRIMARY_W)
        rows.append({
            "definition": label,
            "n_episodes": int(len(sub)),
            "n_users": int(sub["user_id"].nunique()) if len(sub) else 0,
            "n_ok": int(len(ok_sub)),
            "n_users_with_ok": int(ok_sub["user_id"].nunique()) if len(ok_sub) else 0,
            "ok_responded_72h": sc["responded"],
            "ok_no_response_72h": sc["no_response"],
            "ok_censored_72h": sc["censored"],
            "ok_response_rate_72h": response_rate(sc),
        })

    # OLD bands (END-anchored, 50 mWh via online detector)
    for name in EPISODE_THRESHOLDS:
        sub = old[old["threshold_name"] == name] if len(old) else old
        ok = sub[sub["episode_quality"] == "ok"] if len(sub) else sub
        _row(f"OLD:{name}", sub, ok)

    # NEW Type A / Type B (per-type, all rows)
    for t, lbl in (("A", "OD2:typeA"), ("B", "OD2:typeB")):
        sub = od2[od2["opportunity_type"] == t] if len(od2) else od2
        ok = sub[sub["episode_quality"] == "ok"] if len(sub) else sub
        _row(lbl, sub, ok)

    # NEW union (dedup on END; one audit per relearn completion)
    uni = od2[od2["is_union_primary"]] if len(od2) else od2
    uok = uni[uni["episode_quality"] == "ok"] if len(uni) else uni
    _row("OD2:union", uni, uok)
    return pd.DataFrame(rows)


def coverage_movement(od2: pd.DataFrame, old: pd.DataFrame, all_users: pd.Index) -> pd.DataFrame:
    """Per-user 2x2: had an OK opportunity under OD1 vs OD2 (union). Gauge candidates = no opp."""
    old_ok = set(old[old["episode_quality"] == "ok"]["user_id"].unique()) if len(old) else set()
    uni = od2[od2["is_union_primary"]] if len(od2) else od2
    od2_ok = set(uni[uni["episode_quality"] == "ok"]["user_id"].unique()) if len(uni) else set()
    rows = []
    for label, cond in [
        ("old_ok & od2_ok", lambda u: u in old_ok and u in od2_ok),
        ("old_ok & od2_NO", lambda u: u in old_ok and u not in od2_ok),
        ("old_NO & od2_ok", lambda u: u not in old_ok and u in od2_ok),
        ("old_NO & od2_NO", lambda u: u not in old_ok and u not in od2_ok),
    ]:
        rows.append({"cell": label, "n_users": sum(1 for u in all_users if cond(u))})
    rows.append({"cell": "TOTAL users", "n_users": len(all_users)})
    rows.append({"cell": "users_with_od2_opportunity(any_quality)",
                 "n_users": int(uni["user_id"].nunique()) if len(uni) else 0})
    rows.append({"cell": "users_with_ZERO_od2_opportunity(gauge_candidates)",
                 "n_users": len(all_users) - (int(uni["user_id"].nunique()) if len(uni) else 0)})
    return pd.DataFrame(rows)


def type_b_diagnostics(od2: pd.DataFrame) -> Dict[str, object]:
    b = od2[od2["opportunity_type"] == "B"]
    a = od2[od2["opportunity_type"] == "A"]
    both = od2[od2["union_types"] == "A,B"]["end_idx"].count() if len(od2) else 0
    d = {}
    if len(b):
        d["typeB_arm_to_full_h_median"] = round(float(b["arm_to_full_duration_h"].median()), 2)
        d["typeB_arm_to_full_h_p90"] = round(float(b["arm_to_full_duration_h"].quantile(0.9)), 2)
        d["typeB_arm_to_full_gt48h_frac"] = round(float((b["arm_to_full_duration_h"] > 48).mean()), 4)
        d["typeB_band_entry_rsoc_median"] = round(float(b["band_entry_rsoc"].median()), 1)
    if len(a):
        d["typeA_depth_median"] = round(float(a["episode_depth"].median()), 1)
        d["typeA_low_rsoc_median"] = round(float(a["low_rsoc"].median()), 1)
    d["typeA_typeB_coincident_END_rows"] = int(both)
    if len(od2):
        d["pre_end_gap_gt12h_frac"] = round(float((od2["pre_end_gap_h"] > 12).mean()), 4)
    return d


# --------------------------------------------------------------------------- #
def sensitivity_grid(df: pd.DataFrame) -> pd.DataFrame:
    """One-factor-at-a-time variant sweep: episode/user counts + ok 72h response rate."""
    variants: List[tuple[str, Od2Config]] = []
    base = DEFAULT_OD2_CONFIG
    for full in (97.0, 99.0, 100.0):
        variants.append((f"FULL={int(full)}",
                         Od2Config(type_a=TypeADef(full_pct=full, deep_pct=6.0),
                                   type_b=TypeBDef(full_pct=full))))
    for deep in (4.0, 6.0, 8.0, 10.0):
        variants.append((f"DEEP={int(deep)}",
                         Od2Config(type_a=TypeADef(deep_pct=deep), type_b=base.type_b)))
    for lo, hi in ((55.0, 80.0), (60.0, 80.0), (60.0, 85.0)):
        variants.append((f"BAND={int(lo)}-{int(hi)}",
                         Od2Config(type_a=base.type_a,
                                   type_b=TypeBDef(band_lo=lo, band_hi=hi, abort_pct=min(lo, 60.0)))))
    for ab in (50.0, 60.0):
        variants.append((f"ABORT={int(ab)}",
                         Od2Config(type_a=base.type_a, type_b=TypeBDef(abort_pct=ab))))

    rows = []
    groups = list(df.groupby("user_id", sort=False))
    for label, cfg in variants:
        recs: List[Dict] = []
        for uid, g in groups:
            recs.extend(process_user_od2(uid, g, cfg))
        d = pd.DataFrame(recs)
        if len(d):
            d = add_union_flags(d)
        for t, tl in (("A", "typeA"), ("B", "typeB")):
            sub = d[d["opportunity_type"] == t] if len(d) else d
            ok = sub[sub["episode_quality"] == "ok"] if len(sub) else sub
            sc = status_counts(ok, PRIMARY_W) if len(ok) else {s: 0 for s in STATUS_ORDER}
            rows.append({"variant": label, "type": tl,
                         "n_episodes": int(len(sub)),
                         "n_users": int(sub["user_id"].nunique()) if len(sub) else 0,
                         "n_ok": int(len(ok)),
                         "ok_response_rate_72h": response_rate(sc)})
        uni = d[d["is_union_primary"]] if len(d) else d
        uok = uni[uni["episode_quality"] == "ok"] if len(uni) else uni
        sc = status_counts(uok, PRIMARY_W) if len(uok) else {s: 0 for s in STATUS_ORDER}
        rows.append({"variant": label, "type": "union",
                     "n_episodes": int(len(uni)),
                     "n_users": int(uni["user_id"].nunique()) if len(uni) else 0,
                     "n_ok": int(len(uok)),
                     "ok_response_rate_72h": response_rate(sc)})
        print(f"  [sensitivity] {label} done", flush=True)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def write_report(summ, cov, diag, n_users, sens=None):
    def tbl(df):
        return df.to_markdown(index=False)
    lines = []
    lines.append("# OD2 re-analysis - Phase 1: OLD (discharge-band) vs NEW (gauge-relearn) opportunities\n")
    lines.append(f"_Code version: {CODE_VERSION}. Cohort: {n_users} users, "
                 f"battery_timeseries_all.parquet. Response convention (both sides): "
                 f"END-anchored, effective step >=50 mWh, ok-quality, 72h primary window._\n")
    lines.append("> The corrected fuel-gauge relearn logic replaces the OD1 high->low->high "
                 "discharge bands (80/20/80, 90/10/90, 85/15/85) with two real mechanisms: "
                 "**Type A** full->RSOC<=6%->full, and **Type B** charging through 60-80% -> full. "
                 "END = full-charge attainment in both. OD1 files are untouched.\n")
    lines.append("## 1. Episode & response summary (unified END-anchored / 50 mWh convention)\n")
    lines.append(tbl(summ) + "\n")
    lines.append("## 2. Per-user opportunity coverage movement (OD1 vs OD2 union)\n")
    lines.append(tbl(cov) + "\n")
    lines.append("Users who had NO OD1 opportunity but DO under OD2 are newly auditable; "
                 "users with ZERO OD2 opportunity are the gauge-reset candidate pool "
                 "(no relearn chance observed).\n")
    lines.append("## 3. Type A / Type B diagnostics\n")
    lines.append("\n".join(f"- **{k}**: {v}" for k, v in diag.items()) + "\n")
    if sens is not None:
        lines.append("## 4. Sensitivity grid (one-factor-at-a-time)\n")
        lines.append(tbl(sens) + "\n")
    lines.append("## Notes / caveats\n")
    lines.append("- OLD-side response rates are recomputed END-anchored/50 mWh (NOT the "
                 "production START-anchored/any-change 71.5%), so old vs new is comparable.\n")
    lines.append("- Type B has no discharge low; `low_ts`/`low_rsoc` = band-entry (arming) sample.\n")
    lines.append("- `union` de-duplicates coincident A/B ENDs (audited once). Per-type rows are descriptive.\n")
    (REPORTS / "fcc_relearn_od2_comparison_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only first N users (smoke test)")
    ap.add_argument("--sensitivity", action="store_true", help="run the OFAT variant grid")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[1/4] loading cohort ({'limit ' + str(args.limit) if args.limit else 'full 752'})...", flush=True)
    df = load_cohort(args.limit)
    all_users = df["user_id"].drop_duplicates()
    n_users = len(all_users)
    print(f"      {n_users} users, {len(df):,} rows", flush=True)

    print("[2/4] extracting OD2 (Type A/B) + OLD bands, END-anchored audit...", flush=True)
    od2, old = extract_all(df, DEFAULT_OD2_CONFIG)
    od2.to_parquet(OUT / "od2_opportunities.parquet", index=False)
    print(f"      OD2 episodes: {len(od2):,}  |  OLD episodes: {len(old):,}", flush=True)

    print("[3/4] summarising + comparison...", flush=True)
    summ = episode_summary(od2, old)
    cov = coverage_movement(od2, old, all_users)
    diag = type_b_diagnostics(od2)
    summ.to_csv(OUT / "od2_old_vs_new_episode_comparison.csv", index=False)
    cov.to_csv(OUT / "od2_old_vs_new_user_movement.csv", index=False)
    pd.DataFrame([diag]).to_csv(OUT / "od2_typeAB_diagnostics.csv", index=False)
    print(summ.to_string(index=False), flush=True)
    print(cov.to_string(index=False), flush=True)
    print(diag, flush=True)

    sens = None
    if args.sensitivity:
        print("[4/4] sensitivity grid...", flush=True)
        sens = sensitivity_grid(df)
        sens.to_csv(OUT / "od2_sensitivity_grid.csv", index=False)
        print(sens.to_string(index=False), flush=True)
    else:
        print("[4/4] (skipping sensitivity grid; pass --sensitivity to run)", flush=True)

    write_report(summ, cov, diag, n_users, sens)
    print(f"\nDONE. Report: {REPORTS / 'fcc_relearn_od2_comparison_report.md'}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
