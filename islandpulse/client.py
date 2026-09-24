"""HTTP client for Epic's public Fortnite Data API (stdlib only)."""

from __future__ import annotations

import datetime as _dt
import email.utils
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator, Optional, Union

from . import __version__
from .errors import (
    APIError,
    InvalidIslandCode,
    LookbackError,
    NotFoundError,
    RateLimitError,
    TimestampFormatError,
    TransportError,
)
from .models import DailyMetrics, Island, IslandPage, merge_metrics

DEFAULT_BASE_URL = "https://api.fortnite.com/ecosystem/v1"
USER_AGENT = f"islandpulse/{__version__} (+https://github.com/abafaboy/islandpulse)"

#: The API refuses a ``from`` older than this (HTTP 400).
MAX_LOOKBACK = _dt.timedelta(days=7)

ISLAND_CODE_RE = re.compile(r"^\d{4}-\d{4}-\d{4}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

TimeLike = Union[_dt.datetime, _dt.date, str]


def validate_code(code: str) -> str:
    """Return ``code`` stripped, or raise :class:`InvalidIslandCode`."""
    code = (code or "").strip()
    if not ISLAND_CODE_RE.match(code):
        raise InvalidIslandCode(
            f"invalid island code {code!r}: expected the form 1234-5678-9012"
        )
    return code


def to_datetime(value: TimeLike) -> _dt.datetime:
    """Normalise a datetime, date or API timestamp string to an aware UTC datetime.

    * naive datetimes are taken to be UTC;
    * a ``date`` means midnight UTC of that day;
    * strings must already be in the exact form the API accepts
      (``2026-09-21T00:00:00.000Z``), otherwise :class:`TimestampFormatError`.
    """
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc)
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day, tzinfo=_dt.timezone.utc)
    if isinstance(value, str):
        if not TIMESTAMP_RE.match(value):
            raise TimestampFormatError(
                f"timestamp {value!r} is not accepted by the API; use full ISO 8601 "
                "with milliseconds and a trailing Z, e.g. 2026-09-21T00:00:00.000Z"
            )
        return _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=_dt.timezone.utc
        )
    raise TypeError(f"expected datetime, date or str, got {type(value).__name__}")


def format_timestamp(value: TimeLike) -> str:
    """Format a time the only way the API accepts: ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    dt = to_datetime(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def last_complete_days(
    days: int, now: Optional[_dt.datetime] = None
) -> tuple[_dt.datetime, _dt.datetime]:
    """Return ``(start, end)`` covering the last ``days`` complete UTC days.

    ``end`` is today's midnight UTC. Because the API only looks back 7 days
    from *now*, at most 6 complete days fit in the window.
    """
    if not 1 <= days <= 6:
        raise ValueError("days must be between 1 and 6 (the API keeps 7 days from now)")
    now = to_datetime(now) if now is not None else _dt.datetime.now(_dt.timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return end - _dt.timedelta(days=days), end


def _retry_after_seconds(value: Optional[str], now: _dt.datetime) -> Optional[float]:
    """Parse a Retry-After header: delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    return max(0.0, (when - now).total_seconds())


