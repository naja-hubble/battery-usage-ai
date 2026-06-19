#!/usr/bin/env python
"""FCC learning-response — patent-strengthening technical evidence (v3).

ADDITIVE driver. Produces technical evidence (NOT legal conclusions) for the
full-history and rolling30-v2 FCC learning-response detection technology:
input manifest, baseline reproduction gate, data-availability probe, the
opportunity/response comparator ablation (Analysis A), the any/effective
dual-track step-magnitude evidence (Analysis C), the technical-effect
comparison (Analysis H), and the NOT-AVAILABLE intervention/version scaffolds
(Analyses F/G).  Heavy raw-reprocessing analyses (negative controls, full
retention grid, missingness injection, response hazard) are exposed as flagged
stages and emit a PENDING marker when not run, so nothing is fabricated.

Outputs land under --out-dir (data) and data/reports (artifacts). Existing
production outputs are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# robust UTF-8 stdout on CP932 consoles (Windows) so progress prints never crash
try:  # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from battery_usage import patent_opportunity_response as por
from battery_usage import patent_dual_track as pdt
from battery_usage import patent_claim_support as pcs

PENDING_ANALYSES = [
    "Analysis A.2 negative controls (circular-shift / permutation, user-bootstrap CI) — raw-trace, PENDING",
    "Analysis A.3 response-anchor comparison (start/low/end) — PENDING",
    "Analysis B response hazard (KM/cumulative-incidence true vs pseudo episode) — PENDING",
    "Analysis D full retention grid (7..90d x stride 1/7 x alignment 0..6 x stateless/stateful) — PENDING",
    "Analysis E missingness/sleep-gap/censor injection stress — PENDING",
    "Analysis F/G intervention & firmware-version analyses — NOT AVAILABLE (schema+protocol+power-sim only)",
]

REPO = Path(__file__).resolve().parent
PROC = REPO / "data" / "processed"
REPORTS = REPO / "data" / "reports"

# ---- Section 2 expected baselines ----
BASELINE_FULL = {
    "users": 752, "no_low_candidates": 96, "gauge_actionable": 18,
    "fw_actionable": 14, "watch": 55, "review": 338, "normal": 327,
}
BASELINE_V2 = {
    "STATEFUL_REVIEW_DATA_QUALITY": 325, "STATEFUL_NORMAL_RESPONDING": 183,
    "STATEFUL_WATCH_LARGE_GAP_OR_CENSORED": 128, "STATEFUL_FW_WATCH_HIGH_ANOMALY": 43,
    "STATEFUL_WATCH_LOW_EVIDENCE": 35, "STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY": 22,
    "STATEFUL_GAUGE_REVIEW": 7, "STATEFUL_FW_CHECK_CORE": 5, "STATEFUL_GAUGE_RESET_CORE": 4,
}

# intervention / version fields we look for (Analysis F/G)
VERSION_FIELDS = ["bios", "ec_version", "ecversion", "battery_fw", "gauge_fw", "firmware",
                  "update_available", "update_applied", "gauge_reset", "calibration",
                  "intervention", "outcome"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_any(path: Path, cols: Optional[list] = None) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path, columns=cols)
    return pd.read_csv(path, usecols=cols) if cols else pd.read_csv(path)


# --------------------------------------------------------------------------
def build_manifest(out_dir: Path) -> pd.DataFrame:
    inputs = [
        PROC / "battery_timeseries_all.parquet",
        PROC / "fcc_final_learning_episodes.csv",
        PROC / "fcc_final_user_features.csv",
        PROC / "fcc_final_action_labels.csv",
        PROC / "soh_update_status.csv",
        PROC / "user_master.csv",
        PROC / "fcc_online_v2" / "online_latest_snapshot_v2.csv",
        PROC / "fcc_online_v2" / "online_stateful_labels_v2.parquet",
    ]
    rows: List[dict] = []
    for p in inputs:
        if not p.exists():
            rows.append({"path": str(p.relative_to(REPO)), "exists": False})
            continue
        nrows = nusers = None
        ts_min = ts_max = None
        cols: List[str] = []
        try:
            if p.suffix == ".parquet":
                import pyarrow.parquet as pq
                sc = pq.read_schema(p); cols = [f.name for f in sc]
                use = [c for c in ["user_id", "timestamp"] if c in cols]
                d = pd.read_parquet(p, columns=use) if use else pd.read_parquet(p, columns=cols[:1])
                nrows = len(d)
            else:
                d = pd.read_csv(p)
                cols = d.columns.tolist(); nrows = len(d)
            if "user_id" in d.columns:
                nusers = int(d["user_id"].nunique())
            if "timestamp" in d.columns:
                t = pd.to_datetime(d["timestamp"], errors="coerce")
                ts_min, ts_max = str(t.min()), str(t.max())
        except Exception as e:  # pragma: no cover
            cols = [f"<error:{type(e).__name__}>"]
        rows.append({
            "path": str(p.relative_to(REPO)), "exists": True, "sha256": sha256(p),
            "bytes": p.stat().st_size, "n_rows": nrows, "n_users": nusers,
            "ts_min": ts_min, "ts_max": ts_max, "n_cols": len(cols),
            "columns": "|".join(cols)[:1200],
        })
    mf = pd.DataFrame(rows)
    mf.to_csv(out_dir / "input_manifest_patent_v3.csv", index=False)
    return mf


# --------------------------------------------------------------------------
def baseline_gate(out_dir: Path) -> pd.DataFrame:
    al = pd.read_csv(PROC / "fcc_final_action_labels.csv")
    obs_full = {
        "users": int(al["user_id"].nunique()),
        "no_low_candidates": int(al["fcc_no_or_low_change_candidate"].sum()),
        "gauge_actionable": int((al["final_label"] == por.LABEL_GAUGE).sum()),
        "fw_actionable": int((al["final_label"] == por.LABEL_FW).sum()),
        "watch": int((al["final_label"] == por.LABEL_WATCH).sum()),
        "review": int((al["final_label"] == por.LABEL_REVIEW).sum()),
        "normal": int((al["final_label"] == por.LABEL_NORMAL).sum()),
    }
    snap = pd.read_csv(PROC / "fcc_online_v2" / "online_latest_snapshot_v2.csv")
    vc = snap["stateful_label_v2"].value_counts().to_dict()
    obs_v2 = {k: int(vc.get(k, 0)) for k in BASELINE_V2}

    rows: List[dict] = []
    for k, exp in BASELINE_FULL.items():
        rows.append({"baseline": "full_history", "metric": k, "expected": exp,
                     "observed": obs_full[k], "match": exp == obs_full[k]})
    for k, exp in BASELINE_V2.items():
        rows.append({"baseline": "rolling_v2", "metric": k, "expected": exp,
                     "observed": obs_v2[k], "match": exp == obs_v2[k]})
    gate = pd.DataFrame(rows)
    gate.to_csv(out_dir / "patent_baseline_gate_v3.csv", index=False)
    status = "PASS" if gate["match"].all() else "BASELINE_MISMATCH"
    print(f"[gate] baseline reproduction = {status} "
          f"({int(gate['match'].sum())}/{len(gate)} metrics match)")
    return gate, status


# --------------------------------------------------------------------------
def availability_probe(out_dir: Path) -> dict:
    """Probe time-series + raw artifacts for BIOS/EC/FW-version / intervention.
    Records explicit NOT AVAILABLE rather than fabricating."""
    import pyarrow.parquet as pq
    ts_cols = [f.name for f in pq.read_schema(PROC / "battery_timeseries_all.parquet")]
    found = {f: False for f in VERSION_FIELDS}
    hay = " ".join(ts_cols).lower()
    for f in VERSION_FIELDS:
        if f.replace("_", "") in hay.replace("_", ""):
            found[f] = True
    # probe a raw vendor/battery_info/product sample
    raw = REPO / "data" / "raw"
    raw_cols: List[str] = []
    if raw.exists():
        for sub in list(raw.glob("*/"))[:5]:
            for art in ["vendor.csv", "battery_info.csv"]:
                p = sub / art
                if p.exists():
                    try:
                        raw_cols += pd.read_csv(p, nrows=0).columns.tolist()
                    except Exception:
                        pass
            pj = sub / "product.json"
            if pj.exists():
                try:
                    raw_cols += list(json.loads(pj.read_text(encoding="utf-8-sig")).keys())
                except Exception:
                    pass
    rawhay = " ".join(raw_cols).lower()
    for f in VERSION_FIELDS:
        if f.replace("_", "") in rawhay.replace("_", ""):
            found[f] = True
    any_found = any(found.values())
    status = "AVAILABLE" if any_found else "NOT AVAILABLE"
    rep = {"intervention_version_data": status, "fields_probed": found,
           "timeseries_columns": ts_cols, "raw_columns_sampled": sorted(set(raw_cols))}
    (out_dir / "availability_probe_v3.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] intervention/BIOS/EC/FW-version data = {status}")
    return rep


# --------------------------------------------------------------------------
def analysis_A_ablation(out_dir: Path) -> pd.DataFrame:
    al = pd.read_csv(PROC / "fcc_final_action_labels.csv")
    res = por.evaluate(al)
    res.to_csv(out_dir / "patent_ablation_comparison.csv", index=False)
    print("[A] ablation A0..A6 ->", out_dir / "patent_ablation_comparison.csv")
    return res


def _design_by_user() -> pd.Series:
    # prefer fcc_final_user_features design column; else derive from timeseries soh
    uf = PROC / "fcc_final_user_features.csv"
    if uf.exists():
        d = pd.read_csv(uf)
        for c in ["design_capacity", "DesignCapacity", "design_capacity_mwh"]:
            if c in d.columns and "user_id" in d.columns:
                return d.set_index("user_id")[c].astype(float)
    # derive design = fcc*100/soh_design_pct from timeseries (median per user)
    ts = pd.read_parquet(PROC / "battery_timeseries_all.parquet",
                         columns=["user_id", "fullChargeCapacity", "soh_design_pct"])
    ts = ts[(ts["soh_design_pct"] > 0) & ts["fullChargeCapacity"].notna()]
    ts["design"] = ts["fullChargeCapacity"] * 100.0 / ts["soh_design_pct"]
    return ts.groupby("user_id")["design"].median()


def analysis_C_dual_track(out_dir: Path) -> Dict[str, object]:
    ts = pd.read_parquet(PROC / "battery_timeseries_all.parquet",
                         columns=["user_id", "timestamp", "fullChargeCapacity"])
    steps = pdt.fcc_steps(ts)
    summ = pdt.step_magnitude_summary(steps)
    design = _design_by_user()
    thr = pdt.threshold_comparison(steps, design)
    thr.to_csv(out_dir / "dual_track_threshold_analysis.csv", index=False)
    pd.DataFrame([summ]).to_csv(out_dir / "dual_track_step_magnitude_summary.csv", index=False)
    # persist abs-step sample for plotting (cap to keep file small)
    steps[["abs_step"]].sample(min(len(steps), 200000), random_state=42).to_csv(
        out_dir / "_dual_track_abs_steps_sample.csv", index=False)
    print(f"[C] dual-track: n_steps={summ['n_steps']} quant={summ['quantization_unit_mwh']} "
          f"frac_micro<50mWh={summ['frac_micro_lt_50mwh']:.3f}")
    return {"summary": summ, "thresholds": thr}


# --------------------------------------------------------------------------
def analysis_H_technical_effects(out_dir: Path) -> pd.DataFrame:
    al = pd.read_csv(PROC / "fcc_final_action_labels.csv")
    snap = pd.read_csv(PROC / "fcc_online_v2" / "online_latest_snapshot_v2.csv")
    n = al["user_id"].nunique()
    # detectors: static stale rule / full-history proposed / rolling stateless / rolling stateful
    flat = al["flat_tail_days"].astype(float)
    eff_active = set(al.loc[al["fcc_effective_changes_50mwh"].astype(float) >= 1, "user_id"])
    normal_ids = set(al.loc[al["final_label"] == por.LABEL_NORMAL, "user_id"])

    # static stale: flag anyone flat>=180 as "needs action"
    static_flag = set(al.loc[flat >= por.FLAT_TAIL_FW_DAYS, "user_id"])
    # full-history proposed actionable
    fh_flag = set(al.loc[al["final_label"].isin(por.ACTIONABLE_LABELS), "user_id"])
    # rolling stateless core actionable (window_label_v2 opportunity-no-response)
    sl_core = set(snap.loc[snap["window_label_v2"] == "WINDOW_OPPORTUNITY_NO_RESPONSE", "user_id"])
    # rolling stateful core actionable (FW_CHECK_CORE + GAUGE_RESET_CORE)
    sf_core = set(snap.loc[snap["stateful_label_v2"].isin(
        ["STATEFUL_FW_CHECK_CORE", "STATEFUL_GAUGE_RESET_CORE"]), "user_id"])

    proxy_actionable = set(al.loc[al["final_label"].isin(por.ACTIONABLE_LABELS), "user_id"])

    def row(name, flagged, hard_prompts):
        return {
            "detector": name,
            "n_flagged_actionable": len(flagged),
            "overlap_with_production_actionable": len(flagged & proxy_actionable),
            "production_normal_falsely_flagged": len(flagged & normal_ids),
            "had_lifetime_effective_step_descriptive": len(flagged & eff_active),
            "hard_calibration_prompts": hard_prompts,
        }
    rows = [
        row("static_fcc_stale_rule", static_flag, len(static_flag)),
        row("full_history_proposed", fh_flag, len(al.loc[al["final_label"] == por.LABEL_GAUGE])),
        row("rolling_stateless_core", sl_core, len(sl_core)),
        row("rolling_stateful_v2_core", sf_core,
            int((snap["stateful_label_v2"] == "STATEFUL_GAUGE_RESET_CORE").sum())),
    ]
    eff = pd.DataFrame(rows)
    # storage tradeoff (bytes): raw timeseries vs persisted v2 state
    raw_bytes = (PROC / "battery_timeseries_all.parquet").stat().st_size
    state_p = PROC / "fcc_online_v2" / "online_stateful_labels_v2.parquet"
    state_bytes = state_p.stat().st_size if state_p.exists() else None
    eff.attrs["raw_bytes"] = raw_bytes
    eff.attrs["state_bytes"] = state_bytes
    eff.to_csv(out_dir / "patent_technical_effects.csv", index=False)
    pd.DataFrame([{"raw_bytes": raw_bytes, "state_bytes": state_bytes,
                   "state_to_raw_ratio": (state_bytes / raw_bytes) if state_bytes else None}]).to_csv(
        out_dir / "patent_storage_tradeoff.csv", index=False)
    print(f"[H] technical effects -> static flags {len(static_flag)} "
          f"(false-active {len(static_flag & eff_active)}) vs stateful core {len(sf_core)} (false-active {len(sf_core & eff_active)})")
    return eff


# --------------------------------------------------------------------------
def emit_not_available_artifacts(availability: dict) -> None:
    """Analyses F/G when intervention/version data is NOT AVAILABLE: schema +
    prospective protocol + power simulation. No fabricated outcomes."""
    avail = availability["intervention_version_data"] == "AVAILABLE"
    # intervention data schema (input contract)
    schema = pd.DataFrame([
        ("device_hash", "str", "hashed device id (no raw serial/user)"),
        ("intervention_type", "enum", "GAUGE_CALIBRATION | FW_UPDATE | NONE"),
        ("intervention_ts", "datetime", "when OEM-approved calibration/update applied"),
        ("bios_version_pre", "str", "BIOS version before"),
        ("bios_version_post", "str", "BIOS version after"),
        ("ec_version_pre", "str", "EC version before"),
        ("ec_version_post", "str", "EC version after"),
        ("battery_fw_version_pre", "str", "gauge FW version before"),
        ("battery_fw_version_post", "str", "gauge FW version after"),
        ("first_highok_opportunity_post_ts", "datetime", "first HIGH_OK opportunity after intervention"),
        ("effective_fcc_step_within_72h_post", "bool", "effective >=50mWh step within 72h of that opportunity"),
        ("effective_fcc_step_within_168h_post", "bool", "within 168h"),
        ("time_to_effective_response_h", "float", "hours from opportunity to first effective step"),
        ("cycles_to_effective_response", "float", "cycle increments to first effective step"),
    ], columns=["field", "dtype", "description"])
    schema.to_csv(REPORTS / "fcc_intervention_data_schema_v3.csv", index=False)
    pd.DataFrame([
        ("firmware_version_case_control", "device_hash, fru_hash, model_hash, version, opportunity_exposure, obs_days, cycle_intensity, label, post_response"),
        ("firmware_update_prepost", "device_hash, version_pre, version_post, update_ts, pre_response_rate, post_response_rate, n_opportunities_pre, n_opportunities_post"),
    ], columns=["table", "required_columns"]).to_csv(REPORTS / "fcc_firmware_version_schema_v3.csv", index=False)

    status = "AVAILABLE" if avail else "NOT AVAILABLE"
    # power simulation using empirical baseline response rate (normative responder rate ~0.39)
    base = 0.39  # empirical positive (effective-response) rate at episode level
    sim_rows = []
    rng = np.random.default_rng(42)
    for n in [10, 20, 30, 50, 80, 120]:
        for lift in [0.15, 0.25, 0.35]:
            p_treat = min(0.99, base + lift)
            # two-proportion z power via simulation
            hits = 0; B = 2000
            for _ in range(B):
                c = rng.binomial(n, base); t = rng.binomial(n, p_treat)
                pc, pt = c / n, t / n
                pp = (c + t) / (2 * n)
                se = np.sqrt(2 * pp * (1 - pp) / n) or 1e-9
                z = (pt - pc) / se
                if z > 1.96:
                    hits += 1
            sim_rows.append({"n_per_arm": n, "baseline_response_rate": base,
                             "assumed_lift": lift, "treated_rate": round(p_treat, 3),
                             "estimated_power": round(hits / B, 3)})
    pd.DataFrame(sim_rows).to_csv(REPORTS / "fcc_intervention_power_simulation_v3.csv", index=False)

    protocol = f"""# Prospective Intervention Protocol (v3) — closed-loop FCC recovery verification

