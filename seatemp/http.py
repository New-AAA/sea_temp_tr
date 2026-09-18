"""Polite HTTP with retry/backoff, shared by the Wayback and live fetchers."""
import gzip
import time

import requests

from .config import MAX_RETRIES, POLITE_DELAY, REQUEST_TIMEOUT, USER_AGENT

_session = None
_last_call = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT})
    return _session


def _throttle(delay: float) -> None:
    global _last_call
    wait = delay - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


class FetchError(RuntimeError):
    pass


def get_bytes(url: str, delay: float = POLITE_DELAY) -> tuple[int, bytes]:
    """GET a URL, returning (status, body). Retries 429/5xx with backoff.

    Wayback's `id_` replay hands back the *original* stored bytes, so a response
    the origin gzipped arrives still gzipped with no Content-Encoding header for
    requests to act on. Sniff the magic number and inflate it ourselves.
    """
    last = None
    for attempt in range(MAX_RETRIES):
        _throttle(delay)
        try:
            r = session().get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
            else:
                body = r.content
                if body[:2] == b"\x1f\x8b":
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                return r.status_code, body
        time.sleep(min(60, 5 * 2**attempt))
    raise FetchError(f"{url} failed after {MAX_RETRIES} attempts: {last}")