class Client:
    """Client for ``https://api.fortnite.com/ecosystem/v1``.

    No authentication is needed. Requests that the API is known to reject
    (bad island code, ``start`` older than 7 days, badly formatted timestamp)
    raise before anything is sent.

    :param base_url: API root.
    :param timeout: per-request socket timeout in seconds.
    :param max_retries: retries on 429, 5xx and network errors (0 disables).
    :param backoff: first retry delay in seconds; doubles each attempt, capped
        at ``max_backoff``. A ``Retry-After`` header takes precedence.
    :param opener: anything with ``open(request, timeout=...)`` returning a
        response (default ``urllib.request.build_opener()``). Inject a fake here
        in tests.
    :param clock: returns the current time as an aware UTC datetime; used for
        the 7-day guard.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        max_retries: int = 4,
        backoff: float = 1.0,
        max_backoff: float = 60.0,
        user_agent: str = USER_AGENT,
        opener: Any = None,
        clock: Optional[Callable[[], _dt.datetime]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.user_agent = user_agent
        self._opener = opener if opener is not None else urllib.request.build_opener()
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))

    def now(self) -> _dt.datetime:
        """Current time according to this client's clock (aware, UTC)."""
        return to_datetime(self._clock())

    # -- transport ---------------------------------------------------------

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        # Keep ':' literal so timestamps go out exactly as the API documents them.
        query = urllib.parse.urlencode(
            {k: v for k, v in (params or {}).items() if v is not None}, safe=":"
        )
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        attempt = 0
        while True:
            retry_after: Optional[float] = None
            try:
                with self._opener.open(request, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace") if exc.fp else ""
                status = exc.code
                if status not in RETRY_STATUSES or attempt >= self.max_retries:
                    if status == 404:
                        raise NotFoundError(status, url, body) from None
                    if status == 429:
                        raise RateLimitError(status, url, body) from None
                    raise APIError(status, url, body) from None
                retry_after = _retry_after_seconds(exc.headers.get("Retry-After"), self.now())
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= self.max_retries:
                    reason = getattr(exc, "reason", exc)
                    raise TransportError(f"request to {url} failed: {reason}") from exc
            delay = min(self.backoff * (2**attempt), self.max_backoff)
            if retry_after is not None:
                delay = min(retry_after, self.max_backoff)
            time.sleep(delay)
            attempt += 1

    # -- endpoints ---------------------------------------------------------

    def islands_page(self, *, size: int = 50, after: Optional[str] = None) -> IslandPage:
        """Fetch one page of ``GET /islands`` (newest islands first, not a ranking)."""
        return IslandPage.from_api(self._get("/islands", {"size": size, "after": after}))

    def iter_islands(
        self,
        *,
        size: int = 50,
        max_pages: Optional[int] = None,
        after: Optional[str] = None,
    ) -> Iterator[Island]:
        """Yield islands from the ``/islands`` firehose, following cursors.

        Stops when a page has no ``nextCursor``, a page is empty, or
        ``max_pages`` pages have been read.
        """
        pages = 0
        cursor = after
        while max_pages is None or pages < max_pages:
            page = self.islands_page(size=size, after=cursor)
            pages += 1
            yield from page.islands
            if not page.islands or not page.next_cursor:
                return
            cursor = page.next_cursor

    def island(self, code: str) -> Island:
        """Fetch ``GET /islands/{code}``."""
        code = validate_code(code)
        return Island.from_api(self._get(f"/islands/{code}"))

    def metrics(
        self,
        code: str,
        start: TimeLike,
        end: TimeLike,
        *,
        interval: Optional[str] = None,
    ) -> list[DailyMetrics]:
        """Fetch ``GET /islands/{code}/metrics`` and merge it into rows per timestamp.

        :param start: first bucket; must be within the last 7 days.
        :param end: last bucket.
        :param interval: **unverified, advanced.** Sent as-is as an
            ``interval`` query parameter. Epic documents ten-minute, hour and
            day granularity but the parameter name is not confirmed; leave it
            ``None`` to get the API default, which is daily.
        """
        code = validate_code(code)
        start_dt, end_dt = to_datetime(start), to_datetime(end)
        oldest = self.now() - MAX_LOOKBACK
        if start_dt < oldest:
            raise LookbackError(
                f"start {format_timestamp(start_dt)} is older than 7 days; the API only "
                f"serves data from {format_timestamp(oldest)} onwards"
            )
        if end_dt < start_dt:
            raise ValueError("end must not be before start")
        payload = self._get(
            f"/islands/{code}/metrics",
            {
                "from": format_timestamp(start_dt),
                "to": format_timestamp(end_dt),
                "interval": interval,
            },
        )
        return merge_metrics(payload)
