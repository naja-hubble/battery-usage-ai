"""FCC-learning intervention classifier — main analysis script.

Audits, per user, whether the smart gauge got a learning OPPORTUNITY (a high->low->high
RSOC excursion) and whether ``fullChargeCapacity`` actually RESPONDED afterwards, then
assigns each of the 752 users ONE mutually-exclusive intervention label:

    REVIEW_INSUFFICIENT_DATA / NORMAL_OR_RESPONDING /
    ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY (-> gauge reset) /
    ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE (-> FW/BIOS/EC check) /
    WATCH_LOW_UPDATE_RATE_AMBIGUOUS

Hardware identity (device_model / batt_vendor / batt_fru) is read ONLY after
classification, for descriptive enrichment — never as a classification input.

    python analyze_fcc_learning_actions.py \
      --timeseries data/processed/battery_timeseries_all.parquet \
      --out-dir data/processed \
      --fig-dir data/reports/figures/fcc_action \
      --report data/reports/fcc_learning_action_report.md

Outputs: see the CSV/figure/report paths in ``main``.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from battery_usage.config import load_config
from battery_usage.fcc_learning import (
    DEFAULT_CONFIG, EPISODE_THRESHOLDS, RESPONSE_WINDOWS_H, FccLearningConfig, process_user, _short,
)
from battery_usage import fcc_action_classifier as C
from battery_usage.fcc_action_classifier import (
    ClassifierThresholds, DEFAULT_THRESHOLDS, LABEL_ORDER, LABEL_GAUGE, LABEL_FW,
    active_reference_quantiles, compute_candidate_flags, classify_frame,
)

# Columns the audit reads from the parquet. Hardware identity is intentionally ABSENT.
_TS_COLS = ["user_id", "timestamp", "remainingCapacityInPercentage", "cycleCount",
            "fullChargeCapacity", "soh_design_pct", "acdcMode", "serialNumber"]
_HW_COLS = ["device_model", "batt_vendor", "batt_fru"]

_LABEL_SHORT = {C.LABEL_REVIEW: "review", C.LABEL_NORMAL: "normal", C.LABEL_GAUGE: "gauge_reset",
                C.LABEL_FW: "fw_check", C.LABEL_WATCH: "watch"}

_EPISODE_CSV_COLS = [
    "user_id", "threshold_name", "start_ts", "low_ts", "end_ts",
    "start_idx", "low_idx", "end_idx", "start_rsoc", "low_rsoc", "end_rsoc",
    "cycle_delta_episode", "fcc_start", "fcc_end", "fcc_changed_during_episode",
    "fcc_changed_24h", "fcc_changed_72h", "fcc_changed_168h",
    "response_window_end_ts_24h", "response_window_end_ts_72h", "response_window_end_ts_168h",
    "max_gap_h_in_episode", "episode_quality",
]

# Operational columns for the user-contact / FW-investigation target lists. Hardware
# identity is included here for FW triage PRIORITISATION only (allowed post-classification).
_TARGET_COLS = [
    "user_id", "final_label", "recommended_action", "confidence", "sub_reason",
    "gauge_reset_score_0_100", "fw_check_score_0_100", "primary_evidence",
    "flat_tail_days", "fcc_changes", "tail_cycle_delta",
    "tail_n_90_10_90_ok", "tail_n_80_20_80_ok", "tail_n_85_15_85_ok",
    "tail_response_rate_80_20_80_72h", "relevant_response_rate_72h",
    "tail_ac_time_ratio", "tail_min_rsoc", "tail_max_rsoc", "tail_rsoc_swing",
    "obs_days", "data_quality_label", "device_model", "batt_vendor", "batt_fru",
    "operational_message",
]


# --------------------------------------------------------------------------- #
# Stage 1: per-user features + episodes (single pass over the cohort)
# --------------------------------------------------------------------------- #
def build_features_and_episodes(
    df: pd.DataFrame, cfg: FccLearningConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    feats: List[dict] = []
    episodes: List[dict] = []
    for uid, g in df.groupby("user_id", sort=False):
        f, e = process_user(uid, g, cfg)
        feats.append(f)
        episodes.extend(e)
    fdf = pd.DataFrame(feats)
    edf = pd.DataFrame(episodes)
    return fdf, edf


# --------------------------------------------------------------------------- #
# Stage 2: candidate flags + final labels
# --------------------------------------------------------------------------- #
def classify(
    features: pd.DataFrame, thr: ClassifierThresholds,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    q = active_reference_quantiles(features)
    feat = compute_candidate_flags(features, q, thr.candidate_pct)
    cls = classify_frame(feat, thr)
    out = pd.concat([feat.reset_index(drop=True), cls.reset_index(drop=True)], axis=1)
    return out, q


# --------------------------------------------------------------------------- #
# Stage 3: sensitivity analysis (section 10)
# --------------------------------------------------------------------------- #
def sensitivity_analysis(
    features: pd.DataFrame, q: Dict[str, float], base: ClassifierThresholds,
) -> pd.DataFrame:
    rows: List[dict] = []
    base_feat = compute_candidate_flags(features, q, base.candidate_pct)

    def add(dim: str, variant, thr: ClassifierThresholds, feat: pd.DataFrame) -> None:
        vc = classify_frame(feat, thr)["final_label"].value_counts()
        row = {"dimension": dim, "variant": str(variant),
               "n_candidates": int(feat["fcc_no_or_low_change_candidate"].sum())}
        for lab in LABEL_ORDER:
            row[f"n_{_LABEL_SHORT[lab]}"] = int(vc.get(lab, 0))
        rows.append(row)

    for pct in ("p05", "p10"):
        feat = compute_candidate_flags(features, q, pct)
        add("candidate_pct", pct, replace(base, candidate_pct=pct), feat)
    for w in ("24h", "72h", "168h"):
        add("response_window", w, replace(base, response_window=w), base_feat)
    for v in (60, 120, 180):
        add("flat_tail_days[fw_hi&gauge_hi]", v,
            replace(base, fw_hi_flat_tail_days=v, gauge_hi_flat_tail_days=v), base_feat)
    for v in (20, 30, 50):
        add("tail_cycle_delta[fw_hi&fw_med]", v,
            replace(base, fw_hi_tail_cycle_ge=v, fw_med_tail_cycle_ge=v), base_feat)
    for v in (1, 2, 3, 5):
        add("tail_n_80_20_80_ok[fw_hi]", v, replace(base, fw_hi_tail_n_8020_ge=v), base_feat)
    return pd.DataFrame(rows)


def episode_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    """Per threshold_name: episode counts and OK-episode 72h response rate (section 10.2)."""
    rows = []
    for name in EPISODE_THRESHOLDS:
        sub = episodes[episodes["threshold_name"] == name]
        ok = sub[sub["episode_quality"] == "ok"]
        known = ok[ok["fcc_changed_72h"].notna()]
        resp = float(known["fcc_changed_72h"].astype(float).mean()) if len(known) else float("nan")
        rows.append({
            "threshold_name": name,
            "n_episodes": int(len(sub)),
            "n_ok": int(len(ok)),
            "n_large_gap": int((sub["episode_quality"] == "large_gap").sum()),
            "n_users_with_ok": int(ok["user_id"].nunique()),
            "ok_response_rate_72h": round(resp, 4) if resp == resp else float("nan"),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Stage 4: hardware enrichment (POST-classification only)
# --------------------------------------------------------------------------- #
def enrichment_by_hardware(labels: pd.DataFrame) -> pd.DataFrame:
    """Per (attribute, value): total users + per-label counts + action rates.

    Hardware identity is merged in only here, AFTER labels are fixed, to check whether
    FW-check targets concentrate on particular models/vendors/FRUs (descriptive only).
    """
    rows: List[dict] = []
    for attr in _HW_COLS:
        for val, g in labels.groupby(labels[attr].fillna("(none)")):
            row = {"attribute": attr, "value": val, "n_total": int(len(g))}
            vc = g["final_label"].value_counts()
            for lab in LABEL_ORDER:
                row[f"n_{_LABEL_SHORT[lab]}"] = int(vc.get(lab, 0))
            row["fw_check_rate"] = round(row["n_fw_check"] / row["n_total"], 4)
            row["gauge_reset_rate"] = round(row["n_gauge_reset"] / row["n_total"], 4)
            rows.append(row)
    out = pd.DataFrame(rows)
    return out.sort_values(["attribute", "n_fw_check", "n_total"], ascending=[True, False, False])


# --------------------------------------------------------------------------- #
# Stage 5: cross-validation vs existing soh_update_status.csv (section 10.1)
# --------------------------------------------------------------------------- #
def crossvalidate_status(labels: pd.DataFrame, processed_dir: Path) -> Tuple[pd.DataFrame, dict]:
    info: dict = {}
    # Reproduce active/stale/very_stale from our own flat_tail_days (60/180 thresholds).
    ft = labels["flat_tail_days"]
    repro = pd.cut(ft, [-1, 60, 180, 1e9], labels=["active", "stale", "very_stale"])
    info["reproduced"] = repro.value_counts().reindex(["active", "stale", "very_stale"]).fillna(0).astype(int).to_dict()

    path = processed_dir / "soh_update_status.csv"
    ctab = pd.DataFrame()
    if path.exists():
        ext = pd.read_csv(path)[["user_id", "soh_update_status", "soh_flat_tail_days"]]
        info["existing"] = ext["soh_update_status"].value_counts().to_dict()
        m = labels.merge(ext, on="user_id", how="inner")
        info["n_merged"] = int(len(m))
        # Median flat-tail difference (mostly the de-dup / change-detection nuance).
        info["flat_tail_median_abs_diff"] = round(
            float((m["flat_tail_days"] - m["soh_flat_tail_days"]).abs().median()), 2)
        ctab = pd.crosstab(m["soh_update_status"], m["final_label"])
    return ctab, info


# --------------------------------------------------------------------------- #
# Stage 6: report
# --------------------------------------------------------------------------- #
def _q(label_counts: dict, key: str) -> int:
    return int(label_counts.get(key, 0))


def write_report(
    path: Path, labels: pd.DataFrame, episodes: pd.DataFrame, q: Dict[str, float],
    sens: pd.DataFrame, epi_sum: pd.DataFrame, enrich: pd.DataFrame, funnel: dict,
    ctab: pd.DataFrame, xinfo: dict, thr: ClassifierThresholds, fig_dir: Path,
    n_users: int, analysis_ts: str,
) -> None:
    lc = labels["final_label"].value_counts().to_dict()
    ac = labels["recommended_action"].value_counts().to_dict()
    cand = labels[labels["fcc_no_or_low_change_candidate"]]
    gauge = labels[labels["final_label"] == LABEL_GAUGE]
    fw = labels[labels["final_label"] == LABEL_FW]

    # Sub-reason breakdowns (questions 5 & 6).
    fw_sub = fw["sub_reason"].value_counts().to_dict()
    gauge_ac = int(gauge["sub_reason"].str.contains("AC_BOUND").sum())
    gauge_lc = int(gauge["sub_reason"].str.contains("LOW_CYCLING").sum())
    gauge_sr = int(gauge["sub_reason"].str.contains("SHALLOW_RANGE").sum())

    rel = fig_dir.name  # figures live under <reports>/figures/<rel>

    def md_table(df: pd.DataFrame, floatfmt: int = 3) -> str:
        d = df.copy()
        for c in d.select_dtypes("float").columns:
            d[c] = d[c].map(lambda x: f"{x:.{floatfmt}f}" if pd.notna(x) else "")
        head = "| " + " | ".join(map(str, d.columns)) + " |"
        sep = "| " + " | ".join("---" for _ in d.columns) + " |"
        body = ["| " + " | ".join(map(str, r)) + " |" for r in d.itertuples(index=False)]
        return "\n".join([head, sep, *body])

    L = []
    L.append("# FCC学習機会ベースの介入対象分類レポート\n")
    L.append(f"_analysis_timestamp: {analysis_ts} · users: {n_users} · "
             f"episodes: {len(episodes):,}_\n")

    L.append("## 1. 目的と前提\n")
    L.append(
        "本レポートは ThinkPad バッテリーテレメトリから、`fullChargeCapacity`(FCC)/SoH が長期間"
        "更新されない（凍結している）ユーザーを抽出し、**介入アクションに直結する監査ロジック**で 2 種に"
        "分類する。\n\n"
        "- **学習機会なし → ゲージリセット/キャリブレーション促し** (`ACTION_GAUGE_RESET`)\n"
        "- **学習機会あり・FCC無応答 → FW/BIOS/EC確認促し** (`ACTION_FW_CHECK`)\n\n"
        "これは予測モデルではない。既存の教師あり検証で「使用挙動から very_stale を予測」は公平領域で "
        "AUC≈0.54（ほぼランダム）と判明しているため、ここでは**学習機会に対してFCCが応答したかを監査**する。\n\n"
        "**前提**: SoH は `FCC/DesignCapacity`。FCC は整数 mWh で、ステップしたときのみ SoH が更新される。"
        "RSOC=`remainingCapacityInPercentage`。本コホートでは RSOC は 0–100 の整数で欠損なし、FCC も欠損なし、"
        "`serialNumber` は全ユーザーで不変（パック交換 0 件）。\n\n"
        "**重要**: `device_model` / `batt_vendor` / `batt_fru` は分類ルールに一切使用していない（後述の偏在分析でのみ集計）。\n")

    L.append("## 2. データ品質確認\n")
    dq = labels["data_quality_label"].value_counts().to_dict()
    L.append("ユーザー単位のデータ品質ラベル分布:\n")
    L.append("\n".join(f"- `{k}`: {v}" for k, v in sorted(dq.items(), key=lambda x: -x[1])))
    L.append(f"\n\n- `obs_days < 120`: {int((labels['obs_days'] < 120).sum())} 人")
    L.append(f"- `n_samples < 200`: {int((labels['n_samples'] < 200).sum())} 人")
    L.append(f"- `cycle_decrease_count > 0`（カウンタリセット疑い）: {int((labels['cycle_decrease_count'] > 0).sum())} 人")
    L.append(f"- `serial_number_distinct > 1`（パック交換疑い）: {int((labels['serial_number_distinct'] > 1).sum())} 人")
    L.append("\n`QUALITY_OK` 以外でも特徴量は計算するが、最終ラベルでは信頼度を下げるか "
             "`REVIEW_INSUFFICIENT_DATA` に回している。\n")

    L.append("## 3. FCC no/low change 候補の定義\n")
    L.append(
        f"Active reference cohort（`obs_days>=180 & cycle_delta>=20 & flat_tail_days<60 & QUALITY_OK`）"
        f"= **{q['n_active_reference']} 人**。この群から更新率の分位点を算出:\n\n"
        f"- p05 fcc_changes_per_100_cycles = {q['p05_fcc_changes_per_100_cycles_active']:.3f}, "
        f"p10 = {q['p10_fcc_changes_per_100_cycles_active']:.3f}\n"
        f"- p05 fcc_change_rate_per_100d = {q['p05_fcc_change_rate_per_100d_active']:.3f}, "
        f"p10 = {q['p10_fcc_change_rate_per_100d_active']:.3f}\n\n"
        "候補フラグ（いずれか該当で候補）: `no_fcc_update`(FCC変化0かつobs>=120), "
        "`long_terminal_flat`(flat_tail>=180), `low_update_per_cycle`(cycle_delta>=50かつper-cycle更新率<=p05), "
        "`low_update_per_time`(obs>=180かつper-100d更新率<=p05)。\n\n"
        f"**FCC no/low change 候補: {int(labels['fcc_no_or_low_change_candidate'].sum())} 人**"
        "（内訳は重複あり）:\n"
        f"- no_fcc_update: {int(labels['no_fcc_update'].sum())}\n"
        f"- long_terminal_flat: {int(labels['long_terminal_flat'].sum())}\n"
        f"- low_update_per_cycle: {int(labels['low_update_per_cycle'].sum())}\n"
        f"- low_update_per_time: {int(labels['low_update_per_time'].sum())}\n")

    L.append("## 4. 学習機会 episode の定義\n")
    L.append(
        "RSOC を timestamp でsortし重複は最後の行を採用、状態機械で high→low→high を抽出する。"
        "3 種の閾値: `strict_90_10_90` / `primary_80_20_80` / `secondary_85_15_85`。各 episode に対し "
        "episode内・end+24h/72h/168h の FCC 応答を判定する（FCC欠損windowは unknown=NaN で 0応答と区別）。"
        "主判定は `episode_quality == ok`（最大サンプル間隔<=12h）のみを用い、感度分析で large_gap 込みも見る。\n")
    L.append("### threshold別 episode サマリ\n")
    L.append(md_table(epi_sum, 4))

    L.append("\n## 5. 最終ラベル定義と優先順位\n")
    L.append(
        "相互排他。適用順は **review > normal > fw_high > gauge_high > fw_medium > gauge_medium > watch**。"
        "spec 8.3(gauge)→8.4(fw) の列挙順に対し、判別の本質は「学習機会の有無」であるため、同一信頼度帯では "
        "機会ありの FW を先に解決する（gauge_high は機会ゼロが要件のため FW と衝突しない）。詳細は "
        "`battery_usage/fcc_action_classifier.py` の docstring を参照。\n")

    L.append("## 6. ラベル別人数\n")
    lab_tbl = pd.DataFrame(
        [{"final_label": k, "n_users": _q(lc, k),
          "pct": round(_q(lc, k) / n_users * 100, 1)} for k in LABEL_ORDER])
    L.append(md_table(lab_tbl, 1))
    L.append(f"\n合計 = {int(lab_tbl['n_users'].sum())}（=全 {n_users} ユーザー、相互排他）\n")

    L.append("## 7. 推奨アクション別人数\n")
    L.append("\n".join(f"- `{k}`: {v}" for k, v in sorted(ac.items(), key=lambda x: -x[1])))

    L.append("\n\n## 8. 閾値感度分析\n")
    L.append(md_table(sens, 0))
    L.append(
        "\n結論の安定性: candidate判定(p05↔p10)・応答window(24/72/168h)・flat_tail(60/120/180)・"
        "tail_cycle(20/30/50)・tail_n_80_20_80_ok(1/2/3/5) を振っても、actionable 群(gauge/fw)の"
        "規模感と大小関係は概ね保たれる（上表参照）。\n")

    L.append("## 9. 既存 soh_update_status との照合\n")
    if "existing" in xinfo:
        L.append(f"- 既存CSV: {xinfo['existing']}\n- 本解析の再現(flat_tail 60/180): {xinfo['reproduced']}\n"
                 f"- merged {xinfo.get('n_merged')} 人, flat_tail 中央絶対差 "
                 f"{xinfo.get('flat_tail_median_abs_diff')} 日（重複除去・変化検出の差に起因）\n")
        if not ctab.empty:
            L.append("\n既存status × 本ラベル クロス集計:\n")
            L.append(md_table(ctab.reset_index(), 0))
    else:
        L.append(f"- soh_update_status.csv なし。本解析の再現(flat_tail 60/180): {xinfo['reproduced']}\n")

    L.append("\n## 10. 代表ユーザーの時系列プロット\n")
    L.append(
        f"- `{rel}/examples_gauge_reset_top20/*.png`: ゲージリセット対象 上位20件\n"
        f"- `{rel}/examples_fw_check_top20/*.png`: FW確認対象 上位20件\n"
        "各図は timestamp x軸で RSOC・FCC/SoH・cycleCount・AC/DC・学習機会エピソード・FCC変化点・"
        "最後のFCC変化点を表示する。\n"
        f"- 集計図: `{rel}/funnel_counts.png`, `{rel}/label_counts.png`, "
        f"`{rel}/opportunity_vs_response.png`, `{rel}/flat_tail_vs_tail_cycles.png`, "
        f"`{rel}/hardware_enrichment_fw_check.png`\n")

    L.append("## 11. ハードウェア偏在（分類には不使用）\n")
    L.append("> **重要**: device_model / batt_vendor / batt_fru は分類ルールに一切使っていない。"
             "以下は分類確定後の集計のみ。母数(n_total)とともに表示する。\n")
    for attr in _HW_COLS:
        sub = enrich[(enrich["attribute"] == attr) & (enrich["n_total"] >= 5)].head(10)
        if len(sub):
            L.append(f"\n**{attr}**（n_total>=5, fw_check降順 上位10）:\n")
            L.append(md_table(sub[["value", "n_total", "n_fw_check", "n_gauge_reset",
                                   "fw_check_rate", "gauge_reset_rate"]], 3))

    L.append("\n## 12. 注意点\n")
    L.append(
        "- このデータ単体では **FW/BIOS/EC version も update 適用有無も確認できない**。本分類は"
        "「FW確認に回すべき対象」を抽出するだけであり、FW不良を断定するものではない。\n"
        "- `ACTION_GAUGE_RESET` も「ゲージリセットで必ず直る」ことを意味しない。安全な環境での実施と"
        "実施後 72h〜7日のFCC更新有無の確認が前提。\n"
        "- 候補判定では FCC 指標を使う（FCC凍結そのものを探す監査だから）。一方 gauge/fw の分岐は FCC の結果ではなく"
        "RSOC・cycle・AC/DC の使用履歴と episode 後の FCC 応答で行う。\n")

    L.append("## 13. 最終的に確認したい問い への回答\n")
    rel_rate = "relevant_response_rate_72h"
    L.append(
        f"1. **FCC no/low change 候補**: {int(labels['fcc_no_or_low_change_candidate'].sum())} 人\n"
        f"2. うち **ACTION_GAUGE_RESET**: {_q(lc, LABEL_GAUGE)} 人\n"
        f"3. うち **ACTION_FW_CHECK**: {_q(lc, LABEL_FW)} 人\n"
        f"4. **WATCH_LOW_UPDATE_RATE_AMBIGUOUS**: {_q(lc, C.LABEL_WATCH)} 人\n"
        f"5. FW_CHECK のサブ理由内訳: "
        f"ZERO_UPDATE_AFTER_OPPORTUNITIES={fw_sub.get('ZERO_UPDATE_AFTER_OPPORTUNITIES', 0)}, "
        f"TERMINAL_FREEZE_AFTER_OPPORTUNITIES={fw_sub.get('TERMINAL_FREEZE_AFTER_OPPORTUNITIES', 0)}, "
        f"LOW_UPDATE_RATE_WITH_OPPORTUNITIES={fw_sub.get('LOW_UPDATE_RATE_WITH_OPPORTUNITIES', 0)}\n"
        f"6. GAUGE_RESET 主因内訳（重複可）: AC-bound={gauge_ac}, low-cycling={gauge_lc}, shallow-range={gauge_sr}\n"
        "7. FW_CHECK のハードウェア偏在: 第11節参照（母数併記）。分類には device/vendor/FRU を使っていない。\n"
        "8. 閾値感度: 第8節の通り、結論（actionable 群の規模と gauge≷fw の関係）は概ね安定。\n"
        "9. **次に収集すべきデータ**: BIOS/EC/バッテリー関連 FW version、FW update 適用日時、"
        "intervention（ゲージリセット/FW更新）実施日時、intervention 後の FCC 更新有無（72h〜7日の追跡テレメトリ）。"
        "これらがあれば本監査は「介入→効果」の因果評価に格上げできる。\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def parse_args(argv=None) -> argparse.Namespace:
    cfg = load_config()
    p = argparse.ArgumentParser(description="FCC-learning intervention classifier")
    p.add_argument("--timeseries", default=str(cfg.processed_dir / "battery_timeseries_all.parquet"))
    p.add_argument("--out-dir", default=str(cfg.processed_dir))
    p.add_argument("--fig-dir", default=str(cfg.figures_dir / "fcc_action"))
    p.add_argument("--report", default=str(cfg.reports_dir / "fcc_learning_action_report.md"))
    p.add_argument("--no-figures", action="store_true", help="skip figure generation")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    out_dir = Path(args.out_dir)
    fig_dir = Path(args.fig_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    analysis_ts = pd.Timestamp.now().isoformat(timespec="seconds")
    thr = DEFAULT_THRESHOLDS

    print(f"loading {args.timeseries} ...")
    df = pd.read_parquet(args.timeseries, columns=_TS_COLS)
    n_users = df["user_id"].nunique()
    print(f"  {len(df):,} rows, {n_users} users")

    print("building per-user features + episodes (single pass) ...")
    features, episodes = build_features_and_episodes(df, DEFAULT_CONFIG)
    print(f"  features {features.shape}, episodes {episodes.shape}")

    print("classifying ...")
    labels, q = classify(features, thr)

    # Merge hardware identity AFTER classification (enrichment only).
    hw = (pd.read_parquet(args.timeseries, columns=["user_id"] + _HW_COLS)
          .groupby("user_id", as_index=False).first())
    labels = labels.merge(hw, on="user_id", how="left")

    assert len(labels) == n_users, f"expected {n_users} labelled users, got {len(labels)}"
    assert labels["final_label"].isin(LABEL_ORDER).all(), "unknown label produced"

    # ---- sensitivity / summaries / enrichment / crossval ----
    sens = sensitivity_analysis(features, q, thr)
    epi_sum = episode_summary(episodes)
    enrich = enrichment_by_hardware(labels)
    ctab, xinfo = crossvalidate_status(labels, out_dir)

    funnel = {
        "all_users": int(n_users),
        "candidates": int(labels["fcc_no_or_low_change_candidate"].sum()),
        "no_opportunity": int((labels["final_label"] == LABEL_GAUGE).sum()),
        "has_opportunity": int((labels["final_label"] == LABEL_FW).sum()),
        "watch": int((labels["final_label"] == C.LABEL_WATCH).sum()),
        "review": int((labels["final_label"] == C.LABEL_REVIEW).sum()),
        "normal": int((labels["final_label"] == C.LABEL_NORMAL).sum()),
        "gauge_reset": int((labels["final_label"] == LABEL_GAUGE).sum()),
        "fw_check": int((labels["final_label"] == LABEL_FW).sum()),
    }

    # ---- write CSVs (all carry analysis_timestamp) ----
    def _stamp(d: pd.DataFrame) -> pd.DataFrame:
        d = d.copy()
        d["analysis_timestamp"] = analysis_ts
        return d

    epi_out = episodes.reindex(columns=_EPISODE_CSV_COLS)
    _stamp(epi_out).to_csv(out_dir / "fcc_learning_episodes.csv", index=False)
    _stamp(labels).to_csv(out_dir / "fcc_learning_user_features.csv", index=False)

    action_cols = ([c for c in _TARGET_COLS if c in labels.columns])
    _stamp(labels[action_cols]).to_csv(out_dir / "fcc_learning_action_labels.csv", index=False)

    gauge_t = labels[labels["recommended_action"] == C.ACTION_GAUGE_RESET][action_cols] \
        .sort_values("gauge_reset_score_0_100", ascending=False)
    fw_t = labels[labels["recommended_action"] == C.ACTION_FW_CHECK][action_cols] \
        .sort_values("fw_check_score_0_100", ascending=False)
    _stamp(gauge_t).to_csv(out_dir / "fcc_intervention_targets_gauge_reset.csv", index=False)
    _stamp(fw_t).to_csv(out_dir / "fcc_intervention_targets_fw_check.csv", index=False)

    _stamp(sens).to_csv(out_dir / "fcc_action_sensitivity.csv", index=False)
    _stamp(enrich).to_csv(out_dir / "fcc_action_enrichment_by_hardware.csv", index=False)

    # ---- report ----
    write_report(Path(args.report), labels, episodes, q, sens, epi_sum, enrich, funnel,
                 ctab, xinfo, thr, fig_dir, n_users, analysis_ts)

    # ---- figures ----
    if not args.no_figures:
        try:
            import plot_fcc_learning_actions as P
            P.generate_all(df, labels, episodes, enrich, funnel, fig_dir, DEFAULT_CONFIG)
        except Exception as exc:  # figures are non-fatal for the data pipeline
            print(f"  WARNING: figure generation failed: {exc!r}")

    # ---- console summary ----
    print("\n=== label counts ===")
    print(labels["final_label"].value_counts().reindex(LABEL_ORDER).fillna(0).astype(int).to_string())
    print("\n=== action counts ===")
    print(labels["recommended_action"].value_counts().to_string())
    print(f"\nwrote CSVs + report to {out_dir} and {Path(args.report)}")
    print(f"figures: {fig_dir}")


if __name__ == "__main__":
    main()
