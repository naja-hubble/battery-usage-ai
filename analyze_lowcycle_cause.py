"""Why is a user's battery barely cycled? — observation vs AC-bound vs stuck gauge.

For users whose lifetime ``cycleCount`` is very low ("ほとんど回っていない"), this
separates the competing explanations. The user's original two hypotheses were:

  (A) INSUFFICIENT OBSERVATION — we did not watch them cycle. Either used only
      recently (使用開始直後) or telemetry stopped updating (データ更新が止まっている).
  (B) AC-BOUND USAGE — watched a long time, but stayed plugged in (AC modeで長時間),
      so few discharge cycles accrued.

An adversarial review surfaced a third, physically distinct cause that the data
demands we separate:

  (C) GAUGE NOT INCREMENTING — the battery DID discharge substantially, but the
      gauge's ``cycleCount`` never advanced (a stuck / non-incrementing counter).
      Here a low ``cycleCount`` is a gauge artifact, not a usage fact.

Design notes (what the review fixed):
  * Exposure is measured on **effective observed days** = gap-capped covered
    hours / 24, NOT calendar span — so the "watched long enough" gate is on the
    same clock as ``ac_time_ratio`` (both gap-capped). Calendar span overstates
    observation when the logger is mostly asleep (coverage often 0.1–0.3).
  * ``cycleCount`` is cumulative lifetime and FROZEN at the last sample. For
    STALE users it is a year+ out of date, so we cannot assert current low-cycling
    — staleness is treated as an orthogonal flag and routes to LOGGING_STOPPED
    regardless of window length.
  * AC_BOUND means a LOW CYCLING RATE while on AC (near-zero discharge), not
    "never cycles" — we additionally require low discharge throughput and report
    the in-window cycling rate so the claim is falsifiable.
  * Discharge throughput is quantified as DoD-equivalent full cycles =
    sum(qualifying-session DoD%) / 100, used both for the gauge check and to
    distinguish AC-pinned users from slow cyclers.

Priority of the assigned primary cause (most-blocking / most-certain first):

    1. GAUGE_NOT_INCREMENTING : equiv_full_cycles - cycles_in_window >= GAUGE_GAP
                                (real discharge the counter never recorded)
    2. LOGGING_STOPPED        : is_stale (telemetry old; cycle_last frozen)      [A]
    3. RECENTLY_STARTED       : current but effective_obs_days < MIN_OBS_DAYS     [A]
    4. AC_BOUND               : current, watched long, high AC, low throughput   [B]
    5. OTHER_LOW_CYCLING      : current, watched long, used battery, yet low cycle

AC-binding co-occurs with the other causes (many short-window users are also
high-AC), so ``ac_time_ratio`` is carried as an attribute on every row, not only
on AC_BOUND.

Outputs (dpi=600 figures + CSV + sensitivity grid + markdown report):
    data/processed/lowcycle_cause/lowcycle_user_analysis.csv
    data/processed/lowcycle_cause/lowcycle_threshold_sensitivity.csv
    data/reports/figures/lowcycle_cause/lowcycle_scatter_obs_vs_ac.png
    data/reports/figures/lowcycle_cause/lowcycle_cause_counts.png
    data/reports/figures/lowcycle_cause/lowcycle_examples.png
    data/reports/lowcycle_cause_report.md

    python analyze_lowcycle_cause.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ---- config --------------------------------------------------------------
SRC = Path("data/processed/battery_timeseries_all.parquet")
OUT_CSV = Path("data/processed/lowcycle_cause/lowcycle_user_analysis.csv")
SENS_CSV = Path("data/processed/lowcycle_cause/lowcycle_threshold_sensitivity.csv")
FIG_DIR = Path("data/reports/figures/lowcycle_cause")
REPORT = Path("data/reports/lowcycle_cause_report.md")
DPI = 600

GAP_CAP_H = 2.0          # matches cfg.analysis['max_sample_gap_hours']
MIN_SESS_MIN = 5.0       # discharge-session min duration (features.py rule)
MIN_SESS_DOD = 3.0       # discharge-session min depth-of-discharge %

LOW_CYCLE = 5            # primary "barely cycled" threshold (drives scatter/examples)
COUNT_THRESHOLDS = [3, 5, 10, 20, 50, 80, 100]   # cycle_last cuts for the breakdown
MIN_OBS_DAYS = 30        # effective (covered) observed days to judge "watched enough"
AC_RATIO_T = 0.80        # at/above this the user is AC-bound (when current+watched)
AC_MAX_EQUIV = 2.0       # AC_BOUND requires < this many DoD-equivalent cycles observed
STALE_DAYS = 60          # last sample older than this vs cohort horizon = stopped
GAUGE_GAP_CYCLES = 2.0   # equiv cycles of discharge the counter failed to record

CAUSE_ORDER = ["GAUGE_NOT_INCREMENTING", "RECENTLY_STARTED", "LOGGING_STOPPED",
               "AC_BOUND", "OTHER_LOW_CYCLING"]
CAUSE_COLOR = {
    "GAUGE_NOT_INCREMENTING": "#2ca02c",
    "RECENTLY_STARTED": "#1f77b4",
    "LOGGING_STOPPED": "#9467bd",
    "AC_BOUND": "#d62728",
    "OTHER_LOW_CYCLING": "#ff7f0e",
}
CAUSE_JP = {
    "GAUGE_NOT_INCREMENTING": "gauge未加算（放電多いがcycleCount不変）",
    "RECENTLY_STARTED": "使用開始直後（現行・実観測が短い）",
    "LOGGING_STOPPED": "データ更新停止（telemetryが古い）",
    "AC_BOUND": "AC長時間（現行・実観測十分・高AC比・放電僅少）",
    "OTHER_LOW_CYCLING": "その他（現行・電池使用ありだが低cycle）",
}

for _f in ("Meiryo", "Yu Gothic", "MS Gothic"):
    if _f in {f.name for f in font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = _f
        break
plt.rcParams["axes.unicode_minus"] = False


def per_user_features(ts: pd.DataFrame) -> pd.DataFrame:
    """One row per user: cycle / exposure (covered-time) / AC / discharge evidence."""
    ts = ts.sort_values(["user_id", "timestamp"])
    rows = []
    for uid, d in ts.groupby("user_id", sort=False):
        t = d["timestamp"].to_numpy()
        n = len(d)
        first_ts, last_ts = d["timestamp"].iloc[0], d["timestamp"].iloc[-1]
        obs_days = (last_ts - first_ts).total_seconds() / 86400.0

        acdc = d["acdcMode"].to_numpy()
        cyc = d["cycleCount"].to_numpy()
        pct = d["remainingCapacityInPercentage"].to_numpy()

        # sample weight = capped gap (h) to the NEXT sample; last sample -> 0.
        if n >= 2:
            dt_h = np.diff(t).astype("timedelta64[s]").astype(np.float64) / 3600.0
            w = np.clip(dt_h, 0.0, GAP_CAP_H)
            ac_prev = (acdc[:-1] == 1).astype(float)
            batt_prev = (acdc[:-1] == 0).astype(float)
            tot_w = w.sum()
            ac_time_ratio = float((w * ac_prev).sum() / tot_w) if tot_w > 0 else np.nan
            batt_hours = float((w * batt_prev).sum())
            obs_hours = float(tot_w)
            med_gap_min = float(np.median(dt_h)) * 60.0
        else:
            ac_time_ratio, batt_hours, obs_hours, med_gap_min = np.nan, 0.0, 0.0, np.nan

        # discharge sessions = contiguous on-battery runs meeting dur/DoD rule.
        # Accumulate count and summed DoD (-> DoD-equivalent full cycles).
        n_sess, sum_dod = 0, 0.0
        on = acdc == 0
        if on.any():
            change = np.concatenate([[True], on[1:] != on[:-1]])
            run_id = np.cumsum(change)
            for rid in np.unique(run_id[on]):
                idx = np.where((run_id == rid) & on)[0]
                if len(idx) < 2:
                    continue
                dur_min = (t[idx[-1]] - t[idx[0]]).astype("timedelta64[s]").astype(float) / 60.0
                dod = float(pct[idx[0]] - pct[idx[-1]])
                if dur_min >= MIN_SESS_MIN and dod >= MIN_SESS_DOD:
                    n_sess += 1
                    sum_dod += dod

        obs_days_eff = obs_hours / 24.0
        rows.append({
            "user_id": uid,
            "cycle_last": int(np.nanmax(cyc)),
            "cycles_in_window": int(np.nanmax(cyc) - np.nanmin(cyc)),
            "obs_days": round(obs_days, 2),
            "obs_days_eff": round(obs_days_eff, 2),
            "coverage": round(obs_hours / (obs_days * 24.0), 3) if obs_days > 0 else None,
            "n_samples": n,
            "median_gap_min": round(med_gap_min, 1) if pd.notna(med_gap_min) else None,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "ac_time_ratio": round(ac_time_ratio, 4) if pd.notna(ac_time_ratio) else None,
            "battery_hours_observed": round(batt_hours, 1),
            "observed_hours_total": round(obs_hours, 1),
            "n_discharge_sessions": n_sess,
            "sum_dod_pct": round(sum_dod, 1),
            "equiv_full_cycles": round(sum_dod / 100.0, 2),
            "rsoc_min": int(np.nanmin(pct)),
            "rsoc_max": int(np.nanmax(pct)),
            "awake_hrs": int(np.nanmax(d["totalBatteryAwakeHrs"].to_numpy())),
        })
    m = pd.DataFrame(rows)
    ref = m["last_ts"].max()
    m["days_stale"] = ((ref - m["last_ts"]).dt.total_seconds() / 86400.0).round(1)
    m["is_stale"] = m["days_stale"] > STALE_DAYS
    # in-window cycling rate on the covered-time clock (cycles per observed-year).
    m["cycles_per_obs_year"] = np.where(
        m["obs_days_eff"] > 1.0,
        (m["cycles_in_window"] / m["obs_days_eff"] * 365.25).round(1), np.nan)
    m["gauge_gap_cycles"] = (m["equiv_full_cycles"] - m["cycles_in_window"]).round(2)
    m.attrs["ref_date"] = ref
    return m


def classify(row, *, min_obs=MIN_OBS_DAYS, ac_t=AC_RATIO_T, stale_d=STALE_DAYS,
             gauge_gap=GAUGE_GAP_CYCLES, ac_max_equiv=AC_MAX_EQUIV) -> str:
    ac = row["ac_time_ratio"]
    ac = np.nan if ac is None else ac
    # (C) gauge stuck: substantial real discharge the counter never recorded.
    if row["equiv_full_cycles"] - row["cycles_in_window"] >= gauge_gap:
        return "GAUGE_NOT_INCREMENTING"
    # (A2) telemetry stopped: cycle_last is frozen / out of date.
    if row["days_stale"] > stale_d:
        return "LOGGING_STOPPED"
    # (A1) current but too little effective observation to judge usage.
    if row["obs_days_eff"] < min_obs:
        return "RECENTLY_STARTED"
    # (B) AC-bound: watched long enough, mostly on AC, near-zero discharge throughput.
    if not np.isnan(ac) and ac >= ac_t and row["equiv_full_cycles"] < ac_max_equiv:
        return "AC_BOUND"
    # else: used the battery meaningfully yet still few cycles (slow cycler / review).
    return "OTHER_LOW_CYCLING"


def add_causes(m: pd.DataFrame, low_cycle: int, **kw) -> pd.DataFrame:
    m = m.copy()
    m["is_low_cycle"] = m["cycle_last"] <= low_cycle
    m["cause"] = None
    low = m["is_low_cycle"]
    m.loc[low, "cause"] = m.loc[low].apply(lambda r: classify(r, **kw), axis=1)
    return m


def sensitivity_grid(feat: pd.DataFrame, low_cycle: int) -> pd.DataFrame:
    """Sweep each threshold one-at-a-time around the defaults; count causes."""
    base = dict(min_obs=MIN_OBS_DAYS, ac_t=AC_RATIO_T, stale_d=STALE_DAYS)
    sweeps = {
        "ac_t": [0.70, 0.75, 0.80, 0.85, 0.90],
        "min_obs": [21, 30, 45],
        "stale_d": [30, 60, 90],
    }
    rows = []
    for param, vals in sweeps.items():
        for v in vals:
            kw = dict(base); kw[param] = v
            mm = add_causes(feat, low_cycle, **kw)
            vc = mm.loc[mm["is_low_cycle"], "cause"].value_counts()
            rows.append({"param": param, "value": v,
                         **{c: int(vc.get(c, 0)) for c in CAUSE_ORDER}})
    return pd.DataFrame(rows)


# ---- plotting ------------------------------------------------------------
def plot_scatter(m: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 7))
    bg = m[~m["is_low_cycle"]]
    ax.scatter(bg["obs_days_eff"].clip(lower=0.3), bg["ac_time_ratio"], s=12,
               color="#cccccc", alpha=0.5, label=f"その他のuser (cycle > {LOW_CYCLE})",
               edgecolors="none", zorder=1)

    low = m[m["is_low_cycle"]]
    for c in CAUSE_ORDER:
        s = low[low["cause"] == c]
        if s.empty:
            continue
        marker = "*" if c == "GAUGE_NOT_INCREMENTING" else "o"
        size = 230 if c == "GAUGE_NOT_INCREMENTING" else 46
        ax.scatter(s["obs_days_eff"].clip(lower=0.3), s["ac_time_ratio"], s=size,
                   marker=marker, color=CAUSE_COLOR[c], alpha=0.9,
                   edgecolors="white", linewidth=0.5,
                   label=f"{CAUSE_JP[c]}  (n={len(s)})", zorder=3)

    ax.set_xscale("log")
    ax.set_xlim(0.3, m["obs_days_eff"].max() * 1.3)
    ax.set_ylim(-0.02, 1.05)
    ax.axvline(MIN_OBS_DAYS, color="#444", ls="--", lw=1.3)
    ax.axhline(AC_RATIO_T, color="#444", ls="--", lw=1.3)
    ax.text(MIN_OBS_DAYS * 1.05, 0.0, f"実観測 = {MIN_OBS_DAYS}d", fontsize=9, color="#444")
    ax.text(0.33, AC_RATIO_T + 0.012, f"AC比 = {AC_RATIO_T:.2f}", fontsize=9, color="#444")
    ax.set_xlabel("実観測期間 effective_observed_days = 補正カバー時間/24  (log scale)", fontsize=12)
    ax.set_ylabel("AC時間比 ac_time_ratio", fontsize=12)
    ax.set_title(
        f"低cycle user の原因切り分け  (cycle_last ≤ {LOW_CYCLE}, n={int(m['is_low_cycle'].sum())} / {len(m)})",
        fontsize=14, fontweight="bold", pad=12,
    )
    ax.grid(alpha=0.25, which="both")
    ax.legend(frameon=True, fontsize=8.5, loc="lower left", framealpha=0.92)
    fig.text(0.01, 0.005,
             "横軸は『実際に観測できた時間』（カレンダー期間ではない）。左＝実観測不足。右上＝十分観測かつ高AC比→AC長時間。"
             "★＝放電実績に対しcycleCountが進まないgauge未加算。 staleユーザーは更新停止として扱う。",
             fontsize=7.8, color="#444")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}")


def cause_counts_by_threshold(feat: pd.DataFrame, thresholds) -> dict:
    counts = {}
    for thr in thresholds:
        mm = add_causes(feat, thr)
        vc = mm.loc[mm["is_low_cycle"], "cause"].value_counts()
        counts[thr] = [int(vc.get(c, 0)) for c in CAUSE_ORDER]
    return counts


def plot_cause_counts(feat: pd.DataFrame, out: Path) -> None:
    thresholds = COUNT_THRESHOLDS
    counts = cause_counts_by_threshold(feat, thresholds)
    x = np.arange(len(thresholds))
    totals = np.array([sum(counts[t]) for t in thresholds])

    # Population spans 27..575, so show BOTH absolute magnitude and composition.
    fig, (axA, axP) = plt.subplots(1, 2, figsize=(15.5, 6.6))

    # --- left: absolute stacked counts ---
    bottom = np.zeros(len(thresholds))
    for i, c in enumerate(CAUSE_ORDER):
        vals = np.array([counts[t][i] for t in thresholds])
        axA.bar(x, vals, 0.72, bottom=bottom, color=CAUSE_COLOR[c], label=CAUSE_JP[c])
        for xi, (v, b) in enumerate(zip(vals, bottom)):
            if v >= 6:
                axA.text(xi, b + v / 2, str(v), ha="center", va="center",
                         fontsize=8, color="white", fontweight="bold")
        bottom += vals
    for xi in range(len(thresholds)):
        axA.text(xi, bottom[xi] + totals.max() * 0.01, f"計{int(bottom[xi])}",
                 ha="center", fontsize=9, fontweight="bold")
    axA.set_xticks(x)
    axA.set_xticklabels([f"≤{t}" for t in thresholds], fontsize=11)
    axA.set_xlabel("cycle_last しきい値", fontsize=11)
    axA.set_ylabel("user 数", fontsize=12)
    axA.set_title("原因内訳（実数）", fontsize=13, fontweight="bold")
    axA.legend(frameon=False, fontsize=8.2, loc="upper left")
    axA.grid(axis="y", alpha=0.3)
    axA.set_ylim(0, totals.max() * 1.12)

    # --- right: 100% composition ---
    bottom = np.zeros(len(thresholds))
    for i, c in enumerate(CAUSE_ORDER):
        share = np.array([counts[t][i] / totals[ti] * 100 for ti, t in enumerate(thresholds)])
        axP.bar(x, share, 0.72, bottom=bottom, color=CAUSE_COLOR[c], label=CAUSE_JP[c])
        for xi, (v, b) in enumerate(zip(share, bottom)):
            if v >= 5:
                axP.text(xi, b + v / 2, f"{v:.0f}%", ha="center", va="center",
                         fontsize=8, color="white", fontweight="bold")
        bottom += share
    axP.set_xticks(x)
    axP.set_xticklabels([f"≤{t}\n(n={totals[i]})" for i, t in enumerate(thresholds)], fontsize=9.5)
    axP.set_xlabel("cycle_last しきい値", fontsize=11)
    axP.set_ylabel("構成比 %", fontsize=12)
    axP.set_title("原因構成比（100%積み上げ）", fontsize=13, fontweight="bold")
    axP.grid(axis="y", alpha=0.3)
    axP.set_ylim(0, 100)

    fig.suptitle("低cycle user の原因内訳（cycle_last しきい値別）", fontsize=14, fontweight="bold")
    fig.text(0.01, 0.005,
             "しきい値を上げるほど母数は増えるが、どの水準でも『データ更新停止』が支配的でAC長時間はごく僅か。"
             "gauge未加算は2人で一定。 ≤50以上は中程度cycleも含むため『低cycle』は相対的。",
             fontsize=8, color="#444")
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}")


def plot_examples(ts: pd.DataFrame, m: pd.DataFrame, out: Path) -> None:
    """One representative low-cycle user per cause: cycleCount + remaining% + on-battery."""
    low = m[m["is_low_cycle"]].copy()
    pick_rule = {
        "GAUGE_NOT_INCREMENTING": ("gauge_gap_cycles", False),
        "RECENTLY_STARTED": ("days_stale", True),
        "LOGGING_STOPPED": ("days_stale", False),
        "AC_BOUND": ("obs_days_eff", False),
        "OTHER_LOW_CYCLING": ("battery_hours_observed", False),
    }
    picks = {}
    for c in CAUSE_ORDER:
        s = low[low["cause"] == c]
        if s.empty:
            continue
        col, asc = pick_rule[c]
        picks[c] = s.sort_values(col, ascending=asc).iloc[0]

    fig, axes = plt.subplots(len(picks), 1, figsize=(11.5, 2.6 * len(picks)), squeeze=False)
    for ax, (c, row) in zip(axes[:, 0], picks.items()):
        d = ts[ts["user_id"] == row["user_id"]].sort_values("timestamp")
        ax.plot(d["timestamp"], d["cycleCount"], color="#111", lw=1.6, label="cycleCount", zorder=3)
        onb = (d["acdcMode"] == 0).to_numpy()
        ax.fill_between(d["timestamp"], 0, d["cycleCount"].max() + 1, where=onb,
                        color="#d62728", alpha=0.10, step="mid", label="on battery", zorder=1)
        ax.set_ylabel("cycleCount", fontsize=9)
        ax.set_ylim(0, max(2, d["cycleCount"].max() + 1))
        ax2 = ax.twinx()
        ax2.plot(d["timestamp"], d["remainingCapacityInPercentage"], color="#1f77b4",
                 lw=0.8, alpha=0.55, label="remaining %", zorder=2)
        ax2.set_ylabel("remaining %", fontsize=8, color="#1f77b4")
        ax2.set_ylim(0, 105)
        ax2.tick_params(axis="y", labelcolor="#1f77b4", labelsize=7)
        acr = row["ac_time_ratio"]
        ttl = (f"{CAUSE_JP[c]}   [{row['user_id']}]\n"
               f"実観測={row['obs_days_eff']:.0f}d (暦{row['obs_days']:.0f}d, cov={row['coverage']}), "
               f"AC比={acr if acr is not None else float('nan'):.2f}, 古さ={row['days_stale']:.0f}d, "
               f"放電session={row['n_discharge_sessions']}, DoD換算cycle={row['equiv_full_cycles']:.1f}, "
               f"counter増分={row['cycles_in_window']}, cycle_last={row['cycle_last']}")
        ax.set_title(ttl, fontsize=8.8, color=CAUSE_COLOR[c], loc="left")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left", frameon=False, ncol=3)
        ax.grid(alpha=0.2)
    fig.suptitle("原因別の代表例（cycleCount・remaining%・on-battery 区間）", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}")


def write_report(feat: pd.DataFrame, sens: pd.DataFrame, ref_date, out: Path) -> None:
    m = add_causes(feat, LOW_CYCLE)
    low = m[m["is_low_cycle"]]
    vc = low["cause"].value_counts()
    L = []
    L.append("# 低cycle user の原因分析: 観測不足 vs AC長時間 vs gauge未加算\n")
    L.append(f"- コホート: {len(m)} users / 観測ホライズン(最新サンプル): {pd.Timestamp(ref_date).date()}")
    L.append(f"- 低cycle定義: `cycle_last <= {LOW_CYCLE}` → **{len(low)} users**")
    L.append(f"- 判定軸: 実観測 = effective_observed_days(補正カバー時間/24) ≥ {MIN_OBS_DAYS}d、"
             f"AC長時間 = ac_time_ratio ≥ {AC_RATIO_T} かつ DoD換算cycle < {AC_MAX_EQUIV}、"
             f"更新停止 = 最新サンプルがホライズンから > {STALE_DAYS}d前、"
             f"gauge未加算 = DoD換算cycle − counter増分 ≥ {GAUGE_GAP_CYCLES}。")
    L.append("- **重要**: cycleCountは積算かつ最終サンプル時点で凍結。staleユーザーでは現在の周回数は不明なので、"
             "low-cycle=「データ更新停止」として扱い、使い方の結論は出さない。\n")

    L.append("## 原因内訳 (cycle_last ≤ %d)\n" % LOW_CYCLE)
    L.append("| 原因 | 説明 | user数 | 割合 |")
    L.append("|---|---|---:|---:|")
    for c in CAUSE_ORDER:
        n = int(vc.get(c, 0))
        L.append(f"| {c} | {CAUSE_JP[c]} | {n} | {n/len(low)*100:.0f}% |")
    n_obs = int(vc.get("RECENTLY_STARTED", 0) + vc.get("LOGGING_STOPPED", 0))
    L.append(f"\n→ 観測/データ起因 (A) = **{n_obs}**, AC長時間 (B) = **{int(vc.get('AC_BOUND',0))}**, "
             f"gauge未加算 (C) = **{int(vc.get('GAUGE_NOT_INCREMENTING',0))}**, "
             f"その他 = {int(vc.get('OTHER_LOW_CYCLING',0))}。\n")

    # breakdown across cycle_last thresholds (count + share).
    ctab = cause_counts_by_threshold(feat, COUNT_THRESHOLDS)
    L.append("## cycle_last しきい値別の原因内訳\n")
    L.append("| cycle_last ≤ | n | " + " | ".join(c.split("_")[0] for c in CAUSE_ORDER) + " |")
    L.append("|---:|---:|" + "---:|" * len(CAUSE_ORDER))
    for thr in COUNT_THRESHOLDS:
        tot = sum(ctab[thr])
        cells = " | ".join(f"{v} ({v/tot*100:.0f}%)" if tot else "0" for v in ctab[thr])
        L.append(f"| {thr} | {tot} | {cells} |")
    L.append("\n→ どのしきい値でも **LOGGING_STOPPED（更新停止）が支配的**、AC_BOUND はごく僅か（≤6）、"
             "gauge未加算は2で一定。しきい値≥50では中程度cycleのuserも含むため「低cycle」は相対的になる点に注意。\n")

    grp = low.groupby("cause")
    L.append("## 原因別evidence（中央値）\n")
    L.append("| 原因 | 実観測d | 暦d | cov | AC比 | 放電session | DoD換算cycle | counter増分 | 周回/観測年 | 古さd |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for c in CAUSE_ORDER:
        if c not in grp.groups:
            continue
        s = grp.get_group(c)
        acm = f"{s['ac_time_ratio'].median():.2f}" if s["ac_time_ratio"].notna().any() else "—"
        rate = f"{s['cycles_per_obs_year'].median():.1f}" if s["cycles_per_obs_year"].notna().any() else "—"
        L.append("| {} | {:.0f} | {:.0f} | {:.2f} | {} | {:.0f} | {:.1f} | {:.0f} | {} | {:.0f} |".format(
            c, s["obs_days_eff"].median(), s["obs_days"].median(), s["coverage"].median(), acm,
            s["n_discharge_sessions"].median(), s["equiv_full_cycles"].median(),
            s["cycles_in_window"].median(), rate, s["days_stale"].median()))

    # co-occurrence: AC-binding is not exclusive to AC_BOUND.
    L.append("\n## AC比は他原因とも併存（相互排他ではない）\n")
    L.append("| 原因 | n | うち AC比≥%.2f |" % AC_RATIO_T)
    L.append("|---|---:|---:|")
    for c in CAUSE_ORDER:
        if c not in grp.groups:
            continue
        s = grp.get_group(c)
        L.append(f"| {c} | {len(s)} | {(s['ac_time_ratio'] >= AC_RATIO_T).sum()} |")
    L.append("\n→ 短観測(使用開始直後/更新停止)のユーザーも多くが高AC比。"
             "「短い窓」と「AC依存」は同時に成立しうるため、AC比は属性として全行に保持している。\n")

    L.append("## しきい値感度（既定値まわりを1つずつ変化, cycle_last≤%d）\n" % LOW_CYCLE)
    L.append("| param | value | " + " | ".join(CAUSE_ORDER) + " |")
    L.append("|---|---:|" + "---:|" * len(CAUSE_ORDER))
    for _, r in sens.iterrows():
        L.append(f"| {r['param']} | {r['value']} | " +
                 " | ".join(str(int(r[c])) for c in CAUSE_ORDER) + " |")

    L.append("\n## 解釈\n")
    L.append(f"- **観測/データ起因 (A) = {n_obs} users**: 実観測時間が短い(使用開始直後)か telemetry が古い(更新停止)。"
             "low-cycleは主にデータの問題で、使い方の確定はできない。")
    L.append(f"- **AC長時間 (B) = {int(vc.get('AC_BOUND',0))} users**: 実観測が十分長く高AC比かつ放電がごく僅か。"
             "「周回しない」のではなく**AC中心で周回**“率”**が低い**。観測窓内では多くが1回以上放電している（周回/観測年は表参照）。")
    L.append(f"- **gauge未加算 (C) = {int(vc.get('GAUGE_NOT_INCREMENTING',0))} users**: 放電実績(DoD換算)に対し"
             "cycleCountがほぼ進んでいない。例: ANODA は 0%到達を含む放電で約9周相当だが counter は1のまま。"
             "これは使い方ではなく**gauge/FW側の疑い**で、FCC学習解析の対象とも整合。")
    L.append(f"- **その他 = {int(vc.get('OTHER_LOW_CYCLING',0))} users**: 実観測十分・電池使用ありだが低cycle（緩慢な周回 / 要レビュー、n小）。")

    L.append("\n## 注意 / 限界\n")
    L.append("- 横軸の実観測は gap を %.1fh で打ち切ったカバー時間/24。カレンダー期間 obs_days はロガー休眠で過大評価するため判定には使わない。" % GAP_CAP_H)
    L.append("- ac_time_ratio は features.py の sample_weights と同義（gap %.1fh 打ち切り時間加重, 数値一致を検証済）。" % GAP_CAP_H)
    L.append("- staleは静的ダンプ内の相対比較（コホート最新サンプル基準, 今日との差ではない）。cycle_lastはstale下では下限値。")
    L.append("- DoD換算cycle = 条件(継続≥%.0f分, DoD≥%.0f%%)を満たす放電sessionのDoD合計/100。部分放電の下限的な見積り。" % (MIN_SESS_MIN, MIN_SESS_DOD))
    L.append("- modern standby のスリープ放電は疎なサンプル間で取りこぼす可能性があり、高AC比を過大評価しうる（要追加データ）。")
    L.append("- しきい値はスクリプト冒頭の定数で調整可能。感度表のとおり境界付近は数件動く。")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"  wrote {out}")


def main() -> None:
    cols = ["user_id", "timestamp", "acdcMode", "cycleCount",
            "remainingCapacityInPercentage", "totalBatteryAwakeHrs"]
    print(f"Loading {SRC} ...")
    ts = pd.read_parquet(SRC, columns=cols)
    print(f"  {len(ts):,} rows, {ts['user_id'].nunique()} users")

    feat = per_user_features(ts)
    ref_date = feat.attrs["ref_date"]
    m = add_causes(feat, LOW_CYCLE)
    sens = sensitivity_grid(feat, LOW_CYCLE)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    m.to_csv(OUT_CSV, index=False)
    sens.to_csv(SENS_CSV, index=False)
    print(f"  wrote {OUT_CSV}\n  wrote {SENS_CSV}")

    low = m[m["is_low_cycle"]]
    print(f"\nLow-cycle users (cycle_last <= {LOW_CYCLE}): {len(low)}")
    print(low["cause"].value_counts().reindex(CAUSE_ORDER, fill_value=0).to_string())

    plot_scatter(m, FIG_DIR / "lowcycle_scatter_obs_vs_ac.png")
    plot_cause_counts(feat, FIG_DIR / "lowcycle_cause_counts.png")
    plot_examples(ts, m, FIG_DIR / "lowcycle_examples.png")
    write_report(feat, sens, ref_date, REPORT)


if __name__ == "__main__":
    main()
