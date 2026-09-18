"""SQLite storage: snapshots fetched, stations seen, and deduped observations."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,   -- wayback 14-digit ts, or 'live-<iso>'
    source      TEXT NOT NULL,      -- 'wayback' | 'live'
    url         TEXT,
    raw_path    TEXT,               -- cached response, relative to data/
    fetched_at  TEXT,
    http_status INTEGER,
    n_records   INTEGER,
    status      TEXT                -- 'ok' | 'empty' | 'error'
);

CREATE TABLE IF NOT EXISTS stations (
    ist_no     INTEGER PRIMARY KEY,
    ad         TEXT,
    il         TEXT,
    ilce       TEXT,
    enlem      REAL,
    boylam     REAL,
    basin      TEXT,                -- assigned by tools/assign_basins.py
    first_seen TEXT,
    last_seen  TEXT
);

-- One row per (station, measurement instant). The same reading appears in
-- several captures, so the primary key is what makes the archive deduped.
CREATE TABLE IF NOT EXISTS observations (
    ist_no         INTEGER NOT NULL,
    veri_zamani    TEXT    NOT NULL,
    sicaklik       REAL    NOT NULL,
    first_snapshot TEXT,
    qc_flag        TEXT,           -- NULL = passed; see seatemp/qc.py
    source         TEXT,           -- 'mgm' | 'turkiye.gov.tr'
    date_inferred  INTEGER,        -- 1 = day derived from capture time
    PRIMARY KEY (ist_no, veri_zamani)
);

CREATE INDEX IF NOT EXISTS idx_obs_time    ON observations(veri_zamani);
CREATE INDEX IF NOT EXISTS idx_obs_station ON observations(ist_no);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Add columns introduced after a database was first created."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(observations)")}
    for col, decl in (("qc_flag", "TEXT"), ("source", "TEXT"),
                      ("date_inferred", "INTEGER")):
        if col not in cols:
            conn.execute(f"ALTER TABLE observations ADD COLUMN {col} {decl}")
    conn.commit()
    # rows predating provenance tracking all came from the primary source
    conn.execute("UPDATE observations SET source='mgm' WHERE source IS NULL")
    conn.commit()


def record_snapshot(conn, snapshot_id, source, url, raw_path,
                    fetched_at, http_status, n_records, status):
    conn.execute(
        "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
        (snapshot_id, source, url, raw_path, fetched_at,
         http_status, n_records, status),
    )


def fetched_ids(conn) -> set[str]:
    """Snapshots already cached successfully — used to make fetching resumable."""
    return {
        r[0] for r in conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE status != 'error'"
        )
    }


def upsert_records(conn, recs, snapshot_id: str) -> int:
    """Insert observations (ignoring ones already held) and refresh stations.

    Returns the count of genuinely new observations.
    """
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO observations
               (ist_no, veri_zamani, sicaklik, first_snapshot, source, date_inferred)
           VALUES (?,?,?,?,'mgm',0)""",
        [(r.ist_no, r.veri_zamani, r.sicaklik, snapshot_id) for r in recs],
    )
    new = conn.total_changes - before

    for r in recs:
        # Keep the newest metadata (names and coordinates were refined over
        # time) while preserving the earliest first_seen.
        conn.execute(
            """
            INSERT INTO stations (ist_no, ad, il, ilce, enlem, boylam,
                                  first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(ist_no) DO UPDATE SET
                ad         = excluded.ad,
                il         = excluded.il,
                ilce       = excluded.ilce,
                enlem      = COALESCE(excluded.enlem, stations.enlem),
                boylam     = COALESCE(excluded.boylam, stations.boylam),
                first_seen = MIN(stations.first_seen, excluded.first_seen),
                last_seen  = MAX(stations.last_seen,  excluded.last_seen)
            """,
            (r.ist_no, r.ad, r.il, r.ilce, r.enlem, r.boylam,
             r.veri_zamani, r.veri_zamani),
        )
    return new
