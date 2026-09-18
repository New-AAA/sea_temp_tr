"""Fetch -> cache -> parse -> store, plus CSV export and summary stats."""
import csv
import gzip
import sys
from datetime import datetime, timezone

from . import basins, edevlet, qc, store
from .config import DATA, DB, RAW, SNAPSHOT_URL, TARGET_URL
from .http import FetchError, get_bytes
from .parse import ParseError, records
from .wayback import list_snapshots


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _cache_path(snapshot_id: str):
    return RAW / f"{snapshot_id}.html.gz"


def _read_cache(snapshot_id: str) -> str | None:
    p = _cache_path(snapshot_id)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _write_cache(snapshot_id: str, body: bytes) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    p = _cache_path(snapshot_id)
    with gzip.open(p, "wb") as fh:
        fh.write(body)
    return str(p.relative_to(DATA))


def _ingest(conn, snapshot_id, html, source, url, raw_path, http_status):
    """Parse one cached page into the database; returns (n_records, n_new)."""
    try:
        recs = records(html)
    except ParseError as exc:
        _log(f"  ! {snapshot_id}: {exc}")
        store.record_snapshot(conn, snapshot_id, source, url, raw_path,
                              _now(), http_status, 0, "error")
        return 0, 0
    new = store.upsert_records(conn, recs, snapshot_id)
    store.record_snapshot(conn, snapshot_id, source, url, raw_path, _now(),
                          http_status, len(recs), "ok" if recs else "empty")
    return len(recs), new


def cmd_fetch(args) -> int:
    """Download every Wayback capture not already cached, then ingest it."""
    conn = store.connect(DB)
    _log("Listing Wayback captures ...")
    stamps = list_snapshots()
    _log(f"  {len(stamps)} captures: {stamps[0]} .. {stamps[-1]}")

    done = set() if args.refetch else store.fetched_ids(conn)
    todo = [t for t in stamps if t not in done]
    _log(f"  {len(todo)} to fetch, {len(stamps) - len(todo)} already cached")

    failures = 0
    for i, ts in enumerate(todo, 1):
        url = SNAPSHOT_URL.format(ts=ts)
        try:
            status, body = get_bytes(url)
        except FetchError as exc:
            _log(f"[{i}/{len(todo)}] {ts} FAILED: {exc}")
            store.record_snapshot(conn, ts, "wayback", url, None, _now(),
                                  None, 0, "error")
            conn.commit()
            failures += 1
            continue
        if status != 200:
            _log(f"[{i}/{len(todo)}] {ts} HTTP {status}")
            store.record_snapshot(conn, ts, "wayback", url, None, _now(),
                                  status, 0, "error")
            conn.commit()
            failures += 1
            continue
        raw_path = _write_cache(ts, body)
        html = body.decode("utf-8", "replace")
        n, new = _ingest(conn, ts, html, "wayback", url, raw_path, status)
        conn.commit()
        _log(f"[{i}/{len(todo)}] {ts}  {n:3d} records  (+{new} new)")

    basins.assign_all(conn)
    if failures:
        _log(f"\n{failures} capture(s) failed; re-run `fetch` to retry them.")
    conn.close()
    return 0


def cmd_live(args) -> int:
    """Capture the live page — the archive's tail end, beyond the last capture."""
    conn = store.connect(DB)
    status, body = get_bytes(TARGET_URL, delay=0)
    if status != 200:
        _log(f"live fetch: HTTP {status}")
        conn.close()
        return 1
    sid = "live-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = _write_cache(sid, body)
    n, new = _ingest(conn, sid, body.decode("utf-8", "replace"), "live",
                     TARGET_URL, raw_path, status)
    conn.commit()
    basins.assign_all(conn)
    conn.close()
    _log(f"live {sid}: {n} records (+{new} new)")
    return 0


def cmd_parse(args) -> int:
    """Rebuild observations from the cached pages, with no network access."""
    conn = store.connect(DB)
    files = sorted(RAW.glob("*.html.gz"))
    _log(f"Re-parsing {len(files)} cached pages ...")
    total_new = 0
    for p in files:
        sid = p.name[: -len(".html.gz")]
        html = _read_cache(sid)
        source = "live" if sid.startswith("live-") else "wayback"
        url = TARGET_URL if source == "live" else SNAPSHOT_URL.format(ts=sid)
        n, new = _ingest(conn, sid, html, source, url,
                         str(p.relative_to(DATA)), 200)
        total_new += new
    conn.commit()
    basins.assign_all(conn)
    conn.close()
    _log(f"done: {total_new} new observations")
    return 0


