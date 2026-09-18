"""Enumerate Wayback captures of the target page.

Uses the TimeMap (Memento) endpoint rather than the CDX API: both list the same
captures, but CDX has been intermittently offline while TimeMap stayed up.
"""
import re

from .config import TIMEMAP_URL
from .http import get_bytes

TS_RE = re.compile(r"/web/(\d{14})/")


def list_snapshots() -> list[str]:
    """Return every capture timestamp (14-digit UTC), oldest first, deduped.

    All URL spellings (http/https, www, trailing slash) normalise to the same
    capture set on Wayback's side, so one TimeMap query is complete.
    """
    status, body = get_bytes(TIMEMAP_URL)
    if status != 200:
        raise RuntimeError(f"TimeMap returned HTTP {status}")
    text = body.decode("utf-8", "replace")
    if "__NEXT_DATA__" not in text and "rel=" not in text:
        raise RuntimeError("TimeMap response does not look like a link list")
    return sorted(set(TS_RE.findall(text)))
