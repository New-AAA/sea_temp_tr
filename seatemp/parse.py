"""Extract sea-temperature records from a Piri Reis page.

The page is a Next.js app: every server-rendered copy embeds the full station
payload in a <script id="__NEXT_DATA__"> JSON blob, so no JS execution or HTML
scraping is needed. This shape has held across every capture from 2021 to now.
"""
import json
import re
from dataclasses import dataclass

NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


class ParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    ist_no: int
    veri_zamani: str   # ISO-8601 UTC instant of the measurement
    sicaklik: float    # sea-water temperature, degrees Celsius
    ad: str
    il: str
    ilce: str
    enlem: float | None
    boylam: float | None


def extract_payload(html: str) -> list[dict]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ParseError("no __NEXT_DATA__ script found")
    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise ParseError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc
    data = blob.get("props", {}).get("pageProps", {}).get("data")
    if data is None:
        raise ParseError("payload has no props.pageProps.data")
    if not isinstance(data, list):
        raise ParseError(f"props.pageProps.data is {type(data).__name__}, not list")
    return data


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def records(html: str) -> list[Record]:
    """Parse a page into Records, skipping entries with no usable reading."""
    out = []
    for row in extract_payload(html):
        ist_no, when = row.get("istNo"), row.get("denizVeriZamani")
        temp = _num(row.get("denizSicaklik"))
        if ist_no is None or not when or temp is None:
            continue
        out.append(
            Record(
                ist_no=int(ist_no),
                veri_zamani=str(when),
                sicaklik=temp,
                ad=(row.get("istAd") or "").strip(),
                il=(row.get("il") or "").strip(),
                ilce=(row.get("ilce") or "").strip(),
                enlem=_num(row.get("enlem")),
                boylam=_num(row.get("boylam")),
            )
        )
    return out
