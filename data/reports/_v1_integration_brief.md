All maps verified against source. The signatures, helper names, and constants are exactly as the maps describe. I now have what I need to write the brief.

---

# v2.0 Integration Brief — rolling-30day online FCC-response detector (battery-usage-ai)

All paths are absolute under `c:/Users/you/Desktop/wk/battery-usage-ai/`. Module imports below are from `battery_usage/`.

---

## 1. End-to-end v1 data flow (dataframes + key columns between stages)

The orchestrator is `analyze_fcc_online_sliding30.py::main`. The DAG order (do not reorder — causality depends on it) is:

```
df (raw timeseries)
 └─ prepare_user (per user) ──────────────────► df_by_user {uid: g}
      g cols: timestamp, remainingCapacityInPercentage, fullChargeCapacity,
              cycleCount, acdcMode, chargeStatus, soh_design_pct
 │
 ├─[1] rolling_window_features.build_rolling_features(df, cfg)
 │        ─► feats  (one row per user_id × window_end_date)
 │           keys: user_id, window_end_date, window_end_ts, window_start_ts,
 │                 window_data_quality_label, n_samples_30d, obs_days_in_window,
 │                 cycle_delta_30d, ac_time_ratio_30d, rsoc_swing_30d, rsoc_min_30d,
 │                 fcc_effective_changes_30d, last_effective_fcc_change_ts_in_window,
 │                 n_80_20_80_*_30d (after attach_window_episode_counts)
 │        ─► design_by_user {uid: design_mwh}
 │
 ├─[2] online_episode_detector.extract_episodes_causal(g, uid, cfg, design_mwh)
 │        ─► episodes  (episode_id, user_id, threshold_name, start_ts, low_ts, end_ts,
 │              start/low/end_idx, *_rsoc, episode_depth, *_duration_h, cycle_delta_episode,
 │              n_samples_episode, max_gap_h_episode, median_gap_h_episode, episode_quality,
 │              fcc_before_episode, cycle_count_before_episode,
 │              response_status_{24,72,168}h, window_{w}h_complete,
 │              response_window_end_ts_{w}h, first_post_end_step_ts, response_delay_h)
 │
 ├─[2b] attach_window_episode_counts(feats, episodes, cfg, "response_status_72h")
 │        ─► feats += n_{band}_{ok_complete,large_gap,no_response,censored,any}_30d
 │
 ├─[3] fcc_response_ml.enrich_episode_features(df_by_user, episodes, cfg, design_by_user)
 │        ─► eps_feat  (episodes + soh_before_episode + recent_30d_*_before_episode)
 │     fcc_response_ml.train_response_model(eps_feat, "response_status_72h")
 │        ─► (results{metrics,predictions,importances}, ResponseModelBundle)
 │     predict_all_ok(bundle, eps_feat) ─► ep_probs (episode_id, p_response)
 │
 ├─[4] usage_clustering.run_clustering(feats, quality_col="window_data_quality_label")
 │        ─► (assignments{user_id,window_end_date,cluster_id,cluster_profile_name,
 │                          cluster_action_hint}, profiles, info)
 │
 ├─[5] online_anomaly_scores.compute_window_scores(feats, episodes, ep_probs, cfg, final_labels)
 │        ─► feats += expected_response_30d, observed_response_30d, no_response_count_30d,
 │              n_complete_ok_opportunities_30d, p_all_no_response_30d,
 │              fw_response_anomaly_score_30d, conformal_p, conformal_p_proxy_final_normal
 │
 ├─[6] online_state.build_online_state(df_by_user, episodes(+p_response), feats, cfg, design_by_user)
 │        ─► (state_daily, change_audit)
 │     state_daily keys: user_id, window_end_date, days_since_last_effective_fcc_change,
 │              cycles_since_last_effective_fcc_change,
 │              cum_{primary,strict}_{no_response,censored,ok,large_gap,response}_since_last_fcc_change,
 │              cum_expected_response_*, cum_observed_response_*,
 │              cum_log_p_all_no_response_*, cum_fw_response_anomaly_score
 │     change_audit keys: user_id, change_ts, fcc_value, cycle, prev_fcc_value
 │
 ├─[7] join state_daily + feats + cluster assignments ─► daily
 │     online_action_policy.assign_labels(daily, cfg)
 │        ─► daily += window_label, stateful_label, recommended_action
 │     apply_alert_cooldown(daily, 30) ─► daily += alert_fired,
 │                                          consecutive_windows_opportunity_no_response
 │     latest_snapshot(daily) ─► snap (+ primary_evidence)
 │     candidate_lists(snap) ─► {fw_check, gauge_reset, watchlist, review_queue}
 │
 ├─[8] sensitivity (effective_step / gap / response_window), backtest_summary, 
 │     online_enrichment.enrich_all(snap, user_meta, candidate_labels)
 │
 └─[9] _write_outputs(...) + _write_report(...) + plot_fcc_online_sliding30.py
```

