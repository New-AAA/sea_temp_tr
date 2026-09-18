"""Quality control: flag physically implausible readings without deleting them.

MGM's feed occasionally carries a faulty sensor value (e.g. 35.7 C in the
Marmara in January 2023, 29.6 C at Akcakoca on the Black Sea in February 2023).

The test is a robust z-score against the median of the station's own basin and
calendar month, scaled by MAD. The threshold is deliberately high: real Turkish
coastal water shows large genuine excursions -- notably Black Sea summer
upwelling, which drops Bartin/Cide/Zonguldak by 10-13 C in days and reaches
|z| ~ 8. Flagging at |z| > 10 separates the two impossible values from every
real phenomenon in the record.

Nothing is deleted. Rows keep a `qc_flag`, so a consumer can filter or not.
"""
import statistics as st

Z_THRESHOLD = 10.0
MIN_SCALE = 0.5      # floor on the MAD scale, so tight groups don't over-flag
MIN_GROUP = 8        # groups smaller than this are not tested


def compute_flags(conn) -> dict[tuple[int, str], str]:
    rows = conn.execute("""
        SELECT o.ist_no, o.veri_zamani, o.sicaklik, s.basin,
               substr(o.veri_zamani, 6, 2) AS ay
        FROM observations o JOIN stations s USING (ist_no)
    """).fetchall()

    groups: dict[tuple, list[float]] = {}
    for r in rows:
        groups.setdefault((r["basin"], r["ay"]), []).append(r["sicaklik"])

    scale = {}
    for key, vals in groups.items():
        med = st.median(vals)
        mad = st.median([abs(v - med) for v in vals])
        scale[key] = (med, max(mad * 1.4826, MIN_SCALE), len(vals))

    flags = {}
    for r in rows:
        med, s, n = scale[(r["basin"], r["ay"])]
        if n < MIN_GROUP:
            continue
        z = (r["sicaklik"] - med) / s
        if abs(z) > Z_THRESHOLD:
            flags[(r["ist_no"], r["veri_zamani"])] = (
                f"outlier: z={z:+.1f} vs {r['basin']}/{r['ay']} median {med:.1f}C"
            )
    return flags


def apply_flags(conn) -> int:
    """Recompute qc_flag for every observation. Returns the number flagged."""
    conn.execute("UPDATE observations SET qc_flag = NULL")
    flags = compute_flags(conn)
    conn.executemany(
        "UPDATE observations SET qc_flag = ? WHERE ist_no = ? AND veri_zamani = ?",
        [(msg, k[0], k[1]) for k, msg in flags.items()],
    )
    conn.commit()
    return len(flags)
