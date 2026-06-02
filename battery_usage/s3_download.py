"""Discover users in S3 and download a filtered cohort to ``data/raw/``.

The bucket holds ~1800 per-device/user collections under
``thinklog/formatted/battery/collection/PRD||<DEVICE>_<user>/``. About 40% have no
real battery history (preload/test machines), so discovery filters those out.

The main battery time-series files are cumulative, so we only fetch the *latest*
file in each artifact category — a single, cheap superset of the whole history.

Discovery does ONE paginated listing of the whole collection prefix and indexes
artifacts client-side, instead of issuing a list call per user.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import concurrent.futures
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

import boto3
from tqdm import tqdm

from .config import Config
from .schema import ARTIFACT_PATHS


def make_client(cfg: Config):
    keys = cfg.load_aws_keys()
    session = boto3.Session(region_name=cfg.s3.get("region") or None, **keys)
    return session.client("s3")


@dataclass
class UserRef:
    """One device/user collection and the latest file found per artifact."""

    user_id: str                       # raw id, e.g. "ADIEHL-PF4CNVD9_adiehl"
    safe_id: str                       # filesystem-safe id
    prefix: str                        # full S3 prefix of the collection
    artifacts: Dict[str, str] = field(default_factory=dict)   # artifact -> S3 key (latest)
    sizes: Dict[str, int] = field(default_factory=dict)       # artifact -> bytes
    battery_bytes: int = 0             # convenience: size of latest battery file


def _safe_id(user_id: str) -> str:
    """Make a filesystem-safe directory name from a raw user id."""
    s = user_id.strip().replace("||", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "unknown"


# Reverse map: category subpath -> artifact name, longest first so the more
# specific battery_info/ matches before battery/.
_SUBPATH_TO_ARTIFACT = sorted(
    ((meta["subpath"], name) for name, meta in ARTIFACT_PATHS.items()),
    key=lambda kv: len(kv[0]),
    reverse=True,
)


def discover_users(cfg: Config, client=None) -> List[UserRef]:
    """List the whole collection prefix once and build a per-user artifact index."""
    client = client or make_client(cfg)
    bucket = cfg.s3["bucket"]
    prefix = cfg.s3["collection_prefix"]

    users: Dict[str, UserRef] = {}
    paginator = client.get_paginator("list_objects_v2")
    n_objects = 0
    for page in tqdm(paginator.paginate(Bucket=bucket, Prefix=prefix),
                     desc="listing S3", unit="page"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj["Size"]
            n_objects += 1
            rest = key[len(prefix):]
            if "/" not in rest:
                continue
            user_folder, tail = rest.split("/", 1)        # "PRD||<id>", "<category>/.../file"
            user_id = user_folder.split("||", 1)[-1]
            # Which artifact category does this key belong to?
            artifact = None
            for subpath, name in _SUBPATH_TO_ARTIFACT:
                if tail.startswith(subpath):
                    artifact = name
                    break
            if artifact is None or size == 0:
                continue
            if not key.endswith(ARTIFACT_PATHS[artifact]["ext"]):
                continue
            ref = users.get(user_id)
            if ref is None:
                ref = UserRef(user_id=user_id, safe_id=_safe_id(user_id), prefix=prefix + user_folder + "/")
                users[user_id] = ref
            # Keep the lexically-largest key per artifact == latest (UP||YYYYMMDD-HHMM).
            if artifact not in ref.artifacts or key > ref.artifacts[artifact]:
                ref.artifacts[artifact] = key
                ref.sizes[artifact] = size
    for ref in users.values():
        ref.battery_bytes = ref.sizes.get("battery", 0)
    # Disambiguate safe_id collisions so two distinct users can never silently
    # clobber each other's download directory. Deterministic hash suffix.
    counts = Counter(u.safe_id for u in users.values())
    for u in users.values():
        if counts[u.safe_id] > 1:
            u.safe_id = f"{u.safe_id}__{hashlib.sha1(u.user_id.encode('utf-8')).hexdigest()[:6]}"
    print(f"  scanned {n_objects} objects across {len(users)} collections")
    return list(users.values())


def select_cohort(users: List[UserRef], cfg: Config) -> List[UserRef]:
    """Filter to users with real battery history, then pick ``n_users``."""
    c = cfg.cohort
    eligible = [u for u in users if u.battery_bytes >= c["min_battery_bytes"]]
    eligible.sort(key=lambda u: u.safe_id)  # deterministic base order before sampling
    n = c["n_users"]
    if c.get("selection") == "largest":
        chosen = sorted(eligible, key=lambda u: u.battery_bytes, reverse=True)[:n]
    else:
        rng = random.Random(c.get("seed", 42))
        chosen = rng.sample(eligible, min(n, len(eligible)))
    chosen.sort(key=lambda u: u.safe_id)
    print(f"  {len(eligible)} eligible users (>= {c['min_battery_bytes']} battery bytes); "
          f"selected {len(chosen)}")
    return chosen


def _download_one(client, bucket: str, key: str, dest) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(dest))
    return dest.stat().st_size


def download_cohort(cfg: Config, client=None, users: Optional[List[UserRef]] = None) -> dict:
    """Download the selected cohort's artifacts into ``data/raw/<safe_id>/``.

    Returns the manifest dict (also written to ``data/raw/manifest.json``).
    """
    client = client or make_client(cfg)
    cfg.ensure_dirs()
    if users is None:
        users = select_cohort(discover_users(cfg, client), cfg)

    bucket = cfg.s3["bucket"]
    wanted = list(cfg.download["artifacts"])

    # Build the flat list of (user, artifact, key, dest) download jobs.
    jobs = []
    for u in users:
        for art in wanted:
            key = u.artifacts.get(art)
            if not key:
                continue
            ext = ARTIFACT_PATHS[art]["ext"]
            dest = cfg.raw_dir / u.safe_id / f"{art}{ext}"
            jobs.append((u, art, key, dest))

    errors: List[str] = []
    succeeded: set = set()      # (safe_id, artifact) pairs actually written to disk
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.cohort["max_workers"]) as ex:
        futs = {ex.submit(_download_one, client, bucket, key, dest): (u, art)
                for (u, art, key, dest) in jobs}
        for fut in tqdm(concurrent.futures.as_completed(futs), total=len(futs),
                        desc="downloading", unit="file"):
            u, art = futs[fut]
            try:
                size = fut.result()
                if size > 0:
                    succeeded.add((u.safe_id, art))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{u.safe_id}/{art}: {exc}")

    manifest = {
        "bucket": bucket,
        "collection_prefix": cfg.s3["collection_prefix"],
        "n_users": len(users),
        "artifacts": wanted,
        "cohort": {k: cfg.cohort[k]
                   for k in ("n_users", "min_battery_bytes", "min_rows", "seed", "selection")
                   if k in cfg.cohort},
        "users": [
            {
                "safe_id": u.safe_id,
                "user_id": u.user_id,
                "battery_bytes": u.battery_bytes,
                # Only artifacts whose bytes actually landed on disk, not merely discovered.
                "downloaded": sorted(a for a in wanted if (u.safe_id, a) in succeeded),
            }
            for u in users
        ],
        "errors": errors,
    }
    with open(cfg.manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"  downloaded {len(jobs) - len(errors)}/{len(jobs)} files for {len(users)} users "
          f"-> {cfg.raw_dir}")
    if errors:
        print(f"  WARNING: {len(errors)} download errors (see manifest.json)")
    return manifest