The single most important invariant: **episodes resolve at `end_ts + W`**, `feats` carry causal per-window counts, `state_daily` replays events with the `seen_ids` dedup guard, and `daily` only labels after state is built. Anomaly scoring (step 5) must come **after** episode resolution but **before** state replay consumes `p_response`.

---

## 2. The 8 new v2 modules — what each builds on and must produce

### 2.1 `online_step_state.py` — dual-track FCC state (`any_change` vs `effective`)
- **Builds on:** `online_episode_detector.fcc_step_indicator(fcc, min_mwh)`, `step_threshold_mwh(step_def, design_mwh)`, `recover_design_mwh(g)`, and `online_state._effective_change_events(g, min_mwh)`.
- **Approach:** run `_effective_change_events` twice per user — once with `min_mwh = step_threshold_mwh("any_change", …)` (= 1.0) and once with `min_mwh = step_threshold_mwh(cfg.effective_step, design_mwh)` (= 50 mWh default). Track two parallel `last_change_ts / days_since / cycles_since` trajectories.
- **Produces (new columns on `state_daily`):** `days_since_last_any_fcc_change`, `cycles_since_last_any_fcc_change`, `last_any_fcc_change_ts`, `last_any_fcc_change_value`, alongside the existing `*_effective_*`. Dual-basis is needed by the active-false-alert audit (§2.5/2.7) and the policy matrix (§2.4).
- **Reuse the v1 `_BandState.reset()` semantics** but key resets off the **effective** track only for the anomaly accumulator (mixing any-change into the Poisson-binomial double-counts, see §4).

### 2.2 `online_gap_quality.py` — graded gap-quality tiers
- **Builds on:** `online_episode_detector._episode_quality(...)` (returns quality + `(max_gap, median_gap)`), `OnlineConfig.gap_small_h=6.0 / gap_mid_h=12.0 / gap_large_h=24.0`, and the window `max_gap_h` / `p95_interval_h` already in `feats`.
- **Produces:** a graded tier replacing the binary `ok`/`large_gap`. Map `max_gap_h_episode` → `HIGH_OK` (≤ gap_small_h), `MEDIUM_GAP` (gap_small_h < g ≤ gap_large_h), `LOW_LARGE_GAP` (> gap_large_h). New episode column `gap_quality_tier`; new window columns `n_{band}_{HIGH_OK,MEDIUM_GAP,LOW_LARGE_GAP}_30d`.
- **Critical:** the existing binary `episode_quality` must remain for backward compatibility and for the existing tests; v2 adds `gap_quality_tier` as a parallel field. `attach_window_episode_counts` should gain a tiered variant rather than replacing the v1 counts.

### 2.3 `fcc_response_normative.py` — normative vs personalized response models
- **Builds on:** `fcc_response_ml.train_response_model`, `predict_all_ok`, `ResponseModelBundle`, `enrich_episode_features`, `_assert_no_leakage`, `EPISODE_TIME_FEATURES`, `GroupKFold` strategy.
- **Two model heads:**
  - **Personalized** = current v1 feature set (all of `EPISODE_TIME_FEATURES`, including the recent-history features).
  - **Normative** = `EPISODE_TIME_FEATURES` **MINUS all recent-FCC-history / recent-outcome features** (exact exclusion list in §5).
- **Produces:** two bundles + two `p_response` columns: `p_response_personalized`, `p_response_normative`. Add a normative-specific `FORBIDDEN_SUBSTRINGS` extension and a new `_assert_normative_excludes_history()` gate. Re-emit `metrics`/`predictions`/`importances` per head.

