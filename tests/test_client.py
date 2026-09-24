import datetime as dt
import urllib.error
import urllib.parse

import pytest
from fakes import FIXED_NOW, fixture_client, http_error, load

import islandpulse
from islandpulse import (
    APIError,
    Client,
    InvalidIslandCode,
    LookbackError,
    NotFoundError,
    RateLimitError,
    TimestampFormatError,
    TransportError,
    format_timestamp,
    last_complete_days,
    validate_code,
)

UTC = dt.timezone.utc
CODE = "0925-4822-4538"


def query(request) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(request.full_url).query))


# -- validation and formatting ---------------------------------------------


@pytest.mark.parametrize("code", ["0925-4822-4538", " 0925-4822-4538\n"])
def test_validate_code_ok(code):
    assert validate_code(code) == "0925-4822-4538"


@pytest.mark.parametrize("code", ["", "0925-4822-453", "0925_4822_4538", "abcd-4822-4538", "09254822-4538"])
def test_validate_code_rejects(code):
    with pytest.raises(InvalidIslandCode):
        validate_code(code)


def test_invalid_code_raises_before_request():
    client, opener = fixture_client()
    with pytest.raises(InvalidIslandCode):
        client.island("not-a-code")
    with pytest.raises(ValueError):  # InvalidIslandCode is also a ValueError
        client.metrics("123", FIXED_NOW - dt.timedelta(days=1), FIXED_NOW)
    assert opener.requests == []


@pytest.mark.parametrize(
    "value, expected",
    [
        (dt.datetime(2026, 9, 21, tzinfo=UTC), "2026-09-21T00:00:00.000Z"),
        (dt.datetime(2026, 9, 21, 13, 5, 7, 123456, tzinfo=UTC), "2026-09-21T13:05:07.123Z"),
        (dt.datetime(2026, 9, 21, 12, 0), "2026-09-21T12:00:00.000Z"),  # naive = UTC
        (dt.datetime(2026, 9, 21, 2, 0, tzinfo=dt.timezone(dt.timedelta(hours=2))), "2026-09-21T00:00:00.000Z"),
        (dt.date(2026, 9, 21), "2026-09-21T00:00:00.000Z"),
        ("2026-09-21T00:00:00.000Z", "2026-09-21T00:00:00.000Z"),
    ],
)
def test_format_timestamp(value, expected):
    assert format_timestamp(value) == expected


@pytest.mark.parametrize(
    "bad", ["2026-09-21", "2026-09-21T00:00:00Z", "2026-09-21T00:00:00.000", "2026-09-21T00:00:00.000+00:00"]
)
def test_bad_timestamp_string_raises_before_request(bad):
    client, opener = fixture_client()
    with pytest.raises(TimestampFormatError):
        client.metrics(CODE, bad, "2026-09-23T00:00:00.000Z")
    assert opener.requests == []


def test_format_timestamp_rejects_other_types():
    with pytest.raises(TypeError):
        format_timestamp(1695254400)


def test_last_complete_days():
    start, end = last_complete_days(6, FIXED_NOW)
    assert end == dt.datetime(2026, 9, 24, tzinfo=UTC)
    assert start == dt.datetime(2026, 9, 18, tzinfo=UTC)
    assert FIXED_NOW - start < islandpulse.MAX_LOOKBACK
    for bad in (0, 7):
        with pytest.raises(ValueError):
            last_complete_days(bad, FIXED_NOW)


def test_last_complete_days_defaults_to_real_now():
    start, end = last_complete_days(1)
    assert end - start == dt.timedelta(days=1)
    assert end.tzinfo is not None


# -- endpoints ---------------------------------------------------------------


def test_island_request_and_user_agent():
    client, opener = fixture_client()
    isl = client.island(CODE)
    assert isl.title == "WAR TYCOON 3 💣"
    req = opener.requests[0]
    assert req.full_url == f"https://api.fortnite.com/ecosystem/v1/islands/{CODE}"
    assert req.get_header("User-agent") == (
        f"islandpulse/{islandpulse.__version__} (+https://github.com/abafaboy/islandpulse)"
    )


