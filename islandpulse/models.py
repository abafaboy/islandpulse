"""Typed records built from Fortnite Data API responses."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, fields
from typing import Any, Optional

Number = Optional[float]

# API key -> DailyMetrics attribute, in the column order used for CSV output.
METRIC_KEYS: dict[str, str] = {
    "uniquePlayers": "unique_players",
    "plays": "plays",
    "minutesPlayed": "minutes_played",
    "averageMinutesPerPlayer": "average_minutes_per_player",
    "peakCCU": "peak_ccu",
    "favorites": "favorites",
    "recommendations": "recommendations",
}


@dataclass(frozen=True)
class Island:
    """One island as returned by ``/islands`` or ``/islands/{code}``."""

    code: str
    title: str = ""
    creator_code: str = ""
    created_in: str = ""  # "UEFN" or "FNC" in observed responses
    tags: tuple[str, ...] = ()

    @classmethod
    def from_api(cls, obj: dict[str, Any]) -> "Island":
        return cls(
            code=obj["code"],
            title=obj.get("title") or "",
            creator_code=obj.get("creatorCode") or "",
            created_in=obj.get("createdIn") or "",
            tags=tuple(obj.get("tags") or ()),
        )


@dataclass
class DailyMetrics:
    """All metrics for one time bucket (one UTC day unless ``interval`` is set).

    Any field can be ``None``: the API returns ``null`` for buckets it has no
    value for (for example, days with too few players).
    """

    timestamp: str
    unique_players: Number = None
    plays: Number = None
    minutes_played: Number = None
    average_minutes_per_player: Number = None
    peak_ccu: Number = None
    favorites: Number = None
    recommendations: Number = None
    retention_d1: Number = None
    retention_d7: Number = None

    @property
    def date(self) -> _dt.date:
        """The UTC calendar date of the bucket."""
        return _dt.date.fromisoformat(self.timestamp[:10])

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.columns()}


def merge_metrics(payload: dict[str, Any]) -> list[DailyMetrics]:
    """Merge the per-metric series of a ``/metrics`` response into rows.

    The API returns one list per metric (``{"peakCCU": [{"value", "timestamp"}]}``)
    plus ``retention`` as ``[{"d1", "d7", "timestamp"}]``. This joins them on
    timestamp and returns rows sorted oldest first.
    """
    rows: dict[str, DailyMetrics] = {}

    def row(ts: str) -> DailyMetrics:
        if ts not in rows:
            rows[ts] = DailyMetrics(timestamp=ts)
        return rows[ts]

    for api_key, attr in METRIC_KEYS.items():
        for point in payload.get(api_key) or ():
            setattr(row(point["timestamp"]), attr, point.get("value"))
    for point in payload.get("retention") or ():
        r = row(point["timestamp"])
        r.retention_d1 = point.get("d1")
        r.retention_d7 = point.get("d7")
    return [rows[ts] for ts in sorted(rows)]


@dataclass
class IslandPage:
    """One page of the ``/islands`` firehose."""

    islands: list[Island] = field(default_factory=list)
    next_cursor: Optional[str] = None

    @classmethod
    def from_api(cls, obj: dict[str, Any]) -> "IslandPage":
        page = (obj.get("meta") or {}).get("page") or {}
        return cls(
            islands=[Island.from_api(item) for item in obj.get("data") or ()],
            next_cursor=page.get("nextCursor") or None,
        )
