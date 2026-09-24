"""Command-line interface: ``islandpulse island|metrics|new|archive|report``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .archive import FETCH_DAYS, archive, read_codes
from .client import DEFAULT_BASE_URL, Client, last_complete_days
from .errors import IslandPulseError
from .models import DailyMetrics, Island
from .report import write_report


def _table(headers: list[str], rows: list[list[str]], right: set[int]) -> str:
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        return "  ".join(
            c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(cells, widths))
        ).rstrip()

    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def _cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _island_dict(isl: Island) -> dict:
    return {
        "code": isl.code,
        "title": isl.title,
        "creator_code": isl.creator_code,
        "created_in": isl.created_in,
        "tags": list(isl.tags),
    }


def _print_islands(islands: list[Island], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps([_island_dict(i) for i in islands], indent=2, ensure_ascii=False))
    elif fmt == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(["code", "title", "creator_code", "created_in", "tags"])
        for i in islands:
            writer.writerow([i.code, i.title, i.creator_code, i.created_in, ";".join(i.tags)])
    else:
        rows = [[i.code, i.created_in, i.creator_code, i.title] for i in islands]
        print(_table(["code", "made in", "creator", "title"], rows, set()))


def _print_metrics(rows: list[DailyMetrics], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps([r.as_dict() for r in rows], indent=2))
    elif fmt == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(DailyMetrics.columns())
        for r in rows:
            writer.writerow(["" if v is None else v for v in r.as_dict().values()])
    else:
        headers = ["day", "players", "plays", "peak", "minutes", "avg min", "favs", "recs", "d1", "d7"]
        table = [
            [
                r.timestamp[:10],
                _cell(r.unique_players),
                _cell(r.plays),
                _cell(r.peak_ccu),
                _cell(r.minutes_played),
                _cell(r.average_minutes_per_player),
                _cell(r.favorites),
                _cell(r.recommendations),
                _cell(r.retention_d1),
                _cell(r.retention_d7),
            ]
            for r in rows
        ]
        print(_table(headers, table, set(range(1, len(headers)))))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="islandpulse",
        description="Client and daily archiver for Epic's public Fortnite Data API.",
    )
    p.add_argument("--version", action="version", version=f"islandpulse {__version__}")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API root (default: %(default)s)")
    p.add_argument("--timeout", type=float, default=30.0, help="request timeout in seconds")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("island", help="show one island's metadata")
    s.add_argument("code", help="island code, e.g. 0925-4822-4538")
    s.add_argument("--format", choices=["table", "json"], default="table")

    s = sub.add_parser("metrics", help="daily metrics for one island")
    s.add_argument("code")
    s.add_argument(
        "--days",
        type=int,
        default=FETCH_DAYS,
        choices=range(1, FETCH_DAYS + 1),
        metavar="N",
        help="last N complete UTC days, 1-6 (default: %(default)s; the API keeps 7 days from now)",
    )
    s.add_argument("--format", choices=["table", "csv", "json"], default="table")
    s.add_argument(
        "--interval",
        default=None,
        help="UNVERIFIED: passed through as the 'interval' query parameter; omit for daily",
    )

    s = sub.add_parser("new", help="latest islands from the /islands firehose (newest first, not a ranking)")
    s.add_argument("--pages", type=int, default=1, help="pages to fetch (default: %(default)s)")
    s.add_argument("--size", type=int, default=20, help="islands per page (default: %(default)s)")
    s.add_argument("--format", choices=["table", "csv", "json"], default="table")

    s = sub.add_parser("archive", help="append recent complete days to DATA_DIR/<code>.csv")
    s.add_argument("--codes", required=True, type=Path, help="text file, one island code per line")
    s.add_argument("--out", required=True, type=Path, help="data directory")
    s.add_argument(
        "--settle-days",
        type=int,
        default=1,
        choices=range(0, FETCH_DAYS),
        metavar="N",
        help="skip the newest N complete days so values are final before they are frozen (default: %(default)s)",
    )

    s = sub.add_parser("report", help="render the archive as one self-contained HTML page")
    s.add_argument("--data", required=True, type=Path, help="data directory written by 'archive'")
    s.add_argument("--out", required=True, type=Path, help="output HTML file, e.g. site/index.html")
    return p


def main(argv: Optional[Sequence[str]] = None, client: Optional[Client] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "report":
        out = write_report(args.data, args.out)
        print(f"wrote {out}")
        return 0

    client = client or Client(args.base_url, timeout=args.timeout)
    try:
        if args.command == "island":
            isl = client.island(args.code)
            if args.format == "json":
                print(json.dumps(_island_dict(isl), indent=2, ensure_ascii=False))
            else:
                print(f"code:       {isl.code}")
                print(f"title:      {isl.title}")
                print(f"creator:    {isl.creator_code}")
                print(f"created in: {isl.created_in}")
                print(f"tags:       {', '.join(isl.tags)}")
        elif args.command == "metrics":
            start, end = last_complete_days(args.days, client.now())
            rows = client.metrics(args.code, start, end, interval=args.interval)
            _print_metrics(rows, args.format)
        elif args.command == "new":
            islands = list(client.iter_islands(size=args.size, max_pages=args.pages))
            _print_islands(islands, args.format)
        elif args.command == "archive":
            codes = read_codes(args.codes)
            results = archive(client, codes, args.out, settle_days=args.settle_days)
            failed = 0
            for r in results:
                if r.error:
                    failed += 1
                    print(f"{r.code}: FAILED {r.error}", file=sys.stderr)
                else:
                    print(f"{r.code}: +{r.added} rows, {r.filled} cells filled")
            # Only fail the run when nothing could be archived, so one island
            # going private does not stop the others from being committed.
            return 1 if results and failed == len(results) else 0
    except (IslandPulseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