def test_base_url_trailing_slash():
    _, opener = fixture_client()
    client = Client("https://example.test/ecosystem/v1/", opener=opener)
    client.island(CODE)
    assert opener.requests[0].full_url.startswith("https://example.test/ecosystem/v1/islands/")


def test_metrics_request_and_parse():
    client, opener = fixture_client()
    start, end = last_complete_days(6, FIXED_NOW)
    rows = client.metrics(CODE, start, end)
    assert len(rows) == 2 and rows[1].recommendations is None
    req = opener.requests[0]
    # Colons stay literal, exactly the format the API accepts.
    assert "from=2026-09-18T00:00:00.000Z&to=2026-09-24T00:00:00.000Z" in req.full_url
    assert "interval" not in query(req)


def test_metrics_accepts_api_timestamp_strings():
    client, opener = fixture_client()
    client.metrics(CODE, "2026-09-21T00:00:00.000Z", "2026-09-23T00:00:00.000Z")
    assert query(opener.requests[0])["from"] == "2026-09-21T00:00:00.000Z"


def test_metrics_interval_passthrough():
    client, opener = fixture_client()
    client.metrics(CODE, FIXED_NOW - dt.timedelta(days=1), FIXED_NOW, interval="hour")
    assert query(opener.requests[0])["interval"] == "hour"


def test_seven_day_guard_raises_before_request():
    client, opener = fixture_client()
    too_old = FIXED_NOW - dt.timedelta(days=7, seconds=1)
    with pytest.raises(LookbackError, match="older than 7 days"):
        client.metrics(CODE, too_old, FIXED_NOW)
    assert opener.requests == []
    # Just inside the window is fine.
    client.metrics(CODE, FIXED_NOW - dt.timedelta(days=7), FIXED_NOW)
    assert len(opener.requests) == 1


def test_end_before_start_rejected():
    client, opener = fixture_client()
    with pytest.raises(ValueError):
        client.metrics(CODE, FIXED_NOW, FIXED_NOW - dt.timedelta(days=1))
    assert opener.requests == []


def test_client_now_uses_clock():
    client, _ = fixture_client()
    assert client.now() == FIXED_NOW
    assert Client().now().tzinfo is not None


# -- pagination ----------------------------------------------------------------


def two_pages():
    page1 = load("fortnite_islands_page.json")
    page2 = {
        "links": {"next": None, "prev": None},
        "meta": {"count": 1, "page": {"nextCursor": None, "prevCursor": "x"}},
        "data": [{"code": "1111-2222-3333", "title": "Last", "createdIn": "UEFN", "tags": []}],
    }

    def route(parsed):
        params = dict(urllib.parse.parse_qsl(parsed.query))
        return page2 if params.get("after") == "OTc1Mi03MjU0LTU4MDE=" else page1

    return {"/islands": route}


def test_iter_islands_follows_cursor_across_two_pages():
    client, opener = fixture_client(two_pages())
    codes = [i.code for i in client.iter_islands(size=2)]
    assert codes == ["1321-3263-2308", "9752-7254-5801", "1111-2222-3333"]
    assert len(opener.requests) == 2
    assert query(opener.requests[0]) == {"size": "2"}
    assert query(opener.requests[1]) == {"size": "2", "after": "OTc1Mi03MjU0LTU4MDE="}
    assert "after=OTc1Mi03MjU0LTU4MDE%3D" in opener.requests[1].full_url


def test_iter_islands_max_pages():
    client, opener = fixture_client(two_pages())
    assert len(list(client.iter_islands(size=2, max_pages=1))) == 2
    assert len(opener.requests) == 1


def test_iter_islands_stops_on_empty_page():
    empty = {"meta": {"page": {"nextCursor": "still-here"}}, "data": []}
    client, opener = fixture_client({"/islands": empty})
    assert list(client.iter_islands()) == []
    assert len(opener.requests) == 1


