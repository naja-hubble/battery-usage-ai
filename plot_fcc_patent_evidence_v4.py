#!/usr/bin/env python
"""Render the FCC patent-evidence v4 figures (all dpi=300, anonymous).

Reads the produced v4 aggregate CSV/parquet files in --in-dir and writes figures
to --fig-dir. No user_id / serial / UUID / device field is ever plotted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from battery_usage import patent_common_v4 as pc
from battery_usage import patent_plotting_v4 as plot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FCC patent evidence v4 figures")
    ap.add_argument("--in-dir", default=str(pc.V4_DIR))
    ap.add_argument("--fig-dir", default=str(pc.FIG_DIR))
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args(argv)
    plot.DPI = args.dpi
    plot.build_all(Path(args.in_dir), Path(args.fig_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
