# OD2 re-analysis — MASTER report (corrected fuel-gauge relearn definition)

_All-new `od2` pipeline; no OD1/v4 file modified. Cohort 752 users / 3,130,394 samples.
Response convention: END-anchored, effective step ≥50 mWh, **primary window 168h** (72/24
secondary). Tests: 15 OD2 unit tests pass; OD1 files verified byte-untouched._

## Motivation
The project owner corrected the definition of a fuel-gauge **learning opportunity**. It is
NOT the OD1 RSOC high→low→high discharge band (80/20/80). FCC re-learns under **two**
mechanisms, both completing at full charge:

- **Type A — deep-discharge relearn:** full (RSOC≥99) → RSOC ≤6% → full.
- **Type B — charge-side relearn:** while charging, RSOC transits 60–80% → full.

Everything downstream (opportunity extraction, offline triage, online detector, patent
5-pillar evidence) was re-run on this corrected definition and compared to OD1.

## Three structural changes the correction produces
1. **Opportunity coverage doubles.** Type B is very common (34,578 episodes vs OD1 primary
   11,342). OK-quality auditable users **294 → 687**; zero-opportunity (gauge candidate) = 46.
   (OD1 primary reproduced exactly at 11,342/598; Type A at 3,913/475 — methodology verified.)
2. **True relearn latency exceeds 72h → 168h primary window.** FCC-step attribution (share of
   real FCC updates explained by a preceding Type A/B END): 72h **69%** → 7d **86%** → 14d 91%.
   The inherited 72h window under-counts genuine responses.
3. **Triage shifts from "gauge reset" toward "FW check."** Because charge-side opportunities are
   ubiquitous, very few devices truly *lack* a relearn chance, so "opportunity present but no
   response → FW" grows and "no opportunity → gauge reset" shrinks.

## Mechanism strength (healthy per-opportunity response @168h)
- **Type A = 0.740** (strong deep-discharge relearn trigger) → FW k = 3.
- **Type B = 0.454** (frequent but weaker charge-side trigger) → FW k = 5 (re-justified from
  the (1−p)^k ≤ 0.05 false-alarm criterion; OD1 used k=3 calibrated for a strong trigger).

---

## Offline triage — OD1 vs OD2 (168h, re-justified k)
| label | baseline (OD1/72h) | OD2 (168h) |
|---|---|---|
| REVIEW | 338 | 338 (unchanged — opportunity-independent) |
| NORMAL | 327 | 327 (unchanged) |
| **FW check** | **14** | **35** |
| **GAUGE reset** | **18** | **10** |
| WATCH | 55 | 42 |

Movement: old-WATCH 55 → FW 19 / GAUGE 4 / WATCH 32; old-GAUGE 18 → FW 3 / GAUGE 5 / WATCH 10.

## Online 9-tier detector — OD1 vs OD2
| tier | OD1 | OD2 |
|---|---|---|
| REVIEW_DQ | 325 | 325 |
| NORMAL | 183 | **41** |
| WATCH_LGC | 128 | 70 |
| WATCH_LOW | 35 | **166** |
| FW_WATCH | 43 | **99** |
| FW_CORE | 5 | **49** |
| GAUGE_SOFT | 22 | 2 |
| GAUGE_REVIEW | 7 | 0 |
| GAUGE_CORE | 4 | **0** |

Stateful-vs-stateless detection gain **+29 → +73** (168h + long Type A episodes widen the
boundary benefit). Band-remap trap closed (0 Type B tagged INVALID). GAUGE_CORE→0 because
Type B supplies a charge-side opportunity in almost every window, so the "no learning
opportunity" gauge gates essentially never fire — nearly all signal moves to the FW side.

---

