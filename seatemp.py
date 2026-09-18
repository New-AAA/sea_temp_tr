#!/usr/bin/env python3
"""CLI for the Türkiye sea-water temperature archive.

  python3 seatemp.py all      # fetch everything + live + export + stats
  python3 seatemp.py fetch    # download/ingest Wayback captures (resumable)
  python3 seatemp.py live     # append today's reading from the live site
  python3 seatemp.py edevlet  # import the e-Devlet mirror (extra capture days)
  python3 seatemp.py parse    # rebuild the DB from cached pages, offline
  python3 seatemp.py basins   # re-apply sea-basin rules to stations
  python3 seatemp.py qc       # recompute quality-control flags
  python3 seatemp.py export   # write data/observations.csv + data/stations.csv
  python3 seatemp.py stats    # summarise what has been collected
  python3 seatemp.py serve    # open the local dashboard in a browser
  python3 seatemp.py publish  # freeze the current state into docs/ as a static site
"""
import argparse
import sys

from seatemp import pipeline

COMMANDS = {
    "all":    pipeline.cmd_all,
    "fetch":  pipeline.cmd_fetch,
    "live":   pipeline.cmd_live,
    "edevlet": pipeline.cmd_edevlet,
    "parse":  pipeline.cmd_parse,
    "basins": pipeline.cmd_basins,
    "qc": pipeline.cmd_qc,
    "export": pipeline.cmd_export,
    "stats":  pipeline.cmd_stats,
    "serve":  pipeline.cmd_serve,
    "publish": pipeline.cmd_publish,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="seatemp",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument(
        "--refetch", action="store_true",
        help="re-download captures even if already cached",
    )
    ap.add_argument("--host", default="0.0.0.0",
                    help="serve/publish --serve: bind address")
    ap.add_argument("--port", type=int, default=8765,
                    help="serve/publish --serve: port")
    ap.add_argument("--out", default="docs",
                    help="publish: output directory (default: docs/)")
    ap.add_argument("--serve", action="store_true",
                    help="publish: also serve the published directory")
    args = ap.parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