### 2.4 `online_policy_v2.py` — Gauge split, FW tiers, 9-level priority matrix
- **Builds on:** `online_action_policy._window_label`, `_stateful_label`, `assign_labels`, `apply_alert_cooldown`, `latest_snapshot`, `candidate_lists`, `assert_no_hw_in_classification`, the `_GAUGE_CLUSTERS` set, and all `OnlineConfig` gate thresholds (`fw_days_since_change_min`, `gauge_days_since_change_min`, `fw_cycles_since_change_min`).
- **Produces:**
  - **Gauge split:** replace single `ST_GAUGE` with `GAUGE_CORE` / `GAUGE_SOFT_CALIBRATION` / `GAUGE_REVIEW` (split the existing gauge gate on cluster confidence + data-quality proximity).
  - **FW tiers:** `FW_CORE` / `FW_WATCH_HIGH_ANOMALY` / `FW_REVIEW` plus engineering-queue ranks `fw_top50` / `fw_top100` (rank by `cum_fw_response_anomaly_score` then `cum_primary_no_response`, same sort key `candidate_lists` already uses for `fw_check`).
  - **9-level priority matrix:** a deterministic lookup keyed on (FW tier × Gauge tier × data-quality). Emit `priority_level` (1–9) and `priority_reason`. Keep the **data-quality-dominance rule first** (§4) — DQ-review always wins.
- **Preserve dual-label separation** (window vs stateful) and the `cum_obs == 0` hard disqualifier.

### 2.5 `online_evaluation_v2.py` — backtest v2
- **Builds on:** `analyze_fcc_online_sliding30.py::backtest_summary`, `topn_yield`, `stateless_latest`, `response_window_sensitivity`, `effective_step_sensitivity`, `gap_sensitivity`, and `extract_episodes_in_window` (the stateless baseline).
- **Produces:** stateful-vs-stateless cross-tab; final-proxy cross-tab (`stateful_label` × proxy `final_label`); lead-time per proxy (`lead_time_days`); a **sensitivity grid** (cartesian over effective_step × gap × response_window rather than the v1 one-axis-at-a-time tables); **dual-basis active-false-alert audit** (false-alert rate computed against BOTH `days_since_last_effective_fcc_change` and `days_since_last_any_fcc_change` from §2.1).
- **Critical:** stateless comparison must still use `extract_episodes_in_window` (marks `detector='stateless'`) and the apples-to-apples gate (≥2 OK no_response + 0 observed response + OK window quality).

### 2.6 `online_reporting_v2.py` — report writer
- **Builds on:** `analyze_fcc_online_sliding30.py::_write_report` (20-section markdown), `_write_outputs`, `_print_final`, and `stamp(df, cfg, ts)`.
- **Produces:** new sections for dual-track state, gauge/FW tier breakdowns, the 9-level matrix counts, normative-vs-personalized model comparison, multi-population enrichment, and the dual-basis false-alert audit. Must still `stamp()` every output frame (`analysis_timestamp, code_version, window_days, stride_days, effective_step_definition`); bump `CODE_VERSION` to `rolling30-v2.0`.

### 2.7 `online_enrichment` extension (multi-population) — lives in new module or extends `online_enrichment.py`
- **Builds on:** `online_enrichment.enrich_axis`, `enrich_all`, `_beta_prior`, `_bh`, `DEFAULT_GROUP_AXES`, `assert_no_hw_in_classification`.
- **Produces:** enrichment across multiple **candidate populations** (FW_CORE, FW_WATCH, GAUGE_CORE, GAUGE_SOFT, etc.) rather than the single FW-candidate set — call `enrich_all` once per population label set, concatenate with a `population` column. Keep beta-binomial shrinkage + Fisher + BH FDR and the post-classification-only rule.

### 2.8 `online_plotting_v2.py`
- **Builds on:** `plot_fcc_online_sliding30.py` `Plotter` class (`load`, `fig`, `_save`, `_annot_n`, `_safe_id`), `FigCounter`, `META_COLS`, `STATEFUL_ORDER`, `STATEFUL_COLORS`, `THRESHOLD_COLORS`, all 32 `fig_*` functions, `plot_example_users`.
- **Produces:** new figures for dual-track days-since, gauge/FW tier funnels, 9-level priority distribution, normative-vs-personalized ROC/calibration overlay, tiered gap-quality stacked bars, dual-basis false-alert time-series, multi-population enrichment. Reuse the `try/except`-per-figure robustness and `(P, out)` signature contract. Update `STATEFUL_ORDER`/`STATEFUL_COLORS` for the new tier labels.