def test_iter_islands_start_cursor():
    client, opener = fixture_client(two_pages())
    assert [i.code for i in client.iter_islands(after="OTc1Mi03MjU0LTU4MDE=")] == ["1111-2222-3333"]


# -- errors and retries -----------------------------------------------------------


def test_retry_on_429_honours_retry_after(sleeps):
    url = "https://api.fortnite.com/ecosystem/v1/islands/" + CODE
    routes = {
        f"queue:/islands/{CODE}": [
            http_error(url, 429, {"Retry-After": "3"}),
            load("fortnite_island_0925-4822-4538.json"),
        ]
    }
    client, opener = fixture_client(routes)
    assert client.island(CODE).code == CODE
    assert sleeps == [3.0]
    assert len(opener.requests) == 2


def test_retry_after_http_date(sleeps):
    url = "https://api.fortnite.com/ecosystem/v1/islands/" + CODE
    when = "Thu, 24 Sep 2026 12:00:10 GMT"  # 10 s after FIXED_NOW
    routes = {
        f"queue:/islands/{CODE}": [
            http_error(url, 429, {"Retry-After": when}),
            load("fortnite_island_0925-4822-4538.json"),
        ]
    }
    client, _ = fixture_client(routes)
    client.island(CODE)
    assert sleeps == [10.0]


def test_exponential_backoff_on_5xx_then_success(sleeps):
    url = "https://x/islands/" + CODE
    routes = {
        f"queue:/islands/{CODE}": [
            http_error(url, 503),
            http_error(url, 502, {"Retry-After": "garbage"}),
            http_error(url, 500),
            load("fortnite_island_0925-4822-4538.json"),
        ]
    }
    client, _ = fixture_client(routes)
    client.backoff = 1.0
    client.island(CODE)
    assert sleeps == [1.0, 2.0, 4.0]


def test_backoff_is_capped(sleeps):
    url = "https://x/islands/" + CODE
    routes = {f"queue:/islands/{CODE}": [http_error(url, 429, {"Retry-After": "3600"}), {"code": CODE}]}
    client, _ = fixture_client(routes)
    client.island(CODE)
    assert sleeps == [60.0]


def test_rate_limit_error_after_retries(sleeps):
    url = "https://x/islands/" + CODE
    client, opener = fixture_client({f"/islands/{CODE}": http_error(url, 429)})
    client.max_retries = 2
    with pytest.raises(RateLimitError) as info:
        client.island(CODE)
    assert info.value.status == 429
    assert len(opener.requests) == 3 and len(sleeps) == 2


def test_400_is_not_retried(sleeps):
    url = "https://x/islands/" + CODE
    client, opener = fixture_client({f"/islands/{CODE}": http_error(url, 400, body='{"error":"bad from"}')})
    with pytest.raises(APIError, match="HTTP 400.*bad from"):
        client.island(CODE)
    assert len(opener.requests) == 1 and sleeps == []


def test_404_raises_not_found(sleeps):
    client, _ = fixture_client({})
    with pytest.raises(NotFoundError):
        client.island("1111-2222-3333")
    assert sleeps == []


def test_network_errors_retry_then_raise(sleeps):
    client, opener = fixture_client({f"/islands/{CODE}": urllib.error.URLError("dns failure")})
    client.max_retries = 1
    with pytest.raises(TransportError, match="dns failure"):
        client.island(CODE)
    assert len(opener.requests) == 2 and len(sleeps) == 1


def test_timeout_is_passed_to_opener():
    seen = {}

    class Opener:
        def open(self, request, timeout=None):
            seen["timeout"] = timeout
            raise TimeoutError("slow")

    client = Client(opener=Opener(), timeout=7.5, max_retries=0)
    with pytest.raises(TransportError):
        client.island(CODE)
    assert seen["timeout"] == 7.5
