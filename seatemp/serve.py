"""Local web dashboard.

The whole archive is a few hundred KB, so the server hands the browser one
compact JSON payload and the page does all filtering client-side. That keeps
interactions instant and the server to a single stdlib handler with no
dependencies.
"""
import json
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import store
from .config import DB

HERE = Path(__file__).resolve().parent


def _basemap() -> dict:
    """Simplified Türkiye coastline + Lake Van, as lon/lat rings."""
    f = HERE / "basemap.json"
    if not f.exists():
        return {"land": [], "lakes": []}
    return json.loads(f.read_text(encoding="utf-8"))


def build_payload(conn) -> dict:
    stations = [
        {
            "id": r["ist_no"], "ad": r["ad"], "il": r["il"], "ilce": r["ilce"],
            "basin": r["basin"], "lat": r["enlem"], "lon": r["boylam"],
        }
        for r in conn.execute(
            """SELECT ist_no, ad, il, ilce, basin, enlem, boylam
               FROM stations WHERE enlem IS NOT NULL AND boylam IS NOT NULL
               ORDER BY ad"""
        )
    ]
    # Column arrays rather than a list of objects: ~4x smaller over the wire.
    obs = conn.execute(
        """SELECT ist_no, veri_zamani, sicaklik, qc_flag,
                  COALESCE(date_inferred,0) AS inf, COALESCE(source,'mgm') AS src
           FROM observations ORDER BY veri_zamani"""
    ).fetchall()
    return {
        "geo": _basemap(),
        "stations": stations,
        "obs": {
            "station": [r["ist_no"] for r in obs],
            # minutes are noise for this archive; date + hour is enough
            "time": [r["veri_zamani"][:16] for r in obs],
            "temp": [r["sicaklik"] for r in obs],
            "flag": [1 if r["qc_flag"] else 0 for r in obs],
            # 1 = day derived from the capture time of an undated e-Devlet page
            "inf": [r["inf"] for r in obs],
        },
        "generated": conn.execute(
            "SELECT MAX(veri_zamani) FROM observations"
        ).fetchone()[0],
    }


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *a, db_path=None, **kw):
        self.db_path = db_path
        super().__init__(*a, **kw)

    def log_message(self, fmt, *args):  # keep the console readable
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            src = HERE / "dashboard.html"
            # Stamp the file's mtime into the page so it is obvious at a glance
            # whether the browser is showing a stale copy.
            build = datetime.fromtimestamp(src.stat().st_mtime).strftime("%H:%M:%S")
            html = src.read_text(encoding="utf-8").replace("{{BUILD}}", build)
            self._send(html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/data":
            conn = store.connect(self.db_path)
            try:
                payload = build_payload(conn)
            finally:
                conn.close()
            body = json.dumps(payload, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            self._send(body, "application/json; charset=utf-8")
        else:
            self.send_error(404)


def serve(host: str, port: int, db_path=DB) -> None:
    conn = store.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    conn.close()
    try:
        httpd = ThreadingHTTPServer(
            (host, port), partial(Handler, db_path=db_path)
        )
    except OSError as exc:
        if getattr(exc, "errno", None) in (98, 48):   # EADDRINUSE
            print(f"  Port {port} is already in use — another dashboard is "
                  f"probably still running.\n"
                  f"  Open http://{host}:{port}/ , or pick another port:\n"
                  f"      python3 seatemp.py serve --port {port + 1}")
            return
        raise
    print(f"  Türkiye sea-temperature dashboard")
    print(f"  {n} observations loaded from {db_path}")
    print(f"\n  ->  http://{host}:{port}/\n")
    print("  Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
        httpd.server_close()