### CLIs
- **`analyze_fcc_online_sliding30_v2.py`** — clone `main`'s DAG, insert step-state (§2.1) and gap-quality (§2.2) before episodes feed ML; run both ML heads (§2.3); call `online_policy_v2` (§2.4); call `online_evaluation_v2` (§2.5) and multi-population enrichment (§2.7); write via `online_reporting_v2` (§2.6).
- **`plot_fcc_online_sliding30_v2.py`** — thin wrapper instantiating `Plotter` against v2 output dir, calling v1 figs + new figs.

---

## 3. Exact reuse points (function names + signatures)

| Concern | Function (module) | Signature |
|---|---|---|
| Episode extraction (stateful) | `extract_episodes_causal` (online_episode_detector) | `(g, uid, cfg=DEFAULT_ONLINE_CONFIG, design_mwh=None, inference_last_ts=None) -> List[Dict]` |
| Episode extraction (stateless baseline) | `extract_episodes_in_window` (online_episode_detector) | `(g_window, uid, window_end, cfg, design_mwh=None, last_observed_ts=None) -> List[Dict]` |
| Raw state machine | `extract_high_low_high_episodes` (online_episode_detector) | `(rsoc, high, low) -> List[Tuple[int,int,int]]` |
| Effective-step threshold | `step_threshold_mwh` (online_episode_detector) | `(step_def, design_mwh) -> float` |
| Design recovery | `recover_design_mwh` (online_episode_detector) | `(g) -> float` |
| Per-sample step flags | `fcc_step_indicator` (online_episode_detector) | `(fcc, min_mwh) -> Tuple[ndarray,ndarray]` (is_step, is_unknown) |
| Response status label | `_response_status` (online_episode_detector, line 137) | `(complete: bool, changed: Optional[bool]) -> str` |
| END-anchored response (USE THIS for online) | `episode_response` (online_episode_detector, line 174) / internal `_changed_after_end` (line 152) | `episode_response(ts_ns, fcc, is_step, end_idx, last_ts_ns, windows_h=RESPONSE_WINDOWS_H) -> Dict` |
| Episode quality + gaps | `_episode_quality` (online_episode_detector, line 207) | `(ts_ns, fcc, rsoc, s, lo, e, max_gap_hours) -> (quality, max_gap, med_gap)` |
| Stable episode id | `_episode_id` (online_episode_detector, line 231) | `(uid, threshold, start_ns, end_ns) -> str` |
| Window features | `build_rolling_features` (rolling_window_features) | `(df, cfg, design_by_user=None, progress=False) -> (feats, design_by_user)` |
| Window-end grid | `window_end_grid` (rolling_window_features) | `(first_ts, last_ts, stride_days) -> DatetimeIndex` |
| Causal episode counts | `attach_window_episode_counts` (rolling_window_features) | `(feats, episodes, cfg, response_col="response_status_72h") -> feats` |
| State replay | `build_online_state` (online_state) | `(df_by_user, episodes, feats, cfg, design_by_user=None, default_p=0.5, progress=False) -> (state_daily, change_audit)` |
| Per-user state replay | `build_user_state_daily` (online_state) | `(g, uid, grid_ends, episodes, cfg, design_mwh=None, default_p=0.5) -> (state_rows, audit_rows)` |
| FCC event extraction | `_effective_change_events` (online_state) | `(g, min_mwh) -> List[Tuple[int,float,float]]` |
| Band counters | `_BandState` (online_state) | class with `.reset()` |
| ML feature enrichment | `enrich_episode_features` (fcc_response_ml) | `(df_by_user, episodes, cfg, design_by_user=None) -> eps_feat` |
| ML training | `train_response_model` (fcc_response_ml) | `(eps_feat, response_col="response_status_72h") -> (results, ResponseModelBundle)` |
| ML scoring | `predict_all_ok` (fcc_response_ml) | `(bundle, eps_feat) -> DataFrame[episode_id, p_response]` |
| Leakage gate | `_assert_no_leakage` (fcc_response_ml) | `(columns) -> None` |
| Clustering | `run_clustering` (usage_clustering) | `(feats, max_fit=40000, random_state=0, quality_col="window_data_quality_label") -> (assignments, profiles, info)` |
| Anomaly scoring | `compute_window_scores` (online_anomaly_scores) | `(feats, episodes, ep_probs, cfg, final_labels=None) -> feats` |
| Empirical conformal p | `_empirical_p` (online_anomaly_scores) | `(scores, calib) -> ndarray` |
| Window label | `_window_label` (online_action_policy) | `(r) -> str` |
| Stateful label | `_stateful_label` (online_action_policy) | `(r, cfg, fleet_cycle_p25) -> str` |
| Policy assignment | `assign_labels` (online_action_policy) | `(daily, cfg) -> daily` |
| Alert cooldown | `apply_alert_cooldown` (online_action_policy) | `(daily, cooldown_days=30) -> daily` |
| Snapshot + candidates | `latest_snapshot` / `candidate_lists` (online_action_policy) | `(daily)->snap` / `(snap)->Dict[str,DataFrame]` |
| HW guard | `assert_no_hw_in_classification` (online_action_policy / online_enrichment) | `(*feature_lists) -> None` |
| Enrichment | `enrich_axis` / `enrich_all` (online_enrichment) | `(snap, user_meta, axis, candidate_labels, min_group_n=5)` / `(snap, user_meta, candidate_labels, group_axes=DEFAULT_GROUP_AXES, min_group_n=5)` |
| Beta prior / FDR | `_beta_prior` / `_bh` (online_enrichment) | `(k,n)->(a,b)` / `(pvals)->qvals` |
| Plotting harness | `Plotter`, `FigCounter` (plot_fcc_online_sliding30) | `Plotter(in_dir, fig_dir, dpi, counter)`; `.load(fname, drop_meta=True)`; `.fig(name, func)` |
| Metadata stamp | `stamp` (analyze_fcc_online_sliding30) | `(df, cfg, ts) -> df` |