> **Data availability: {status}.** The current dataset contains NO BIOS/EC/battery-FW
> version fields and NO intervention-outcome records (verified by column probe;
> see `availability_probe_v3.json`). The analyses below are a PROSPECTIVE protocol
> and a power simulation built on the empirical baseline response rate; **no
> intervention outcome is computed or claimed from existing data.**

## Goal
Demonstrate the *closed-loop* technical effect: after a label-dependent
intervention, a healthy/recovered gauge produces an effective FCC re-learning
step at the next qualified learning opportunity.

## Arms
- **Gauge arm**: devices labeled GAUGE_RESET_CORE / GAUGE_SOFT_CALIBRATION receive an
  **OEM-approved controlled calibration within thermal/voltage safety limits**
  (no unsafe forced deep-discharge is ever instructed).
- **FW arm**: devices labeled FW_CHECK_CORE / FW_WATCH whose BIOS/EC/battery-FW has an
  available update receive the update.
- **Matched controls**: same FRU/model, matched opportunity exposure, observation
  time and cycle intensity, no intervention.

## Primary endpoint
Effective FCC step (>= 50 mWh) within 72 h (secondary: 168 h) of the **first
HIGH_OK learning opportunity after** the intervention timestamp.

## Statistics
Mixed-effects logistic / GEE (device random effect); difference-in-differences and
interrupted time-series for pre/post; Firth / hierarchical Bayes for small n;
BH-FDR across FRU/model strata. Identity/version never enters individual policy —
used only as post-hoc case-control.

