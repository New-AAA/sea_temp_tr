"""Second source: the e-Devlet mirror of the same MGM sea-temperature feed.

https://www.turkiye.gov.tr/deniz-suyu-sicakliklari

Same upstream readings, but the Internet Archive captured it on *different* days,
so it fills gaps in the primary source. It differs in two ways that matter:

  * no station number -- stations are identified by name only, so names must be
    matched back to an `ist_no`;
  * one page-level "updated at" timestamp instead of MGM's per-station times.

Because of the second point a row from here is only inserted when that station
has no reading at all on that calendar day (see pipeline.cmd_edevlet); it adds
new days rather than competing with the more precise primary rows.
"""
import re

from .config import USER_AGENT  # noqa: F401  (kept so config stays the one knob)

TARGET_URL = "https://www.turkiye.gov.tr/deniz-suyu-sicakliklari"
TIMEMAP_URL = "https://web.archive.org/web/timemap/link/" + TARGET_URL
SNAPSHOT_URL = "https://web.archive.org/web/{ts}id_/" + TARGET_URL

TS_RE = re.compile(r"/web/(\d{14})/")
# "09/06/2026 06:00:00 Tarihinde Güncellenen Deniz Suyu Sıcaklıkları"
STAMP_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
TEMP_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)")


class ParseError(RuntimeError):
    pass


def list_snapshots(get_bytes) -> list[str]:
    status, body = get_bytes(TIMEMAP_URL)
    if status != 200:
        raise RuntimeError(f"TimeMap returned HTTP {status}")
    return sorted(set(TS_RE.findall(body.decode("utf-8", "replace"))))


def _text(fragment: str) -> str:
    t = TAG_RE.sub(" ", fragment)
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"')):
        t = t.replace(a, b)
    return " ".join(t.split())


def page_timestamp(html: str) -> str | None:
    """The page's single 'updated at' stamp, as an ISO instant.

    Rendered as dd/mm/yyyy in local Turkish presentation; MGM's own JSON carries
    the same wall-clock value with a Z suffix, so it is kept as-is rather than
    shifted, and provenance is recorded per row.
    """
    m = STAMP_RE.search(_text(html))
    if not m:
        return None
    d, mo, y, hh, mm, ss = m.groups()
    return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}.000Z"


def readings(html: str) -> list[tuple[str, float]]:
    """(station name, temperature) pairs from the results table."""
    out = []
    for name_html, temp_html in ROW_RE.findall(html):
        name = _text(name_html)
        raw = _text(temp_html)
        if not name or name.lower().startswith("merkez"):
            continue
        m = TEMP_RE.search(raw)
        if not m:
            continue
        try:
            out.append((name, float(m.group(1).replace(",", "."))))
        except ValueError:
            continue
    return out


# --- station-name matching -------------------------------------------------
# e-Devlet spells the same station slightly differently over time: "FENER" vs
# "FENERİ", "(YILDIZ ADASI)" vs "(YILDIZADASI)". Collapsing to letters+digits
# and folding the FENER(İ) suffix absorbs those without inventing matches.
_STRIP = re.compile(r"[^0-9A-ZÇĞİÖŞÜ]", re.I)


def norm(name: str) -> str:
    # "FENERİ" also occurs mid-string ("... FENERİ (ANA)"), so fold it anywhere
    # rather than only as a suffix.
    k = _STRIP.sub("", (name or "").upper())
    return k.replace("FENERİ", "FENER").replace("FENERI", "FENER")


# MGM relabelled a number of stations over the archived period. Each pair below
# was confirmed the same station by two independent checks across the 39
# captures: the two names NEVER appear in the same capture, and the old label
# stops exactly when the new one starts (a clean handover, 10/10). Without that
# evidence a name stays unmatched and is reported rather than guessed at.
_RENAMES = [
    ("ENEZ ANA MENDİREK ( BATI ) FENERİ", "ENEZ TALİ MENDİREK FENERİ"),
    ("KARATAŞ BALIKÇI BARINAĞI ANA MENDİREK FENER",
     "KARATAŞ BALIKÇI BARINAĞI TALİ MENDİREK FENERİ"),
    ("ÇAYELİ BALIKÇI BARINAĞI ANA MENDİREK FENER",
     "ÇAYELİ BALIKÇI BARINAĞI TALİ MENDİREK FENERİ"),
    ("MARMARA ADASI BARINAK ANA MENDİREK FENERİ",
     "MARMARA BARINAK ANA MENDİREK FENERİ"),
    ("MARMARA ADASI/SARAYLAR KÖYÜ BARINAK (SANDAL BASENİ) FENERİ",
     "MARMARA/SARAYLAR KÖYÜ BARINAK (SANDAL BASENİ) FENERİ"),
    ("KANDIRA/KEFKEN ADASI BATI MENDİREK FENERİ",
     "KANDIRA/KEFKEN ADASI DOĞU MENDİREK FENERİ"),
    ("GİRESUN PALAMUT KAYALIĞI IŞIKLI ŞAMANDIRA",
     "GİRESUN PALAMUT KAYALIĞI MAHMUZ FENERİ"),
    ("MERSİN DIŞ KANAL IŞIKLI ŞAMANDIRA",
     "MERSİN GÜNEY MENDİREK İSTİKAMET FENERİ"),
    ("BOZCAADA/DAMLACIK FENERİ",
     "BOZCAADA LİMAN GİRİŞİ GÜNEY MENDİREK FENERİ"),
]
ALIASES: dict[str, str] = {}   # filled below, keyed by normalised old name


def _init_aliases() -> None:
    for old, new in _RENAMES:
        ALIASES[norm(old)] = new


_init_aliases()


def infer_day(capture_ts: str) -> str:
    """Reading date for a capture whose page carries no date.

    MGM refreshes the bulk synoptic reading at 06:00; a capture taken before
    that still shows the previous day's figures. Validated three ways: the one
    capture that *does* carry a stamp (taken 00:41, stamped the previous day),
    and the two overlapping captures taken before 06:00, which both agree far
    better with the previous day than with their own (median 0.10-0.20 C vs
    0.30 C). Rows dated this way are marked date_inferred=1.
    """
    import datetime as _dt
    cap = _dt.datetime.strptime(capture_ts, "%Y%m%d%H%M%S")
    if cap.hour < 6:
        cap -= _dt.timedelta(days=1)
    return cap.strftime("%Y-%m-%d")


def build_index(stations) -> dict[str, int]:
    """normalised name -> ist_no, for rows from the primary source."""
    idx = {}
    for s in stations:
        idx[norm(s["ad"])] = s["ist_no"]
    return idx


def resolve(name: str, index: dict[str, int]) -> int | None:
    k = norm(name)
    if k in index:
        return index[k]
    a = ALIASES.get(k)
    return index.get(norm(a)) if a else None