---

## 4. Causality / leakage guards v2 MUST preserve (and the two regression bugs)

1. **END-anchored response window** (online): response measured in `[end_ts, end_ts+W]`, NOT `[start_ts, …]`. v2 online code must call `episode_response`/`_changed_after_end`, never the audit's START-anchored `episode_fcc_response`/`_changed_in_window`.
2. **Censored ≠ no_response:** non-change is `no_response` only when the window is fully observed (`complete=True`); otherwise `censored`. `censored`/`unknown` are NEVER counted as zero response, in episodes, in window counts, or in the Poisson-binomial accumulator.
3. **Missing-FCC baseline → `unknown`, never `no_response`** (`fcc_step_indicator` `is_unknown` track).
4. **Double-count guard (spec 7.5):** `_episode_id` stable across detectors; `build_user_state_daily` dedups via `seen_ids`. v2 step-state and policy must keep this.
5. **Zero-opportunity guard:** `fw_response_anomaly_score_30d = 0.0` (NOT NaN) and `conformal_p = NaN` when `n_complete_ok_opportunities_30d == 0` (`compute_window_scores`). Empty product = 1.0 → log10 = 0.
6. **Causal window membership for counts:** episode ending at `e` is censored in windows `e ≤ t < e+W`, resolved only at `t ≥ e+W` (`attach_window_episode_counts`). This is **regression bug #17's fix — do not undo.**
7. **State temporal ordering:** event replay sorts by (ts, priority): `_PRIO_COMPLETE=0 < _PRIO_RESET=1 < _PRIO_DEADLINE=2`. Censored episodes must NOT flip to no_response when the grid walks past `end+W` in wall-clock time without an observation. This is **regression bug #16's fix — do not undo.** The deadline is only scheduled if `(end_ns + win_ns) <= last_ns`.
8. **ML leakage:** `_assert_no_leakage` scans `FORBIDDEN_SUBSTRINGS` (`response_status, fcc_changed, fcc_response, final_label, subreason, recommended_action, device_model, batt_vendor, batt_fru, manufacturer, serial, uuid, mtm, product_uuid, flat_tail, p_response`). `GroupKFold` by `user_id` so 29-day-overlapping windows never straddle the split. `recent_30d_*` computed strictly in `[start-30d, start)`.
9. **No hardware in classification:** `assert_no_hw_in_classification` on every model/cluster/policy feature list; enrichment runs **only post-classification**.
10. **Data-quality dominance (spec 16.14):** if `window_data_quality_label != WINDOW_QUALITY_OK`, `_window_label → WIN_DQ` and `_stateful_label → ST_REVIEW` **first**, before any actionable gate. In v2's 9-level matrix this must remain the top branch.
11. **`cum_obs == 0` hard disqualifier** for FW and WATCH; **large_gap_or_censored dominance** blocks FW (not GAUGE).
12. **Anomaly accumulator uses PRIMARY band only** (strict is nested; mixing double-counts).

