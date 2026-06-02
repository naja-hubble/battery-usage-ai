"""Pseudonymisation helper.

The on-disk raw directory id (``safe_id``) contains the Windows username and a
device-serial fragment. Shareable artifacts (report.md, figure titles/filenames)
should use a stable pseudonym instead, so PII doesn't leave the local ``data/``
tree. The raw->pseudonym mapping is recoverable from the git-ignored
``cohort_features.csv`` / ``manifest.json``.
"""
from __future__ import annotations

import hashlib


def display_id(raw: str, anonymize: bool = True) -> str:
    """Return a stable pseudonym for ``raw`` when anonymizing, else ``raw`` itself."""
    if not anonymize:
        return raw
    return "user_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
