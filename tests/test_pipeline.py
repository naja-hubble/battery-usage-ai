"""Unit tests for the battery-usage pipeline. No network / no real data required.

Run with:  python -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from battery_usage.config import load_config           # noqa: E402
from battery_usage import s3_download, parse, features  # noqa: E402
from battery_usage.schema import BATTERY_COLUMNS        # noqa: E402


# --------------------------------------------------------------------------- #
# Downloader discovery (mocked S3 — no network)
# --------------------------------------------------------------------------- #
class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **_kw):
        yield from self._pages


class _FakeClient:
    def __init__(self, pages):
        self._pages = pages

    def get_paginator(self, _name):
        return _FakePaginator(self._pages)


def _obj(key, size):
    return {"Key": key, "Size": size}


def test_safe_id():
    assert s3_download._safe_id("AAA-PF1_alice") == "AAA-PF1_alice"
    assert s3_download._safe_id("Win11 GM2.0") == "Win11_GM2.0"
    assert s3_download._safe_id("a/b\\c") == "a_b_c"


def test_discover_picks_latest_and_indexes_artifacts():
    cfg = load_config()
    pre = cfg.s3["collection_prefix"]
    pages = [{"Contents": [
        _obj(pre + "PRD||AAA_alice/PmProgramData/battery/UP||20240101-0900.csv", 50000),
        _obj(pre + "PRD||AAA_alice/PmProgramData/battery/UP||20240201-0900.csv", 60000),  # latest
        _obj(pre + "PRD||AAA_alice/PmProgramData/battery_info/UP||20240201-0900.csv", 145),
        _obj(pre + "PRD||BBB_bob/PmProgramData/battery/UP||20240101-0900.csv", 5000),      # tiny
        _obj(pre + "PRD||CCC_carol/PmProgramData/battery/UP||20240101-0900.csv", 30000),
        _obj(pre + "PRD||CCC_carol/PmProgramData/battery/UP||20240101-0900.csv.tmp", 99),  # wrong ext
    ]}]
    users = {u.user_id: u for u in s3_download.discover_users(cfg, client=_FakeClient(pages))}
    assert set(users) == {"AAA_alice", "BBB_bob", "CCC_carol"}
    alice = users["AAA_alice"]
    assert alice.artifacts["battery"].endswith("UP||20240201-0900.csv")  # latest wins
    assert alice.battery_bytes == 60000
    assert "battery_info" in alice.artifacts


def test_select_cohort_filters_and_limits():
    cfg = load_config(overrides={"cohort": {"min_battery_bytes": 20000, "n_users": 2}})
    pre = cfg.s3["collection_prefix"]
    pages = [{"Contents": [
        _obj(pre + "PRD||AAA_alice/PmProgramData/battery/UP||20240201-0900.csv", 60000),
        _obj(pre + "PRD||BBB_bob/PmProgramData/battery/UP||20240101-0900.csv", 5000),   # filtered out
        _obj(pre + "PRD||CCC_carol/PmProgramData/battery/UP||20240101-0900.csv", 30000),
    ]}]
    users = s3_download.discover_users(cfg, client=_FakeClient(pages))
    chosen = s3_download.select_cohort(users, cfg)
    ids = {u.user_id for u in chosen}
    assert "BBB_bob" not in ids
    assert ids == {"AAA_alice", "CCC_carol"}


# --------------------------------------------------------------------------- #
# Parse + features (synthetic time-series)
# --------------------------------------------------------------------------- #
def _write_battery_csv(path: Path):
    """Two days: day1 full on AC, day2 a clean discharge from 100%->40%."""
    rows = [
        # ts, eventCat, chargeStatus, acdcMode, pct, cyc, sn, remCap, fcc, remTime, totChg, awake, hFull, hHot, hFullHot
        ("01/01/2024 08:00:00", 0, 1, 1, 90, 10, "SN1", 4500, 5000, 30, 1000, 100, 5, 1, 0),
        ("01/01/2024 09:00:00", 0, 0, 1, 100, 10, "SN1", 5000, 5000, 0, 1010, 101, 6, 1, 0),
        ("01/02/2024 09:00:00", 0, 2, 0, 100, 11, "SN1", 4900, 4900, 200, 1010, 110, 6, 1, 0),
        ("01/02/2024 10:00:00", 0, 2, 0, 80, 11, "SN1", 3920, 4900, 150, 1010, 110, 6, 1, 0),
        ("01/02/2024 11:00:00", 0, 2, 0, 40, 11, "SN1", 1960, 4900, 60, 1010, 111, 6, 1, 0),
        ("01/02/2024 11:30:00", 0, 1, 1, 45, 11, "SN1", 2205, 4900, 40, 1011, 111, 6, 1, 0),
    ]
    lines = [",".join(BATTERY_COLUMNS)]
    for r in rows:
        lines.append(",".join(str(x) for x in r))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_load_battery_typed_and_sorted(tmp_path):
    p = tmp_path / "battery.csv"
    _write_battery_csv(p)
    df = parse.load_battery(p)
    assert len(df) == 6
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    assert df["timestamp"].is_monotonic_increasing
    assert df["acdc_label"].iloc[2] == "battery"


def test_features_basic(tmp_path):
    udir = tmp_path / "PRD_user"
    udir.mkdir()
    _write_battery_csv(udir / "battery.csv")
    (udir / "battery_info.csv").write_text(
        "StartDate,Serial Number,DesignCapacity,product_uuid\n"
        "2024-01-01 00:00:00, SN1, 5000, abc\n", encoding="utf-8")
    ud = parse.load_user(udir)
    cfg = load_config()
    f = features.extract_features(ud, cfg)

    assert f["n_samples"] == 6
    assert f["design_capacity"] == 5000
    # FCC fell from 5000 (peak) to 4900 -> 2% fade.
    assert f["capacity_fade_pct"] == pytest.approx(2.0, abs=0.01)
    assert f["soh_peak_pct"] == pytest.approx(98.0, abs=0.01)
    # One qualifying discharge session (100 -> 40 over 2h).
    assert f["n_discharge_sessions"] == 1
    assert f["mean_dod_pct"] == pytest.approx(60.0, abs=0.01)
    # Drain rate 60% over 2h = 30 %/h.
    assert f["median_drain_pct_per_hr"] == pytest.approx(30.0, abs=0.1)
    assert 0.0 <= f["ac_time_ratio"] <= 1.0


def test_sample_weight_cap():
    ts = pd.to_datetime(pd.Series(
        ["2024-01-01 00:00:00", "2024-01-01 00:30:00", "2024-01-05 00:00:00"]))
    w = features.sample_weights(ts, max_gap_hours=2.0)
    assert w[0] == pytest.approx(0.5)   # 30 min gap
    assert w[1] == pytest.approx(2.0)   # 4-day gap capped at 2h
    assert w[2] == 0.0                  # last sample


# --------------------------------------------------------------------------- #
# Regression tests for review findings
# --------------------------------------------------------------------------- #
from battery_usage import parse as _parse, anon, aggregate          # noqa: E402
from battery_usage.__main__ import build_parser                     # noqa: E402


def test_cli_flags_must_follow_subcommand():
    """Finding: pre-subcommand flags were silently discarded; now they error."""
    p = build_parser()
    assert p.parse_args(["download", "--n-users", "20"]).n_users == 20   # after: works
    assert p.parse_args(["all", "--seed", "7"]).seed == 7
    with pytest.raises(SystemExit):                                       # before: errors loudly
        p.parse_args(["--n-users", "20", "download"])


def test_load_battery_missing_required_columns_returns_empty(tmp_path):
    """Finding: missing timestamp/acdcMode/chargeStatus crashed the cohort run."""
    p = tmp_path / "battery.csv"
    p.write_text("timestamp,chargeStatus,foo\n01/01/2024 08:00:00,1,9\n", encoding="utf-8")  # no acdcMode
    df = _parse.load_battery(p)        # must NOT raise
    assert df.empty


def test_discharge_session_nan_dod_is_rejected(tmp_path):
    p = tmp_path / "battery.csv"
    rows = [
        ("01/02/2024 09:00:00", 0, 2, 0, "N/A", 11, "SN1", 4900, 4900, 200, 1010, 110, 6, 1, 0),
        ("01/02/2024 11:00:00", 0, 2, 0, 40,    11, "SN1", 1960, 4900, 60, 1010, 111, 6, 1, 0),
        ("01/02/2024 11:30:00", 0, 1, 1, 45,    11, "SN1", 2205, 4900, 40, 1011, 111, 6, 1, 0),
    ]
    lines = [",".join(BATTERY_COLUMNS)] + [",".join(str(x) for x in r) for r in rows]
    p.write_text("\n".join(lines), encoding="utf-8")
    df = _parse.load_battery(p)
    cfg = load_config()
    sess = features.discharge_sessions(df, cfg)
    assert sess["dod"].notna().all()   # the NaN-start session is dropped, not emitted as junk


def test_load_product_non_dict_returns_empty(tmp_path):
    p = tmp_path / "product.json"
    p.write_text('[{"Version": "T14s"}]', encoding="utf-8")   # top-level list
    assert _parse.load_product(p) == {}                       # must NOT raise


def test_safe_id_collisions_are_disambiguated():
    cfg = load_config()
    pre = cfg.s3["collection_prefix"]
    # Two distinct user_ids that both normalize to "HOST_X_user".
    pages = [{"Contents": [
        _obj(pre + "PRD||HOST X_user/PmProgramData/battery/UP||20240101-0900.csv", 30000),
        _obj(pre + "PRD||HOST/X_user/PmProgramData/battery/UP||20240101-0900.csv", 30000),
    ]}]
    users = s3_download.discover_users(cfg, client=_FakeClient(pages))
    safe_ids = [u.safe_id for u in users]
    assert len(safe_ids) == len(set(safe_ids))   # no collision survives


def test_post_peak_fade_rate_uses_post_peak_interval(tmp_path):
    """Finding: fade rate divided by full window understates when peak is mid-window."""
    # FCC peaks at the LAST-but-... actually peak at row 3, then declines; window is long
    # before the peak (flat) so a full-window denominator would dilute the rate.
    rows = []
    # 200 days flat at peak-ish, then a 100-day decline after the peak.
    base = pd.Timestamp("2023-01-01 00:00:00")
    # day 0: fcc 5000, cyc 0 ; day 200: fcc 5000 (peak), cyc 50 ; day 300: fcc 4500, cyc 100
    pts = [(0, 5000, 0), (200, 5000, 50), (300, 4500, 100)]
    for d, fcc, cyc in pts:
        ts = (base + pd.Timedelta(days=d)).strftime("%m/%d/%Y %H:%M:%S")
        rows.append((ts, 0, 1, 1, 90, cyc, "SN1", int(fcc * 0.9), fcc, 0, 1000, 100, 5, 1, 0))
    p = tmp_path / "battery.csv"
    lines = [",".join(BATTERY_COLUMNS)] + [",".join(str(x) for x in r) for r in rows]
    p.write_text("\n".join(lines), encoding="utf-8")
    ud = _parse.load_user(tmp_path)
    f = features.extract_features(ud, load_config())
    # fade = (5000-4500)/5000 = 10%. Post-peak span = 100 days (~0.274 yr), peak->last.
    # post-peak rate ~ 10/0.274 = 36.5 %/yr; a full-window (300-day) denominator would
    # give ~12.2 %/yr. Assert we use the (larger) post-peak rate.
    assert f["fade_pct_per_year"] == pytest.approx(36.5, abs=1.5)
    # post-peak cycles = 100-50 = 50 -> 10/50*100 = 20 per 100 cycles.
    assert f["fade_pct_per_100_cycles"] == pytest.approx(20.0, abs=0.5)


def test_display_id_anonymizes():
    raw = "IMIHO-PF2SCRY9_imiho"
    anon_id = anon.display_id(raw, anonymize=True)
    assert anon_id.startswith("user_") and raw not in anon_id
    assert anon.display_id(raw, anonymize=True) == anon_id   # deterministic
    assert anon.display_id(raw, anonymize=False) == raw


def test_build_cohort_min_rows_filter(tmp_path):
    # Build two users: one with 6 rows, one with 1 row.
    def write_user(name, n):
        d = tmp_path / name
        d.mkdir()
        lines = [",".join(BATTERY_COLUMNS)]
        for i in range(n):
            ts = f"01/0{(i%8)+1}/2024 08:00:00"
            lines.append(f"{ts},0,1,1,90,1,SN,4500,5000,0,1000,100,5,1,0")
        (d / "battery.csv").write_text("\n".join(lines), encoding="utf-8")
    write_user("PRD_big", 6)
    write_user("PRD_tiny", 1)
    cfg = load_config(overrides={"cohort": {"min_rows": 3}})
    cohort = aggregate.build_cohort_table(cfg, user_dirs=[tmp_path / "PRD_big", tmp_path / "PRD_tiny"])
    assert len(cohort) == 1                       # tiny user dropped
    assert "display_id" in cohort.columns
    assert cohort["display_id"].iloc[0].startswith("user_")
