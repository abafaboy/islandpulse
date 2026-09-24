import copy
import csv

import pytest
from fakes import fixture_client, fixture_routes, load

from islandpulse import DailyMetrics, InvalidIslandCode
from islandpulse.archive import CSV_COLUMNS, archive, merge_rows, read_codes

CODE = "0925-4822-4538"


def read(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_archive_writes_sorted_rows_and_index(tmp_path):
    client, _ = fixture_client()
    results = archive(client, [CODE], tmp_path)
    assert results[0].error is None and results[0].added == 2
    rows = read(tmp_path / f"{CODE}.csv")
    assert list(rows[0]) == CSV_COLUMNS
    assert [r["timestamp"] for r in rows] == ["2026-09-21T00:00:00.000Z", "2026-09-22T00:00:00.000Z"]
    assert rows[0]["unique_players"] == "88" and rows[0]["average_minutes_per_player"] == "38.22"
    assert rows[1]["recommendations"] == ""  # null stays empty
    index = read(tmp_path / "islands.csv")
    assert index == [
        {
            "code": CODE,
            "title": "WAR TYCOON 3 💣",
            "creator_code": "notales",
            "created_in": "UEFN",
            "tags": "casual;tycoon;simulator;pvp",
        }
    ]


def test_archive_twice_is_idempotent(tmp_path):
    client, _ = fixture_client()
    archive(client, [CODE], tmp_path)
    first = (tmp_path / f"{CODE}.csv").read_text()
    results = archive(client, [CODE], tmp_path)
    assert results[0].added == 0 and results[0].filled == 0
    assert (tmp_path / f"{CODE}.csv").read_text() == first
    assert len(read(tmp_path / f"{CODE}.csv")) == 2


def test_archive_fills_nulls_but_never_rewrites_values(tmp_path):
    client, _ = fixture_client()
    archive(client, [CODE], tmp_path)

    later = copy.deepcopy(load("fortnite_metrics_0925-4822-4538.json"))
    later["recommendations"][1]["value"] = 2  # was null
    later["peakCCU"][0]["value"] = 999  # was 16: must NOT overwrite
    later["plays"].append({"value": 50, "timestamp": "2026-09-20T00:00:00.000Z"})  # older day, new
    routes = fixture_routes()
    routes[f"/islands/{CODE}/metrics"] = later
    client2, _ = fixture_client(routes)
    result = archive(client2, [CODE], tmp_path)[0]
    assert result.added == 1 and result.filled == 1

    rows = read(tmp_path / f"{CODE}.csv")
    assert [r["timestamp"][:10] for r in rows] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    assert rows[0]["plays"] == "50" and rows[0]["peak_ccu"] == ""
    assert rows[1]["peak_ccu"] == "16"
    assert rows[2]["recommendations"] == "2"


def test_archive_skips_unsettled_and_incomplete_days(tmp_path):
    payload = copy.deepcopy(load("fortnite_metrics_0925-4822-4538.json"))
    for day in ("2026-09-23", "2026-09-24"):  # yesterday and (incomplete) today
        payload["plays"].append({"value": 1, "timestamp": f"{day}T00:00:00.000Z"})
    routes = fixture_routes()
    routes[f"/islands/{CODE}/metrics"] = payload

    client, _ = fixture_client(routes)
    archive(client, [CODE], tmp_path / "settle1")
    assert [r["timestamp"][:10] for r in read(tmp_path / "settle1" / f"{CODE}.csv")] == [
        "2026-09-21",
        "2026-09-22",
    ]
    archive(client, [CODE], tmp_path / "settle0", settle_days=0)
    assert read(tmp_path / "settle0" / f"{CODE}.csv")[-1]["timestamp"][:10] == "2026-09-23"
    with pytest.raises(ValueError):
        archive(client, [CODE], tmp_path, settle_days=6)


def test_archive_continues_after_a_failing_code(tmp_path):
    client, _ = fixture_client()
    results = archive(client, ["1111-2222-3333", CODE], tmp_path)
    assert results[0].error and "404" in results[0].error
    assert results[1].error is None
    assert not (tmp_path / "1111-2222-3333.csv").exists()
    assert (tmp_path / f"{CODE}.csv").exists()


def test_merge_rows_directly():
    existing = [
        {"timestamp": "2026-09-22T00:00:00.000Z", "plays": "", "peak_ccu": "4"},
    ]
    fetched = [
        DailyMetrics("2026-09-22T00:00:00.000Z", plays=7, peak_ccu=5),
        DailyMetrics("2026-09-21T00:00:00.000Z", plays=3),
    ]
    rows, added, filled = merge_rows(existing, fetched)
    assert (added, filled) == (1, 1)
    assert [r["timestamp"][:10] for r in rows] == ["2026-09-21", "2026-09-22"]
    assert rows[1]["plays"] == "7" and rows[1]["peak_ccu"] == "4"
    assert set(rows[0]) == set(CSV_COLUMNS)


def test_read_codes(tmp_path):
    path = tmp_path / "codes.txt"
    path.write_text("# my islands\n\n0925-4822-4538  # war tycoon\n1321-3263-2308\n0925-4822-4538\n")
    assert read_codes(path) == ["0925-4822-4538", "1321-3263-2308"]
    path.write_text("0925-4822-4538\n12345\n")
    with pytest.raises(InvalidIslandCode, match="codes.txt:2"):
        read_codes(path)


def test_repo_tracked_txt_has_the_three_example_codes():
    from pathlib import Path

    tracked = Path(__file__).resolve().parent.parent / "tracked.txt"
    assert read_codes(tracked) == ["0925-4822-4538", "1321-3263-2308", "9752-7254-5801"]
