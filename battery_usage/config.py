"""Configuration loading and path management.

Defaults live in this module; an optional ``config.yaml`` (and ``config.local.yaml``
which takes precedence) at the repo root can override any value. Nothing here holds
secrets — AWS credentials are read from the CSV referenced by ``s3.credentials_csv``.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml is a declared dependency
    yaml = None


# Repo root = parent of this package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent


_DEFAULTS: Dict[str, Any] = {
    "s3": {
        "bucket": "rprm-alpha-01",
        "collection_prefix": "thinklog/formatted/battery/collection/",
        "credentials_csv": "key/ymaeda6_accessKeys.csv",
        "region": None,
    },
    "cohort": {
        "n_users": 25,
        "min_battery_bytes": 20000,
        "min_rows": 50,
        "seed": 42,
        "selection": "random",
        "max_workers": 8,
    },
    "download": {
        "artifacts": ["battery", "battery_info", "vendor", "drain_rate", "product"],
    },
    "paths": {
        "data_dir": "data",
    },
    "analysis": {
        "max_sample_gap_hours": 2.0,
        "min_session_drain_pct": 3,
        "min_session_minutes": 5,
        "n_personas": 4,
        "anonymize": True,   # use pseudonymous ids in shareable report/figures
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    """Resolved configuration with convenience path accessors."""

    s3: Dict[str, Any]
    cohort: Dict[str, Any]
    download: Dict[str, Any]
    paths: Dict[str, Any]
    analysis: Dict[str, Any]
    repo_root: Path = REPO_ROOT

    # ---- path helpers -------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self.repo_root / self.paths["data_dir"]

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def figures_dir(self) -> Path:
        return self.reports_dir / "figures"

    @property
    def manifest_path(self) -> Path:
        return self.raw_dir / "manifest.json"

    @property
    def credentials_path(self) -> Path:
        return self.repo_root / self.s3["credentials_csv"]

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.processed_dir, self.reports_dir, self.figures_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- credentials --------------------------------------------------
    def load_aws_keys(self) -> Dict[str, str]:
        """Read the IAM access-key CSV. Returns dict with the two key fields."""
        path = self.credentials_path
        if not path.exists():
            raise FileNotFoundError(
                f"AWS credentials CSV not found at {path}. "
                f"Set s3.credentials_csv in config or place the file there."
            )
        with open(path, mode="r", encoding="utf-8-sig") as fh:
            row = next(csv.DictReader(fh))
        # Be tolerant of header whitespace/casing variants.
        norm = {k.strip().lower(): v for k, v in row.items()}
        try:
            return {
                "aws_access_key_id": norm["access key id"].strip(),
                "aws_secret_access_key": norm["secret access key"].strip(),
            }
        except KeyError as exc:  # pragma: no cover
            raise KeyError(
                f"Credentials CSV {path} missing expected column {exc}. "
                f"Got columns: {list(row)}"
            ) from exc


def load_config(path: Optional[os.PathLike] = None, overrides: Optional[Dict[str, Any]] = None) -> Config:
    """Load defaults, then ``config.yaml``/``config.local.yaml``, then explicit overrides."""
    data = _DEFAULTS
    candidates: List[Path] = []
    if path is not None:
        candidates.append(Path(path))
    else:
        candidates.append(REPO_ROOT / "config.yaml")
        candidates.append(REPO_ROOT / "config.local.yaml")  # wins if present
    for cand in candidates:
        if cand.exists() and yaml is not None:
            with open(cand, "r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            data = _deep_merge(data, loaded)
    if overrides:
        data = _deep_merge(data, overrides)
    return Config(
        s3=data["s3"],
        cohort=data["cohort"],
        download=data["download"],
        paths=data["paths"],
        analysis=data["analysis"],
    )
