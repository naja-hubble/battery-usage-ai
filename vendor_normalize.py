"""Battery-vendor name normalization for the consolidation pipeline.

The raw vendor.csv ``Manufacturer`` field is dirty: a stray control byte (0x08)
prefixes one value, and several names carry a manufacture-year suffix
("SMP2021" / "SMP2023" / "Sunwoda2023") that splits a single real vendor into
multiple labels. ``normalize_vendor`` collapses those so vendor-level grouping is
meaningful (13 raw labels -> 9 vendors on the current 752-user cohort).

Scope is deliberately conservative — only mechanical cleanups:
  1. drop non-printable / control characters and trim whitespace
  2. strip a trailing manufacture-year suffix (20xx)

It does NOT merge cross-brand aliases (e.g. SWD<->Sunwoda, LGC<->LGES); those are
domain judgements, left to the explicit opt-in ``ALIAS_MAP`` below (empty by
default, so nothing is silently merged).
"""
from __future__ import annotations

import re
from typing import Dict, Optional

_YEAR_SUFFIX = re.compile(r"\s*20\d{2}\s*$")   # e.g. "SMP2023", "Sunwoda2023"

# Optional cross-brand alias merges. Keys/values are POST-normalization names.
# Empty by default; populate to opt in, e.g. {"SWD": "Sunwoda", "LGC": "LGES"}.
ALIAS_MAP: Dict[str, str] = {}


def normalize_vendor(raw) -> Optional[str]:
    """Clean a raw battery-vendor string; return None for empty/NaN.

    >>> normalize_vendor("\\x08SMP"), normalize_vendor("SMP2023"), normalize_vendor("Sunwoda2023")
    ('SMP', 'SMP', 'Sunwoda')
    """
    if raw is None:
        return None
    s = str(raw)
    if s.strip().lower() in ("", "nan", "none"):
        return None
    # 1) keep only printable chars (drops stray \x08 etc.), then trim
    s = "".join(ch for ch in s if ch.isprintable()).strip()
    # 2) drop a trailing manufacture-year suffix
    s = _YEAR_SUFFIX.sub("", s).strip()
    if not s:
        return None
    # 3) optional, opt-in cross-brand alias merge
    return ALIAS_MAP.get(s, s)
