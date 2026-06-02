"""Summary 'why SoH freezes' trends figure (4 panels) over the labeled cohort.

A: very_stale rate by battery vendor (descriptive)
B: device-model composition of the usage-UNEXPLAINED (HW/firmware-suspected) group
   -> shows the freeze is NOT X1-only
C: cycles_per_year vs FCC update rate, coloured by status (usage mechanism)
D: usage-based root-cause class breakdown (stale vs very_stale)

    python plot_reason_trends.py   ->  data/reports/figures/soh_reason_trends.png
"""
from __future__ import annotations

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from battery_usage.config import load_config
from soh_update_status import STATUS_COLORS
from classify_reason import CLASS_ORDER

BASE = 55 / 752 * 100        # very_stale base rate (%)


def main() -> None:
    cfg = load_config()
    t = pd.read_csv(cfg.processed_dir / "soh_reason_labeled.csv")
    t["is_vs"] = t["soh_update_status"] == "very_stale"
    fig, ax = plt.subplots(2, 2, figsize=(15, 10))

    # --- A: very_stale rate by vendor ---
    v = (t.dropna(subset=["batt_vendor"]).groupby("batt_vendor")
         .agg(n=("is_vs", "size"), rate=("is_vs", "mean")).assign(rate=lambda d: d.rate * 100)
         .sort_values("rate", ascending=False))
    a = ax[0, 0]
    colors = ["crimson" if i == "LG" else "steelblue" for i in v.index]
    a.bar(v.index, v["rate"], color=colors)
    for i, (nm, row) in enumerate(v.iterrows()):
        a.text(i, row["rate"] + 1, f"n={int(row.n)}", ha="center", fontsize=8)
    a.axhline(BASE, color="grey", ls="--", lw=1, label=f"base {BASE:.1f}%")
    a.set_title("A. very_stale rate by battery vendor (LG red)")
    a.set_ylabel("% very_stale"); a.legend(fontsize=8); a.tick_params(axis="x", rotation=30)

    # --- B: device models in the usage-UNEXPLAINED (HW/firmware) group (not X1-only) ---
    hw = t[t["soh_reason_class"] == "HW_firmware_suspected"]
    x1n = int(hw["device_model"].fillna("").str.contains("X1").sum())
    top = hw["device_model"].value_counts().head(10)[::-1]
    b = ax[0, 1]
    bcol = ["darkred" if "X1" in str(m) else "slategray" for m in top.index]
    b.barh([str(m).replace("ThinkPad ", "") for m in top.index], top.values, color=bcol)
    b.set_title(f"B. HW/firmware-suspected (n={len(hw)}) device models\n"
                f"X1 dark = {x1n}/{len(hw)}; grey = NOT X1 ({len(hw) - x1n} users, "
                f"{hw[~hw.device_model.fillna('').str.contains('X1')].device_model.nunique()} models)")
    b.set_xlabel("users")

    # --- C: cycles vs update rate, by status (usage mechanism) ---
    c = ax[1, 0]
    for st in ["active", "stale", "very_stale"]:
        s = t[t["soh_update_status"] == st]
        c.scatter(s["cycles_per_year"], s["fcc_change_rate_per_100d"] + 0.05,
                  s=14, alpha=0.5, color=STATUS_COLORS[st], label=st)
    c.set_yscale("log"); c.set_xlim(-5, 200)
    c.set_title("C. Cycling vs FCC update rate (low-cycle -> frozen)")
    c.set_xlabel("cycles_per_year"); c.set_ylabel("FCC steps / 100 days (log)")
    c.legend(fontsize=8)

    # --- D: root-cause breakdown ---
    d = ax[1, 1]
    flagged = t[t["soh_update_status"] != "active"]
    tab = (flagged.groupby(["soh_reason_class", "soh_update_status"]).size()
           .unstack(fill_value=0).reindex(CLASS_ORDER).fillna(0))
    d.barh(tab.index, tab.get("very_stale", 0), color="red", label="very_stale")
    d.barh(tab.index, tab.get("stale", 0), left=tab.get("very_stale", 0),
           color="tab:orange", label="stale")
    for i, idx in enumerate(tab.index):
        tot = int(tab.loc[idx].sum())
        d.text(tot + 0.3, i, str(tot), va="center", fontsize=9)
    d.invert_yaxis()
    d.set_title(f"D. Root-cause class of the {len(flagged)} stale/very_stale users")
    d.set_xlabel("users"); d.legend(fontsize=8)

    fig.suptitle("Why SoH freezes — usage-driven (low-cycle / always-AC / shallow discharge) "
                 "vs hardware/firmware-suspected (model-agnostic; not X1-only)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = cfg.figures_dir / "soh_reason_trends.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    main()
