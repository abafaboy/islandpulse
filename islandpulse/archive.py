"""Append-only daily archive: one CSV per island plus an ``islands.csv`` index.

The API forgets everything older than 7 days, so each run fetches the recent
complete days and merges them into ``DATA_DIR/<code>.csv``:

* rows are keyed on ``timestamp``; a timestamp is never duplicated;
* rows stay sorted oldest first;
* a value already archived is never changed. The only update to an existing
  row is filling a cell that was empty (``null`` from the API) and now has
  a value.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .client import Client, last_complete_days, validate_code
from .errors import IslandPulseError
from .models import DailyMetrics, Island

CSV_COLUMNS = DailyMetrics.columns()
META_FILE = "islands.csv"
META_COLUMNS = ["code", "title", "creator_code", "created_in", "tags"]

#: Days fetched per run: the most complete days the 7-day window allows.
FETCH_DAYS = 6


def read_codes(path: Path) -> list[str]:
    """Read island codes from a text file: one per line, ``#`` starts a comment.

    Raises :class:`~islandpulse.InvalidIslandCode` naming the bad line.
    Duplicates are dropped, order is kept.
    """
    codes: list[str] = []
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        try:
            code = validate_code(text)
        except IslandPulseError as exc:
            raise type(exc)(f"{path}:{lineno}: {exc}") from None
        if code not in codes:
            codes.append(code)
    return codes


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv_if_changed(path: Path, columns: list[str], rows: Iterable[dict]) -> bool:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    text = buf.getvalue()
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def merge_rows(
    existing: list[dict[str, str]], fetched: Iterable[DailyMetrics]
) -> tuple[list[dict[str, str]], int, int]:
    """Merge fetched rows into archived CSV rows.

    Returns ``(rows sorted by timestamp, rows added, cells filled)``.
    """
    by_ts = {row["timestamp"]: {c: row.get(c) or "" for c in CSV_COLUMNS} for row in existing}
    added = filled = 0
    for metrics in fetched:
        new = {c: _cell(v) for c, v in metrics.as_dict().items()}
        old = by_ts.get(metrics.timestamp)
        if old is None:
            by_ts[metrics.timestamp] = new
            added += 1
            continue
        for column in CSV_COLUMNS:
            if old[column] == "" and new[column] != "":
                old[column] = new[column]
                filled += 1
    return [by_ts[ts] for ts in sorted(by_ts)], added, filled


@dataclass
class ArchiveResult:
    code: str
    added: int = 0
    filled: int = 0
    error: Optional[str] = None


def _update_index(data_dir: Path, islands: list[Island]) -> None:
    index = {row["code"]: row for row in _read_csv(data_dir / META_FILE)}
    for isl in islands:
        index[isl.code] = {
            "code": isl.code,
            "title": isl.title,
            "creator_code": isl.creator_code,
            "created_in": isl.created_in,
            "tags": ";".join(isl.tags),
        }
    _write_csv_if_changed(data_dir / META_FILE, META_COLUMNS, [index[c] for c in sorted(index)])


def archive(
    client: Client,
    codes: Iterable[str],
    data_dir: Path,
    *,
    settle_days: int = 1,
) -> list[ArchiveResult]:
    """Fetch recent complete days for each code and merge them into ``data_dir``.

    :param settle_days: skip the most recent N complete days, so a day is only
        archived once Epic has had time to finish computing it (values are
        frozen once written). With the 6-day fetch window every day is still
        seen several times, so a missed run loses nothing.
    """
    if not 0 <= settle_days < FETCH_DAYS:
        raise ValueError(f"settle_days must be between 0 and {FETCH_DAYS - 1}")
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    start, end = last_complete_days(FETCH_DAYS, client.now())
    cutoff: _dt.date = (end - _dt.timedelta(days=settle_days)).date()

    results: list[ArchiveResult] = []
    islands: list[Island] = []
    for code in codes:
        result = ArchiveResult(code=code)
        results.append(result)
        try:
            islands.append(client.island(code))
            fetched = [m for m in client.metrics(code, start, end) if m.date < cutoff]
        except IslandPulseError as exc:
            result.error = str(exc)
            continue
        path = data_dir / f"{code}.csv"
        rows, result.added, result.filled = merge_rows(_read_csv(path), fetched)
        _write_csv_if_changed(path, CSV_COLUMNS, rows)
    _update_index(data_dir, islands)
    return results