The two known regression bugs live in: **test 16** (`tests/test_fcc_online_sliding30.py` lines ~316-326) guarding `online_state.build_user_state_daily` censored-not-no_response across grid walk; **test 17** (lines ~331-343) guarding `rolling_window_features.attach_window_episode_counts` causal split (`e ≤ window_end_ts < e+72h` = censored). Keep both tests passing unchanged.

---

## 5. Feature lists + what the NORMATIVE model must EXCLUDE

**v1 full feature set (`EPISODE_TIME_FEATURES`, fcc_response_ml.py):**
```
episode_depth, episode_duration_h, start_to_low_duration_h, low_to_end_duration_h,
cycle_delta_episode, start_rsoc, low_rsoc, end_rsoc, n_samples_episode,
max_gap_h_episode, median_gap_h_episode, fcc_before_episode, soh_before_episode,
cycle_count_before_episode,
recent_30d_cycle_delta_before_episode, recent_30d_ac_ratio_before_episode,
recent_30d_rsoc_swing_before_episode, recent_30d_n_80_20_80_ok_before_episode,
recent_30d_fcc_effective_changes_before_episode, recent_30d_n_samples_before_episode,
recent_30d_max_gap_h_before_episode
+ band_* (one-hot from threshold_name)
```

**Normative model = full list MINUS recent FCC-history / recent-outcome features. Exclude exactly:**
- `recent_30d_fcc_effective_changes_before_episode` — **the v1 top feature**; it is recent FCC-update activity (the very thing the model is meant to be agnostic to). This is the single most important exclusion.
- `recent_30d_n_80_20_80_ok_before_episode` — recent learning-opportunity outcome history.
- `fcc_before_episode` — prior FCC level (carries the device's recent gauge trajectory). **Resolve with stakeholders** whether normative keeps an absolute capacity proxy via `soh_before_episode` only.

**Normative model KEEPS:** episode geometry (`episode_depth`, `*_duration_h`, `*_rsoc`, `cycle_delta_episode`), sampling-density features (`n_samples_episode`, `max/median_gap_h_episode`, `recent_30d_n_samples_before_episode`, `recent_30d_max_gap_h_before_episode`), usage context (`recent_30d_cycle_delta_before_episode`, `recent_30d_ac_ratio_before_episode`, `recent_30d_rsoc_swing_before_episode`), `soh_before_episode`, `cycle_count_before_episode`, `band_*`.

Add `_assert_normative_excludes_history()` that rejects any column matching `('recent_30d_fcc', 'recent_30d_n_80_20_80', 'fcc_changed', 'fcc_response')`. **Personalized** keeps the full v1 list.

**Other v1 feature contracts to keep stable:** `CLUSTER_FEATURES` (17 cols, usage_clustering), the rolling-window output column contract (rolling_window_features), `HW_TOKENS` (8), `FORBIDDEN_SUBSTRINGS`.

---

## 6. Recommended implementation order (with dependencies)

1. **`online_step_state.py`** (§2.1) — no upstream v2 deps; only needs v1 `online_state`/`online_episode_detector`. Produces dual-track columns consumed by policy, evaluation, plotting.
2. **`online_gap_quality.py`** (§2.2) — depends only on `online_episode_detector._episode_quality` + config. Produces tier columns consumed by ML enrichment, policy, plotting.
3. **`fcc_response_normative.py`** (§2.3) — depends on the feature list decisions in §5; consumes episodes/eps_feat. Produces `p_response_normative` + `p_response_personalized`. (Anomaly scoring can then choose which `p_response` to feed.)
4. **`online_policy_v2.py`** (§2.4) — depends on §2.1 (dual-track), §2.2 (gap tiers), `state_daily`, `feats`, cluster assignments. Produces tiers + 9-level matrix consumed by evaluation, enrichment, reporting, plotting.
5. **`online_evaluation_v2.py`** (§2.5) — depends on §2.1 (dual-basis), §2.4 (tiers/proxies), stateless baseline. Produces backtest tables.
6. **multi-population enrichment** (§2.7) — depends on §2.4 candidate populations.
7. **`online_reporting_v2.py`** (§2.6) — depends on all upstream outputs.
8. **`online_plotting_v2.py`** (§2.8) — depends on the written v2 output files.
9. **`analyze_fcc_online_sliding30_v2.py`** — wires 1–7 in the v1 DAG order; **`plot_fcc_online_sliding30_v2.py`** wires 8.
10. **Tests:** extend `tests/test_fcc_online_sliding30.py` — keep tests 1–17 unchanged; add v2 tests for dual-track reset semantics, tiered gap counts, normative-excludes-history assertion, 9-level matrix DQ-dominance, dual-basis false-alert.

---

## 7. Open risks / ambiguities to resolve while implementing

1. **Which `p_response` feeds anomaly scoring (§5/§2.3↔§2.5)?** `compute_window_scores` takes one `ep_probs`. Decide whether the Poisson-binomial anomaly uses normative or personalized probabilities — this changes the meaning of `fw_response_anomaly_score_30d` and every downstream gate. Recommendation: normative (device-agnostic baseline), but confirm.
2. **Dual-track reset interaction in state replay.** `_BandState.reset()` and the anomaly accumulator currently reset on **effective** FCC change. If any-change resets are added as events, ensure they do NOT reset the Poisson-binomial accumulator (would double-count). Define precisely which counters each track resets.
3. **`fcc_before_episode` in the normative model** — keep or drop? It encodes the device's recent capacity trajectory. Ambiguous against "excludes recent FCC history."
4. **9-level priority matrix definition** is underspecified. The maps give FW tiers (3) × Gauge tiers (3) = 9 cells, but the exact ranking and tie-breaks (and where WATCH/REVIEW/NORMAL land) need an explicit lookup table. Confirm the matrix axes are (FW tier × Gauge tier) and not (severity × confidence).
5. **`top50/top100` engineering queue scope** — global cohort ranking vs per-population. And the rank key: `cum_fw_response_anomaly_score` then `cum_primary_no_response` then `days_since` (the v1 `candidate_lists` sort) — confirm.
6. **Gauge split criteria.** CORE/SOFT_CALIBRATION/REVIEW thresholds are not in v1. Likely: CORE = strong cluster + long staleness; SOFT = weaker cluster or borderline staleness; REVIEW = DQ-adjacent. Needs explicit thresholds added to `OnlineConfig` (do NOT hardcode — follow the v1 pattern).
7. **Gap-tier boundaries** — `MEDIUM_GAP` upper bound: is it `gap_large_h` (24h) or `gap_mid_h` (12h, the current `episode_max_gap_hours` cutoff)? The existing binary cut is at 12h, so MEDIUM may need to straddle 6–12 vs 12–24. Resolve against the `large_gap` definition to avoid double-counting.
8. **Multi-population enrichment label sets** — exactly which `stateful_label`/tier values define each population, and whether populations overlap (a user can be FW_WATCH and gauge-eligible). Overlap breaks the binary `n_candidate` count in `enrich_axis`.
9. **Dual-basis false-alert audit denominator** — false-alert rate against any-change basis will be much higher (~58% of steps are <50 mWh micro-wobbles per v1 notes). Confirm the audit reports both bases side-by-side and labels which is the "operational" one.
10. **Sensitivity grid cost** — full cartesian (5 effective_step × 3 gap × 3 response_window = 45 runs) re-extracts episodes each time. Reuse `design_by_user` and the O(1) prefix-sum window machinery; consider caching episode extraction keyed on `effective_step` only.
11. **Backward compatibility of column contracts** — v2 must ADD columns, not rename v1 ones, or the 32 v1 figures and tests 1–17 break. Keep `episode_quality` (binary) alongside `gap_quality_tier`, and keep single-`p_response` outputs available for v1 plotters.

**Key v1 files to read first when implementing:** `battery_usage/online_episode_detector.py` (lines 64–346: step/response/quality/id helpers), `battery_usage/online_state.py` (event replay + `_BandState`), `battery_usage/online_action_policy.py` (gate logic), `battery_usage/fcc_response_ml.py` (`EPISODE_TIME_FEATURES`, `_assert_no_leakage`), `analyze_fcc_online_sliding30.py` (DAG order, lines ~310-438), `tests/test_fcc_online_sliding30.py` (tests 16 & 17 regression guards).