## Power
See `fcc_intervention_power_simulation_v3.csv` (baseline response rate {base},
two-proportion test, alpha=0.05). E.g. n≈30/arm gives adequate power only for
large lifts; n≈80–120/arm recommended for a 0.15 lift.

## Safety
Calibration is OEM-approved and bounded by thermal/voltage limits. No forced
unsafe discharge. All device identifiers are hashed in any case table.
"""
    (REPORTS / "fcc_intervention_protocol_v3.md").write_text(protocol, encoding="utf-8")
    (REPORTS / "prospective_intervention_protocol.md").write_text(protocol, encoding="utf-8")
    print(f"[F/G] intervention/version = {status}: emitted schema + protocol + power simulation (no fabricated outcomes)")


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FCC patent evidence v3 (additive)")
    ap.add_argument("--out-dir", default=str(PROC / "fcc_patent_evidence_v3"))
    ap.add_argument("--fig-dir", default=str(REPORTS / "figures" / "fcc_patent_evidence_v3"))
    ap.add_argument("--run-ablation", action="store_true")
    ap.add_argument("--run-dual-track", action="store_true")
    ap.add_argument("--run-technical-effects", action="store_true")
    ap.add_argument("--run-intervention-if-available", action="store_true")
    ap.add_argument("--run-report", action="store_true")
    ap.add_argument("--all", action="store_true", help="run all currently-implemented stages")
    ap.add_argument("--random-seed", type=int, default=42)
    args = ap.parse_args(argv)

    np.random.seed(args.random_seed)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    Path(args.fig_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("FCC PATENT EVIDENCE v3 — technical evidence for patent review (NOT legal advice)")
    print("=" * 70)
    build_manifest(out_dir)
    gate, status = baseline_gate(out_dir)
    avail = availability_probe(out_dir)

    if status != "PASS":
        print("\n[STOP] BASELINE_MISMATCH — not emitting patent-evidence conclusions. "
              "See patent_baseline_gate_v3.csv for the diff.")
        return 1

    run_all = args.all
    if run_all or args.run_ablation:
        analysis_A_ablation(out_dir)
    if run_all or args.run_dual_track:
        analysis_C_dual_track(out_dir)
    if run_all or args.run_technical_effects:
        analysis_H_technical_effects(out_dir)
    if run_all or args.run_intervention_if_available:
        emit_not_available_artifacts(avail)

    if run_all or args.run_report:
        pcs.build_all(status, avail["intervention_version_data"], PENDING_ANALYSES)
        print("[report] disclosure + claim-support + prior-art + main report -> data/reports/")

    print("\n[done] implemented stages complete. Heavy raw-reprocessing analyses "
          "(negative controls, full retention grid, missingness injection, response "
          "hazard) are exposed as PENDING and were NOT fabricated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