def cmd_basins(args) -> int:
    """Re-apply the basin rules (use after editing seatemp/basins.py)."""
    conn = store.connect(DB)
    ok, missing = basins.assign_all(conn)
    conn.close()
    _log(f"basins assigned: {ok}, unassigned: {missing}")
    return 0


CUTOFF = "2021-02-01"


def cmd_edevlet(args) -> int:
    """Import the e-Devlet mirror, which the Archive captured on other days.

    A row is written only when that station has no reading at all on that day,
    so this adds coverage instead of competing with the more precisely
    timestamped primary source.
    """
    conn = store.connect(DB)
    stations = [dict(r) for r in conn.execute("SELECT ist_no, ad FROM stations")]
    index = edevlet.build_index(stations)
    have = {(r[0], r[1]) for r in conn.execute(
        "SELECT ist_no, substr(veri_zamani,1,10) FROM observations")}

    _log("Listing e-Devlet captures ...")
    stamps = [t for t in edevlet.list_snapshots(get_bytes) if t >= "20210101"]
    _log(f"  {len(stamps)} captures from 2021 onward")

    unmatched, n_new, n_skip, n_old, dated, inferred = {}, 0, 0, 0, 0, 0
    for i, ts in enumerate(stamps, 1):
        sid = f"edevlet-{ts}"
        cached = _read_cache(sid)
        if cached is not None:
            html, status = cached, 200
        else:
            try:
                status, body = get_bytes(edevlet.SNAPSHOT_URL.format(ts=ts))
            except FetchError as exc:
                _log(f"[{i}/{len(stamps)}] {ts} FAILED: {exc}")
                continue
            if status != 200:
                _log(f"[{i}/{len(stamps)}] {ts} HTTP {status}")
                continue
            _write_cache(sid, body)
            html = body.decode("utf-8", "replace")

        rows = edevlet.readings(html)
        stamp = edevlet.page_timestamp(html)
        if stamp:
            day, is_inf, when = stamp[:10], 0, stamp
            dated += 1
        else:
            # older template leaves the caption date blank
            day = edevlet.infer_day(ts)
            is_inf, when = 1, day + "T06:00:00.000Z"
            inferred += 1
        if day < CUTOFF:
            n_old += len(rows)
            continue

        added = 0
        for name, temp in rows:
            ino = edevlet.resolve(name, index)
            if ino is None:
                unmatched[name] = unmatched.get(name, 0) + 1
                continue
            if (ino, day) in have:
                n_skip += 1
                continue
            conn.execute(
                """INSERT OR IGNORE INTO observations
                   (ist_no, veri_zamani, sicaklik, first_snapshot, source, date_inferred)
                   VALUES (?,?,?,?,'turkiye.gov.tr',?)""",
                (ino, when, temp, sid, is_inf))
            have.add((ino, day))
            added += 1
            n_new += 1
        store.record_snapshot(conn, sid, "turkiye.gov.tr",
                              edevlet.SNAPSHOT_URL.format(ts=ts),
                              f"raw/{sid}.html.gz", _now(), status,
                              len(rows), "ok" if rows else "empty")
        conn.commit()
        _log(f"[{i}/{len(stamps)}] {ts} -> {day}"
             f"{' (inferred)' if is_inf else ' (stamped) '}  "
             f"{len(rows):3d} rows, +{added} new")

    basins.assign_all(conn)
    conn.close()
    _log(f"\n  new observations   : {n_new}")
    _log(f"  already covered    : {n_skip}")
    _log(f"  before {CUTOFF} : {n_old}")
    _log(f"  captures dated     : {dated} stamped, {inferred} inferred from capture time")
    if unmatched:
        _log(f"  UNMATCHED stations : {len(unmatched)} distinct, "
             f"{sum(unmatched.values())} rows")
        for n, c in sorted(unmatched.items(), key=lambda x: -x[1]):
            _log(f"      {c:4d}  {n}")
    return 0


def cmd_serve(args) -> int:
    """Run the local dashboard."""
    from .serve import serve
    serve(args.host, args.port, DB)
    return 0


def cmd_publish(args) -> int:
    """Freeze the current state into a static, self-contained web page."""
    from .publish import publish
    publish(args.out, DB, serve_dir=args.serve, host=args.host, port=args.port)
    return 0


def cmd_qc(args) -> int:
    """Recompute quality-control flags over the whole archive."""
    conn = store.connect(DB)
    n = qc.apply_flags(conn)
    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    conn.close()
    _log(f"qc: {n} of {total} observations flagged as implausible")
    return 0


