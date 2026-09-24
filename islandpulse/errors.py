"""Exceptions raised by islandpulse."""

from __future__ import annotations


class IslandPulseError(Exception):
    """Base class for every error raised by islandpulse."""


class InvalidIslandCode(IslandPulseError, ValueError):
    """The island code is not in the ``NNNN-NNNN-NNNN`` form the API expects."""


class LookbackError(IslandPulseError, ValueError):
    """The requested ``start`` is outside the API's 7-day window.

    The API answers HTTP 400 for such requests, so the client refuses them
    before sending anything.
    """


class TimestampFormatError(IslandPulseError, ValueError):
    """A timestamp string is not full ISO 8601 with milliseconds and ``Z``.

    The API only accepts the form ``2026-09-21T00:00:00.000Z``.
    """


class APIError(IslandPulseError):
    """The API answered with a non-success HTTP status."""

    def __init__(self, status: int, url: str, body: str = "") -> None:
        self.status = status
        self.url = url
        self.body = body
        detail = f": {body[:300]}" if body else ""
        super().__init__(f"HTTP {status} from {url}{detail}")


class NotFoundError(APIError):
    """HTTP 404: unknown island, or one that is not public and discoverable."""


class RateLimitError(APIError):
    """HTTP 429 persisted after every retry."""


class TransportError(IslandPulseError):
    """The request never got an HTTP answer (DNS, connection, timeout...)."""
