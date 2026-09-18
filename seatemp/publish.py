"""Publish mode: freeze the current archive into a static web page.

`serve` hands the browser a JSON payload from the live database. Publishing
writes the very same payload *into* the page instead, so the result is one
self-contained HTML file with no server, no API and no external requests —
it can be dropped on any static host, e-mailed, or opened straight from disk.
The CSVs and the raw JSON travel next to it so the numbers stay checkable.
"""
import json
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import store
from .config import DB
from .serve import HERE, build_payload

# docs/ rather than site/: GitHub Pages serves the repo root or
# docs/, and nothing else.
OUT = "docs"


def _log(msg: str = "") -> None:
    print(msg, flush=True)   # stays visible when the output is piped


def _inline_json(payload: dict) -> str:
    """Serialise the payload for embedding inside a <script> element.

    `<` is escaped so no string in the data can close the element early
    (`</script>`) or open a comment; \\uXXXX is plain JSON, so the parser in
    the page is unaffected.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return body.replace("<", "\\u003c")


def render_page(payload: dict, stamp: str) -> str:
    """The dashboard with its data baked in."""
    html = (HERE / "dashboard.html").read_text(encoding="utf-8")
    tag = ('<script id="payload" type="application/json">'
           + _inline_json(payload) + "</script>")
    html = html.replace("<!--PAYLOAD-->", tag)
    return html.replace("{{BUILD}}", stamp)


def _human(n: int) -> str:
    return f"{n/1_000_000:.1f} MB" if n >= 1_000_000 else f"{n/1000:.0f} KB"


def publish(out_dir=OUT, db_path=DB, serve_dir=False,
            host="0.0.0.0", port=8765) -> Path:
    from .pipeline import write_observations_csv, write_stations_csv

    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db_path)
    try:
        payload = build_payload(conn)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        page = render_page(payload, stamp)
        (out / "index.html").write_text(page, encoding="utf-8")
        (out / "data.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        n_obs = write_observations_csv(conn, out / "observations.csv")
        n_st = write_stations_csv(conn, out / "stations.csv")
    finally:
        conn.close()

    latest = payload["generated"] or "-"
    _log(f"  published {out}/")
    for f in ("index.html", "data.json", "observations.csv", "stations.csv"):
        _log(f"    {f:<18} {_human((out / f).stat().st_size)}")
    _log(f"\n  {n_obs} observations, {n_st} stations, "
          f"latest reading {latest[:16]}")
    _log("  index.html is self-contained — it also opens directly "
          "from the file system.")
    if serve_dir:
        _serve_static(out, host, port)
    else:
        _log(f"\n  Serve it locally with:"
              f"\n      python3 seatemp.py publish --serve"
              f"\n      python3 -m http.server -d {out} {port}")
    return out


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):   # keep the console readable
        pass


def _serve_static(out: Path, host: str, port: int) -> None:
    """Serve the published directory — plain files, nothing dynamic."""
    handler = partial(_Handler, directory=str(out))
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        if getattr(exc, "errno", None) in (98, 48):   # EADDRINUSE
            _log(f"\n  Port {port} is already in use — something else is "
                  f"probably still running.\n"
                  f"  Pick another port:\n"
                  f"      python3 seatemp.py publish --serve --port {port + 1}")
            return
        raise
    _log(f"\n  ->  http://{host}:{port}/\n")
    _log("  Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("\n  stopped.")
        httpd.server_close()
