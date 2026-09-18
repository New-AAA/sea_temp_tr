"""Assign each station to a sea basin.

MGM's payload has no basin field, so it is derived from province (`il`) plus
coordinates. Most provinces touch exactly one sea; the six that touch two get an
explicit coordinate cut, listed below so the convention is auditable and easy to
change. The Aegean/Mediterranean split along the Muğla coast is a matter of
convention rather than a natural boundary -- the cut used here puts Datça in the
Aegean and Marmaris eastward in the Mediterranean.
"""
KARADENIZ = "Karadeniz"       # Black Sea
MARMARA = "Marmara"           # Sea of Marmara (incl. the Turkish Straits)
EGE = "Ege"                   # Aegean
AKDENIZ = "Akdeniz"           # Mediterranean
VAN = "Van Gölü"              # Lake Van (inland; not a sea, but MGM reports it)

_SINGLE_SEA = {
    "Artvin": KARADENIZ, "Rize": KARADENIZ, "Trabzon": KARADENIZ,
    "Giresun": KARADENIZ, "Ordu": KARADENIZ, "Samsun": KARADENIZ,
    "Sinop": KARADENIZ, "Kastamonu": KARADENIZ, "Bartın": KARADENIZ,
    "Zonguldak": KARADENIZ, "Düzce": KARADENIZ, "Sakarya": KARADENIZ,
    "Kırklareli": KARADENIZ,
    "Tekirdağ": MARMARA, "Bursa": MARMARA, "Yalova": MARMARA,
    "Edirne": EGE, "İzmir": EGE, "Aydın": EGE,
    "Antalya": AKDENIZ, "Mersin": AKDENIZ, "Adana": AKDENIZ, "Hatay": AKDENIZ,
    "Van": VAN, "Bitlis": VAN,
}

# province -> (axis, threshold, basin at/above threshold, basin below)
_SPLIT = {
    # Black Sea coast north of the city vs. the Marmara shore and Bosphorus.
    "İstanbul":  ("lat", 41.15, KARADENIZ, MARMARA),
    # Kefken/Black Sea coast vs. the Gulf of İzmit.
    "Kocaeli":   ("lat", 41.00, KARADENIZ, MARMARA),
    # Dardanelles and inner Marmara vs. the islands and Aegean shore.
    "Çanakkale": ("lon", 26.35, MARMARA, EGE),
    # Marmara island and Bandırma vs. Ayvalık on the Aegean.
    "Balıkesir": ("lat", 40.20, MARMARA, EGE),
    # Marmaris eastward to Fethiye vs. Bodrum/Datça.
    "Muğla":     ("lon", 28.00, AKDENIZ, EGE),
}


def classify(il: str, enlem: float | None, boylam: float | None) -> str | None:
    """Return the basin for a station, or None if it cannot be determined."""
    il = (il or "").strip()
    if il in _SPLIT:
        axis, cut, above, below = _SPLIT[il]
        value = enlem if axis == "lat" else boylam
        if value is None:
            return None
        return above if value >= cut else below
    return _SINGLE_SEA.get(il)


def assign_all(conn) -> tuple[int, int]:
    """(Re)assign basins for every station. Returns (assigned, unassigned)."""
    rows = conn.execute(
        "SELECT ist_no, il, enlem, boylam FROM stations"
    ).fetchall()
    assigned = unassigned = 0
    for r in rows:
        basin = classify(r["il"], r["enlem"], r["boylam"])
        conn.execute("UPDATE stations SET basin = ? WHERE ist_no = ?",
                     (basin, r["ist_no"]))
        if basin:
            assigned += 1
        else:
            unassigned += 1
    conn.commit()
    return assigned, unassigned
