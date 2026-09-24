"""A fake urllib opener that serves the captured API responses in tests/fixtures/.

Used by the test suite and to produce the example output in the README.
"""

from __future__ import annotations

import datetime as dt
import email.message
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Callable, Union

from islandpulse import Client

FIXTURES = Path(__file__).parent / "fixtures"

#: The captured metrics cover 2026-09-21 and 2026-09-22; pin "now" after them.
FIXED_NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse(io.BytesIO):
    status = 200


def http_error(url: str, status: int, headers: dict | None = None, body: str = "") -> urllib.error.HTTPError:
    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(url, status, "error", msg, io.BytesIO(body.encode()))


Handler = Union[dict, list, Exception, Callable[[urllib.parse.ParseResult], object]]


class FakeOpener:
    """Maps a URL path to a response: a JSON-able object, an exception to raise,
    or a callable taking the parsed URL.

    A key ``"queue:<path>"`` holds a list of responses served in order; its
    last entry is reused once the others are consumed. Unknown paths answer
    HTTP 404. Every request is recorded in ``self.requests``.
    """

    def __init__(self, routes: dict[str, Union[Handler, list[Handler]]]) -> None:
        self.routes = dict(routes)
        self.requests: list = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        parsed = urllib.parse.urlparse(request.full_url)
        path = parsed.path.split("/ecosystem/v1", 1)[-1]
        queued = self.routes.get("queue:" + path)
        if queued is not None:
            handler = queued.pop(0) if len(queued) > 1 else queued[0]
        elif path in self.routes:
            handler = self.routes[path]
        else:
            raise http_error(request.full_url, 404, body='{"message":"not found"}')
        if callable(handler):
            handler = handler(parsed)
        if isinstance(handler, Exception):
            raise handler
        return FakeResponse(json.dumps(handler).encode("utf-8"))


def fixture_routes() -> dict:
    """Routes for the three captured responses."""
    return {
        "/islands": load("fortnite_islands_page.json"),
        "/islands/0925-4822-4538": load("fortnite_island_0925-4822-4538.json"),
        "/islands/0925-4822-4538/metrics": load("fortnite_metrics_0925-4822-4538.json"),
    }


def fixture_client(routes: dict | None = None, now: dt.datetime = FIXED_NOW) -> tuple[Client, FakeOpener]:
    opener = FakeOpener(routes if routes is not None else fixture_routes())
    return Client(opener=opener, clock=lambda: now, backoff=0.01), opener
