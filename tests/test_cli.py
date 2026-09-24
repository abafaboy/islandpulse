import csv
import io
import json
import urllib.parse

import pytest
from fakes import fixture_client

from islandpulse.cli import main

CODE = "0925-4822-4538"


def run(argv, capsys, client=None):
    if client is None:
        client, _ = fixture_client()
    code = main(argv, client=client)
    out, err = capsys.readouterr()
    return code, out, err


def test_island_table(capsys):
    code, out, _ = run(["island", CODE], capsys)
    assert code == 0
    assert "title:      WAR TYCOON 3 💣" in out and "tags:       casual, tycoon, simulator, pvp" in out


def test_island_json(capsys):
    _, out, _ = run(["island", CODE, "--format", "json"], capsys)
    assert json.loads(out)["creator_code"] == "notales"


def test_island_invalid_code(capsys):
    code, _, err = run(["island", "12-34"], capsys)
    assert code == 1 and "invalid island code" in err


def test_island_not_found(capsys):
    code, _, err = run(["island", "1111-2222-3333"], capsys)
    assert code == 1 and "HTTP 404" in err


def test_metrics_table(capsys):
    code, out, _ = run(["metrics", CODE], capsys)
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["day", "players", "plays", "peak", "minutes", "avg", "min", "favs", "recs", "d1", "d7"]
    assert lines[2].split() == ["2026-09-21", "88", "116", "16", "3363", "38.22", "8", "1", "0.15", "0.06"]
    assert lines[3].split()[7] == "-"  # null recommendations


def test_metrics_csv_and_days(capsys):
    client, opener = fixture_client()
    _, out, _ = run(["metrics", CODE, "--days", "3", "--format", "csv"], capsys, client)
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[1]["recommendations"] == "" and rows[0]["retention_d7"] == "0.06"
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(opener.requests[0].full_url).query))
    assert params == {"from": "2026-09-21T00:00:00.000Z", "to": "2026-09-24T00:00:00.000Z"}


def test_metrics_json_and_interval(capsys):
    client, opener = fixture_client()
    _, out, _ = run(["metrics", CODE, "--format", "json", "--interval", "day"], capsys, client)
    assert json.loads(out)[1]["recommendations"] is None
    assert "interval=day" in opener.requests[0].full_url


def test_metrics_days_out_of_range(capsys):
    with pytest.raises(SystemExit) as info:
        main(["metrics", CODE, "--days", "7"])
    assert info.value.code == 2


@pytest.mark.parametrize("fmt", ["table", "csv", "json"])
def test_new(capsys, fmt):
    client, opener = fixture_client()
    code, out, _ = run(["new", "--pages", "1", "--size", "2", "--format", fmt], capsys, client)
    assert code == 0 and "1321-3263-2308" in out and "9752-7254-5801" in out
    assert len(opener.requests) == 1 and "size=2" in opener.requests[0].full_url


def test_archive_and_report(tmp_path, capsys):
    codes = tmp_path / "codes.txt"
    codes.write_text(f"# test\n{CODE}\n1111-2222-3333\n")
    data = tmp_path / "data"
    code, out, err = run(["archive", "--codes", str(codes), "--out", str(data)], capsys)
    assert code == 0
    assert f"{CODE}: +2 rows, 0 cells filled" in out
    assert "1111-2222-3333: FAILED" in err

    code, out, _ = run(["archive", "--codes", str(codes), "--out", str(data), "--settle-days", "0"], capsys)
    assert f"{CODE}: +0 rows, 0 cells filled" in out

    site = tmp_path / "site" / "index.html"
    code, out, _ = run(["report", "--data", str(data), "--out", str(site)], capsys)
    assert code == 0 and "WAR TYCOON 3" in site.read_text()


def test_archive_all_fail_exits_nonzero(tmp_path, capsys):
    codes = tmp_path / "codes.txt"
    codes.write_text("1111-2222-3333\n")
    code, _, _ = run(["archive", "--codes", str(codes), "--out", str(tmp_path / "d")], capsys)
    assert code == 1


def test_archive_bad_codes_file(tmp_path, capsys):
    codes = tmp_path / "codes.txt"
    codes.write_text("nope\n")
    code, _, err = run(["archive", "--codes", str(codes), "--out", str(tmp_path)], capsys)
    assert code == 1 and "codes.txt:1" in err
    code, _, err = run(["archive", "--codes", str(tmp_path / "missing.txt"), "--out", str(tmp_path)], capsys)
    assert code == 1 and "error:" in err


def test_global_options_build_client(monkeypatch, capsys):
    import islandpulse.cli as cli

    seen = {}

    class Recorder:
        def __init__(self, base_url, timeout):
            seen.update(base_url=base_url, timeout=timeout)

        def island(self, code):
            from islandpulse import Island

            return Island(code=code)

    monkeypatch.setattr(cli, "Client", Recorder)
    assert main(["--base-url", "https://example.test/v1", "--timeout", "5", "island", CODE]) == 0
    assert seen == {"base_url": "https://example.test/v1", "timeout": 5.0}


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "islandpulse 0.1.0" in capsys.readouterr().out