def write_observations_csv(conn, path) -> int:
    """One row per reading, with the station columns joined in."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ist_no", "station", "il", "ilce", "basin",
                    "enlem", "boylam", "veri_zamani", "sicaklik_c", "qc_flag",
                    "source", "date_inferred"])
        rows = conn.execute("""
            SELECT o.ist_no, s.ad, s.il, s.ilce, s.basin, s.enlem, s.boylam,
                   o.veri_zamani, o.sicaklik, o.qc_flag,
                   COALESCE(o.source,'mgm'), COALESCE(o.date_inferred,0)
            FROM observations o LEFT JOIN stations s USING (ist_no)
            ORDER BY o.veri_zamani, o.ist_no
        """)
        n = 0
        for r in rows:
            w.writerow(list(r))
            n += 1
    return n


def write_stations_csv(conn, path) -> int:
    """One row per station, with its coverage summarised."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ist_no", "ad", "il", "ilce", "basin", "enlem", "boylam",
                    "first_seen", "last_seen", "n_observations"])
        rows = conn.execute("""
            SELECT s.ist_no, s.ad, s.il, s.ilce, s.basin, s.enlem, s.boylam,
                   s.first_seen, s.last_seen, COUNT(o.ist_no)
            FROM stations s LEFT JOIN observations o USING (ist_no)
            GROUP BY s.ist_no ORDER BY s.ad
        """)
        n = 0
        for r in rows:
            w.writerow(list(r))
            n += 1
    return n


def cmd_export(args) -> int:
    conn = store.connect(DB)
    obs_path, st_path = DATA / "observations.csv", DATA / "stations.csv"
    n_obs = write_observations_csv(conn, obs_path)
    n_st = write_stations_csv(conn, st_path)
    conn.close()
    _log(f"wrote {obs_path} ({n_obs} rows)")
    _log(f"wrote {st_path} ({n_st} rows)")
    return 0


def cmd_stats(args) -> int:
    conn = store.connect(DB)
    q = lambda sql: conn.execute(sql).fetchone()

    snaps = q("""SELECT COUNT(*), SUM(status='ok'), SUM(status='error')
                 FROM snapshots""")
    obs = q("""SELECT COUNT(*), COUNT(DISTINCT ist_no),
                      MIN(veri_zamani), MAX(veri_zamani),
                      COUNT(DISTINCT substr(veri_zamani,1,10))
               FROM observations""")
    tmp = q("""SELECT MIN(sicaklik), MAX(sicaklik), ROUND(AVG(sicaklik),2)
               FROM observations WHERE qc_flag IS NULL""")
    flagged = q("SELECT COUNT(*) FROM observations WHERE qc_flag IS NOT NULL")[0]

    _log("=" * 62)
    _log("  Türkiye sea-water temperature archive")
    _log("=" * 62)
    _log(f"  snapshots ingested : {snaps[0]}  (ok {snaps[1] or 0}, failed {snaps[2] or 0})")
    _log(f"  observations       : {obs[0]}")
    _log(f"  stations           : {obs[1]}")
    _log(f"  distinct dates     : {obs[4]}")
    _log(f"  time span          : {obs[2]}  ->  {obs[3]}")
    _log(f"  qc-flagged         : {flagged}  (excluded from the stats below)")
    _log(f"  temperature °C     : min {tmp[0]}  max {tmp[1]}  mean {tmp[2]}")

    _log("\n  Observations per year:")
    for r in conn.execute("""SELECT substr(veri_zamani,1,4) y, COUNT(*) n,
                                    COUNT(DISTINCT substr(veri_zamani,1,10)) d
                             FROM observations GROUP BY y ORDER BY y"""):
        _log(f"    {r[0]}   {r[1]:6d} obs   {r[2]:3d} distinct dates")

    _log("\n  Basins:")
    for r in conn.execute("""SELECT COALESCE(s.basin,'(unassigned)') b,
                                    COUNT(DISTINCT s.ist_no) st, COUNT(o.ist_no) n
                             FROM stations s LEFT JOIN observations o USING (ist_no)
                             GROUP BY b ORDER BY n DESC"""):
        _log(f"    {r[0]:<22} {r[1]:3d} stations  {r[2]:6d} obs")
    conn.close()
    return 0


def cmd_all(args) -> int:
    for fn in (cmd_fetch, cmd_live, cmd_edevlet, cmd_basins, cmd_qc,
               cmd_export, cmd_stats):
        rc = fn(args)
        if rc:
            return rc
        print()
    return 0
