"""islandpulse: a stdlib-only client, CLI and daily archiver for Epic's Fortnite Data API."""

__version__ = "0.1.0"

from .client import (  # noqa: E402
    DEFAULT_BASE_URL,
    MAX_LOOKBACK,
    Client,
    format_timestamp,
    last_complete_days,
    validate_code,
)
from .errors import (  # noqa: E402
    APIError,
    InvalidIslandCode,
    IslandPulseError,
    LookbackError,
    NotFoundError,
    RateLimitError,
    TimestampFormatError,
    TransportError,
)
from .models import DailyMetrics, Island, IslandPage, merge_metrics  # noqa: E402

__all__ = [
    "__version__",
    "APIError",
    "Client",
    "DailyMetrics",
    "DEFAULT_BASE_URL",
    "InvalidIslandCode",
    "Island",
    "IslandPage",
    "IslandPulseError",
    "LookbackError",
    "MAX_LOOKBACK",
    "NotFoundError",
    "RateLimitError",
    "TimestampFormatError",
    "TransportError",
    "format_timestamp",
    "last_complete_days",
    "merge_metrics",
    "validate_code",
]
