# Prospective Intervention Protocol (v3) — closed-loop FCC recovery verification

> **Data availability: NOT AVAILABLE.** The current dataset contains NO BIOS/EC/battery-FW
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
See `fcc_intervention_power_simulation_v3.csv` (baseline response rate 0.39,
two-proportion test, alpha=0.05). E.g. n≈30/arm gives adequate power only for
large lifts; n≈80–120/arm recommended for a 0.15 lift.

## Safety
Calibration is OEM-approved and bounded by thermal/voltage limits. No forced
unsafe discharge. All device identifiers are hashed in any case table.
