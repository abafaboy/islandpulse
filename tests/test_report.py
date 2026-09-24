import re

from fakes import fixture_client

from islandpulse.archive import archive
from islandpulse.report import load_archive, render_report, sparkline, write_report

CODE = "0925-4822-4538"
HEADER = (
    "timestamp,unique_players,plays,minutes_played,average_minutes_per_player,"
    "peak_ccu,favorites,recommendations,retention_d1,retention_d7\n"
)


def make_archive(tmp_path):
    client, _ = fixture_client()
    archive(client, [CODE], tmp_path)
    # A second island with a gap, a null and HTML-looking metadata.
    (tmp_path / "1111-2222-3333.csv").write_text(
        HEADER
        + "2026-09-10T00:00:00.000Z,500,,,,40,,,,0.1\n"
        + "2026-09-11T00:00:00.000Z,700,,,,,,,,0.12\n"
        + "2026-09-14T00:00:00.000Z,650,,,,55,,,,\n"
    )
    with (tmp_path / "islands.csv").open("a") as fh:
        fh.write('1111-2222-3333,<b>Evil</b> & co,maker,FNC,a;b\n')
        fh.write("2222-3333-4444,Tracked but empty,,UEFN,\n")
    (tmp_path / "notes.csv").write_text("ignored\n")
    return tmp_path


def test_report_contains_every_island(tmp_path):
    html = render_report(make_archive(tmp_path))
    for text in (CODE, "WAR TYCOON 3 💣", "1111-2222-3333", "2222-3333-4444", "Tracked but empty"):
        assert text in html
    assert "&lt;b&gt;Evil&lt;/b&gt; &amp; co" in html and "<b>Evil" not in html
    assert html.count('<svg class="spark"') == 6  # 3 tiles x 2 islands with data
    assert "No days archived yet" in html
    assert "Daily snapshots from 2026-09-10 to 2026-09-22" in html
    assert "Not affiliated with or endorsed by Epic Games" in html


def test_report_is_self_contained(tmp_path):
    html = render_report(make_archive(tmp_path))
    assert "<script" not in html and "<link" not in html
    assert not re.search(r'src="https?:', html)
    assert "prefers-color-scheme:dark" in html
    assert 'name="viewport"' in html


def test_islands_sorted_by_latest_players(tmp_path):
    codes = [s.code for s in load_archive(make_archive(tmp_path))]
    assert codes == ["1111-2222-3333", CODE, "2222-3333-4444"]


def test_latest_skips_nulls(tmp_path):
    series = {s.code: s for s in load_archive(make_archive(tmp_path))}
    assert series["1111-2222-3333"].latest("retention_d7") == (0.12, "2026-09-11")
    assert series["2222-3333-4444"].latest("plays") == (None, None)


def test_sparkline_breaks_on_gaps_and_nulls():
    rows = [
        {"timestamp": "2026-09-10T00:00:00.000Z", "plays": "1"},
        {"timestamp": "2026-09-11T00:00:00.000Z", "plays": "2"},
        {"timestamp": "2026-09-12T00:00:00.000Z", "plays": ""},
        {"timestamp": "2026-09-13T00:00:00.000Z", "plays": "3"},
        {"timestamp": "2026-09-15T00:00:00.000Z", "plays": "4"},
    ]
    svg = sparkline(rows, "plays", "count")
    assert svg.count('<path class="line"') == 1  # 10-11
    assert svg.count('<circle class="pt"') == 2  # 13 and 15 are isolated
    assert svg.count("<title>") == 4
    assert "No values yet" in sparkline(rows[2:3], "plays", "count")


def test_write_report_creates_parent_dirs(tmp_path):
    out = write_report(make_archive(tmp_path / "data"), tmp_path / "site" / "index.html")
    assert out.read_text().startswith("<!doctype html>")


def test_empty_archive(tmp_path):
    html = render_report(tmp_path)
    assert "No islands tracked yet" in html and "No days archived yet." in html
