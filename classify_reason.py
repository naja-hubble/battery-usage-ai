"""Root-cause sub-classification of stale-SoH users — USAGE-BASED (model-agnostic).

An earlier version keyed a class on the device model ("X1 Carbon/Yoga Gen<=11"), but
the freeze is NOT an X1-only phenomenon and model-name / generation lookups do not
generalize. This version classifies the freeze using ONLY transferable usage-behaviour
features (cycling rate, AC-tethering, discharge depth). Users frozen DESPITE adequate
usage are labelled hardware/firmware-suspected — defined BY EXCLUSION, not by model
name. Which machines populate that group is reported descriptively (see ``main`` /
plot_reason_trends), never baked into the classification rule.

Classes (active users stay "active"):
  USE_ac_bound_no_cycling   always-on-AC (ac_time_ratio>=0.80) + low cycling (cycles/yr < p25)
  USE_low_cycling           low cycling (cycles/yr < p25)
  USE_shallow_discharge     TRULY shallow: never reaches deep RSOC (min_rsoc>10) and no full-range discharge
  HW_firmware_suspected     cycles + reaches deep/full-range discharge yet frozen -> gauge/firmware (model-agnostic)

The RSOC re-exploration (PDF decoder + RSOC/charge-range features) confirmed:
RSOC depth is NOT an independent driver of FCC updates beyond cycling (its partials
vs the update rate collapse to |rho|<=0.12 once cycling is controlled; frozen users
persist even among the heaviest full-range dischargers). It did, however, expose that
the previous mean_dod_pct-based shallow rule was an AVERAGING ARTIFACT (frequent
top-ups dilute occasional deep drains): 25/32 "shallow" users actually reach deep RSOC.
So shallow is now keyed on min_rsoc (actual depth reached); the mislabeled deep-yet-
frozen users move to HW_firmware_suspected, which both adversarial checks rated
"residual_is_hardware".

    python classify_reason.py   # writes data/processed/soh_reason_labeled.csv
"""
from __future__ import annotations

import pandas as pd

from battery_usage.config import load_config

# Cohort-derived thresholds (752-user cohort). Usage / RSOC-depth features only — no model/vendor.
CYC_LO = 30.27           # p25 of cycles_per_year ("low cycling")
AC_HI = 0.80             # high AC-tethering
MIN_RSOC_SHALLOW = 10    # never reaches RSOC <= this => truly shallow (not an averaged-DoD artifact)

CLASS_ORDER = [
    "USE_ac_bound_no_cycling", "USE_low_cycling", "USE_shallow_discharge",
    "HW_firmware_suspected",
]
CLASS_COLORS = {
    "USE_ac_bound_no_cycling": "darkorange",
    "USE_shallow_discharge": "gold",
    "USE_low_cycling": "olive",
    "HW_firmware_suspected": "darkred",
    "active": "steelblue",
}

# Columns DELIBERATELY EXCLUDED from any learning / modeling feature set.
# device_model / batt_vendor / manufacturer are HARDWARE IDENTITY -> descriptive & reporting
# ONLY (user directive); never feed them to a model, tree, importance run or clustering. The
# rest are outcome-leaky, downstream consequences, sampling controls, or identifiers.
EXCLUDED_FROM_LEARNING = {
    # hardware identity / hardware-size attribute — descriptive only
    "device_model", "batt_vendor", "manufacturer", "design_capacity",
    # outcome / leaky (the freeze itself)
    "soh_update_status", "soh_reason_class", "fcc_distinct", "fcc_changes",
    "fcc_change_rate_per_100d", "soh_flat_tail_days", "flat_pct_of_span", "stale_days",
    "fcc_first", "fcc_last", "fcc_peak",
    # downstream consequence of a frozen / healthy gauge
    "soh_design_pct", "soh_peak_pct", "capacity_fade_pct",
    "fade_pct_per_100_cycles", "fade_pct_per_year",
    # sampling / observation-window controls
    "n_samples", "median_sample_gap_min", "observation_days",
    # identifiers / timestamps
    "safe_id", "user_id", "display_id", "first_ts", "last_ts", "soh_last_change_ts",
}


def learning_features(df: pd.DataFrame) -> list:
    """Numeric columns eligible as LEARNING features — excludes device_model, batt_vendor
    and all leaky / consequence / control / identifier columns (see EXCLUDED_FROM_LEARNING)."""
    return [c for c in df.select_dtypes("number").columns if c not in EXCLUDED_FROM_LEARNING]


def classify_row(r) -> str:
    if r["soh_update_status"] == "active":
        return "active"
    ac, cyc = r.get("ac_time_ratio"), r.get("cycles_per_year")
    low_cyc = pd.notna(cyc) and cyc < CYC_LO
    if pd.notna(ac) and ac >= AC_HI and low_cyc:
        return "USE_ac_bound_no_cycling"          # always plugged, barely cycles
    if low_cyc:
        return "USE_low_cycling"                  # low cycling
    # Truly shallow: never reaches deep RSOC AND never a full-range discharge.
    mr, nfr = r.get("min_rsoc"), r.get("n_full_range_dis")
    if pd.notna(mr) and pd.notna(nfr) and mr > MIN_RSOC_SHALLOW and nfr == 0:
        return "USE_shallow_discharge"
    return "HW_firmware_suspected"   # cycles + reaches deep/full-range discharge yet frozen -> hardware


def main() -> None:
    cfg = load_config()
    t = pd.read_csv(cfg.processed_dir / "soh_reason_features.csv")
    t["soh_reason_class"] = t.apply(classify_row, axis=1)

    out = cfg.processed_dir / "soh_reason_labeled.csv"
    t.to_csv(out, index=False)
    print("wrote", out, t.shape)

    flagged = t[t["soh_update_status"] != "active"]
    print(f"\nroot-cause classes among {len(flagged)} stale/very_stale users:")
    tab = (flagged.groupby(["soh_reason_class", "soh_update_status"]).size()
           .unstack(fill_value=0).reindex(CLASS_ORDER))
    tab["total"] = tab.sum(axis=1)
    print(tab.to_string())
    usage = flagged["soh_reason_class"].str.startswith("USE_").sum()
    print(f"\nUSAGE-explained: {usage} | hardware/firmware-suspected: {len(flagged) - usage}")

    # Descriptive (NOT a classification feature): which machines populate the
    # usage-UNEXPLAINED group? Demonstrates the freeze is not X1-only.
    hw = flagged[flagged["soh_reason_class"] == "HW_firmware_suspected"]
    x1 = int(hw["device_model"].fillna("").str.contains("X1").sum())
    print(f"\nHW_firmware_suspected (n={len(hw)}): X1 share {x1}/{len(hw)} - NOT X1-only.")
    print("top device_models:")
    print(hw["device_model"].value_counts().head(12).to_string())
    print("batt_vendor:")
    print(hw["batt_vendor"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