## Patent 5-pillar scoreboard — does the invention survive the corrected definition?
| Pillar | OD1 baseline | OD2 result | verdict |
|---|---|---|---|
| **A2** negative control (true resp vs own null, 168h) | 0.39 vs ~0.25 | **A 0.637 / B 0.368 / union 0.359**, each 4/4 outside null + 4/4 directional | ✅ both mechanisms real stimuli |
| **A3** anchor contamination (END) | END 0.0 (START 0.557) | **END 0.0 both mechanisms** (Type A START 0.689/LOW 0.455; Type B arm 0.03–0.07) | ✅ END clean; Type B dup-attribution 0.65 (caveat) |
| **B** response hazard (CIF true vs pseudo) | 0.39 vs 0.29 @72h | A 0.413→0.643, B 0.264→0.368; separation **grows** 72h→168h | ✅ corroborates; 168h justified |
| **E** missingness (naive→proposed false NR) | 643 → 4.1 | union **203.7 → 5.0** (~40×), recovery 0.96 | ✅ IC6 SUPPORTED |
| **D** retention (stateful recall/dup/storage) | 1.0 / 0 / 0.0417 @72h | **1.0 / 0 / 0.0417 @168h**, W=30d; stateless fails @7d (agreement 0.011) | ✅ IC5 MET; 30-day retention proven sound (7d<30d) |

## Headline conclusion
**The invention is preserved and BROADENED.** Under the corrected definition both the
deep-discharge (Type A) and the charge-side (Type B) mechanisms independently pass the
adversarial negative control — the charge-side response (0.265 @72h ≈ old null) rises to
0.368 @168h and clearly beats its own mechanism-specific null, so it is a genuine learning
stimulus, not background charging. The opportunity-conditioned non-response audit therefore
generalizes to a **dual-mechanism** claim (broader than OD1). All five evidence pillars hold.

## Caveats / open items
- **Type B duplicate-attribution (A3) = 0.65:** dense overlapping 168h windows share one FCC
  step across episodes. Union dedup removes only the *cross-mechanism* coincident-END double
  counting (~1.6 pp); within-mechanism overlap remains — the Type B END advantage rests on
  the duplicate metric less cleanly than Type A. First-step-only attribution is a mitigation.
- **Online k=5 in the cumulative setting:** the online FW_CORE=49 (median 43 no-responses)
  and NORMAL collapse 183→41 suggest cumulative Type B no-responses accrue even for healthy
  devices (healthy Type B response only 0.45). The offline tail-scoped FW=35 is more
  conservative; a cumulative-aware Type B threshold (or tail-scoping online) is a refinement.
- **Residual ~9% of FCC updates unexplained** even at 14d (median 260 mWh — real, not noise):
  a possible third relearn path or missed full-charge ENDs (conservation-mode caps ~80%;
  logger sleeping through the 100% point). 46 users never reach RSOC≥99.
- **Charge-termination anchor NOT AVAILABLE** (no per-sample current/taper telemetry); END
  (full-charge attainment) is its operational proxy — same honest stance as OD1.
- **E absolute scale** (~204 vs OD1 643) reflects the dense-user subset size, not a weaker
  effect; the ~40× naive→proposed reduction and 0.96 recovery are the invariant result.

## Artifacts (all under data/processed/fcc_relearn_od2/ and fcc_patent_evidence_od2/ and fcc_online_od2/)
- Phase 1: `phase1/od2_opportunities.parquet`, `od2_old_vs_new_*`, `od2_sensitivity_grid.csv`,
  `od2_fcc_step_attribution_summary.csv`; report `fcc_relearn_od2_comparison_report.md`.
- Phase 2: `offline/od2_final_action_labels.csv`, `od2_transition_rejk.csv`,
  `od2_k_justification.csv`; report `fcc_relearn_od2_offline_report.md`.
- Phase 4: `fcc_patent_evidence_od2/` (A2 `negative_control_summary_od2.csv` +
  `a2_od2_acceptance_by_mechanism.csv`; B `response_hazard_summary_od2.csv`; A3
  `response_anchor_comparison_od2.csv` + `_duplicate_od2.csv`; E
  `missingness_stress_summary_od2.csv`; D `retention_invariance_summary_od2.csv` +
  `retention_stateful_verification_od2.csv` + `storage_compute_tradeoff_od2.csv`); per-pillar
  reports `fcc_patent_evidence_od2_{a2,b,a3,e,d}_report.md`.
- Phase 3: `fcc_online_od2/online_latest_snapshot_od2.csv` (+28 artifacts); report
  `fcc_online_sliding30_od2_report.md`.
- Code: `battery_usage/relearn_od2*.py`, `patent_{negative_controls,response_hazard,anchor_analysis,missingness_stress,retention_invariance}_od2.py`,
  `online_od2_adapter.py`; drivers `analyze_fcc_relearn_od2_*.py`, `analyze_fcc_online_sliding30_od2.py`;
  tests `tests/test_relearn_od2*.py` (15 pass).
