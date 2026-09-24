import datetime as dt

from fakes import load

from islandpulse import DailyMetrics, Island, IslandPage, merge_metrics


def test_island_detail_fixture():
    isl = Island.from_api(load("fortnite_island_0925-4822-4538.json"))
    assert isl == Island(
        code="0925-4822-4538",
        title="WAR TYCOON 3 💣",
        creator_code="notales",
        created_in="UEFN",
        tags=("casual", "tycoon", "simulator", "pvp"),
    )


def test_islands_page_fixture():
    page = IslandPage.from_api(load("fortnite_islands_page.json"))
    assert [i.code for i in page.islands] == ["1321-3263-2308", "9752-7254-5801"]
    assert page.islands[1].created_in == "FNC"
    assert page.islands[0].title == "BRAINROT PILLARS ⭐ (REBIRTH SYSTEM)"
    assert page.next_cursor == "OTc1Mi03MjU0LTU4MDE="


def test_islands_page_without_cursor_or_data():
    page = IslandPage.from_api({"links": {"next": None}, "meta": {"page": {"nextCursor": None}}})
    assert page.islands == [] and page.next_cursor is None


def test_island_missing_optional_fields():
    isl = Island.from_api({"code": "1111-2222-3333", "title": None, "tags": None})
    assert isl.title == "" and isl.tags == () and isl.creator_code == ""


def test_metrics_fixture_merged_per_timestamp_with_nulls():
    rows = merge_metrics(load("fortnite_metrics_0925-4822-4538.json"))
    assert [r.timestamp for r in rows] == ["2026-09-21T00:00:00.000Z", "2026-09-22T00:00:00.000Z"]
    first, second = rows
    assert first == DailyMetrics(
        timestamp="2026-09-21T00:00:00.000Z",
        unique_players=88,
        plays=116,
        minutes_played=3363,
        average_minutes_per_player=38.22,
        peak_ccu=16,
        favorites=8,
        recommendations=1,
        retention_d1=0.15,
        retention_d7=0.06,
    )
    assert second.recommendations is None  # null in the captured response
    assert second.peak_ccu == 6 and second.retention_d7 == 0.02
    assert second.date == dt.date(2026, 9, 22)


def test_metrics_series_of_different_lengths_and_missing_keys():
    rows = merge_metrics(
        {
            "plays": [
                {"value": 5, "timestamp": "2026-09-22T00:00:00.000Z"},
                {"value": 3, "timestamp": "2026-09-21T00:00:00.000Z"},
            ],
            "peakCCU": [{"value": None, "timestamp": "2026-09-22T00:00:00.000Z"}],
            "retention": [{"d1": None, "d7": None, "timestamp": "2026-09-20T00:00:00.000Z"}],
        }
    )
    assert [r.timestamp[:10] for r in rows] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    assert rows[0].plays is None and rows[0].retention_d1 is None
    assert rows[2].plays == 5 and rows[2].peak_ccu is None
    assert merge_metrics({}) == []


def test_columns_order_is_stable():
    assert DailyMetrics.columns() == [
        "timestamp",
        "unique_players",
        "plays",
        "minutes_played",
        "average_minutes_per_player",
        "peak_ccu",
        "favorites",
        "recommendations",
        "retention_d1",
        "retention_d7",
    ]
