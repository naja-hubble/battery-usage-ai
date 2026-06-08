#!/usr/bin/env python
"""Plot driver for the Rolling 30d FCC online detector v2.0 (spec sections 5, 16.3).

Reads the v2 output CSV/parquet files produced by ``analyze_fcc_online_sliding30_v2.py`` and
renders every required figure at the requested dpi (default 300), plus per-tier example-user
plots. Each figure is independent (one missing input never aborts the rest).

Run:
  python plot_fcc_online_sliding30_v2.py \
    --in-dir data/processed/fcc_online_v2 --fig-dir data/reports/figures/fcc_online_v2 \
    --timeseries data/processed/battery_timeseries_all.parquet --dpi 300 --n-examples 20
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from battery_usage import online_plotting_v2 as pv2                         # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Plot Rolling 30d FCC online detector v2.0")
    ap.add_argument("--in-dir", default="data/processed/fcc_online_v2")
    ap.add_argument("--fig-dir", default="data/reports/figures/fcc_online_v2")
    ap.add_argument("--timeseries", default="data/processed/battery_timeseries_all.parquet")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--n-examples", type=int, default=20)
    ap.add_argument("--no-examples", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    ts_path = None if args.no_examples else args.timeseries
    print(f"[plot v2] reading {args.in_dir} -> {args.fig_dir} (dpi={args.dpi})", flush=True)
    P = pv2.render_all(args.in_dir, args.fig_dir, args.dpi, ts_path=ts_path,
                       n_examples=args.n_examples)
    print(f"[plot v2] done in {time.time() - t0:.1f}s: {P.n_ok} figures, {P.n_skip} skipped",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
