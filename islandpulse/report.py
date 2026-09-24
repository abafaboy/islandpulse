"""Render the archive as one self-contained HTML page (inline CSS and SVG, no JS)."""

from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Optional

from . import __version__
from .archive import META_FILE
from .client import ISLAND_CODE_RE

#: Number of most recent days drawn in each sparkline.
SPARK_DAYS = 90
#: Number of most recent rows listed in each island's table.
TABLE_ROWS = 30

# (csv column, label, kind) for the three sparkline tiles.
TILES = [
    ("unique_players", "Unique players", "count"),
    ("peak_ccu", "Peak concurrent players", "count"),
    ("retention_d7", "Day-7 retention", "ratio"),
]
TABLE_COLUMNS = [
    ("unique_players", "Players", "count"),
    ("plays", "Plays", "count"),
    ("peak_ccu", "Peak CCU", "count"),
    ("minutes_played", "Minutes", "count"),
    ("average_minutes_per_player", "Avg min", "float"),
    ("favorites", "Favs", "count"),
    ("recommendations", "Recs", "count"),
    ("retention_d1", "D1", "ratio"),
    ("retention_d7", "D7", "ratio"),
]


def _num(text: Optional[str]) -> Optional[float]:
    if text is None or text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt(value: Optional[float], kind: str) -> str:
    if value is None:
        return "–"
    if kind == "ratio":
        return f"{value * 100:.1f}%"
    if kind == "float":
        return f"{value:,.1f}"
    return f"{value:,.0f}"


@dataclass
class IslandSeries:
    code: str
    title: str = ""
    creator_code: str = ""
    created_in: str = ""
    tags: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)

    def latest(self, column: str) -> tuple[Optional[float], Optional[str]]:
        """Most recent non-empty value of ``column`` and its date."""
        for row in reversed(self.rows):
            value = _num(row.get(column))
            if value is not None:
                return value, row["timestamp"][:10]
        return None, None


def load_archive(data_dir: Path) -> list[IslandSeries]:
    """Load ``islands.csv`` and every ``<code>.csv`` in ``data_dir``."""
    data_dir = Path(data_dir)
    series: dict[str, IslandSeries] = {}
    meta_path = data_dir / META_FILE
    if meta_path.exists():
        with meta_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                series[row["code"]] = IslandSeries(
                    code=row["code"],
                    title=row.get("title", ""),
                    creator_code=row.get("creator_code", ""),
                    created_in=row.get("created_in", ""),
                    tags=[t for t in (row.get("tags") or "").split(";") if t],
                )
    for path in sorted(data_dir.glob("*.csv")):
        if not ISLAND_CODE_RE.match(path.stem):
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            rows = sorted(csv.DictReader(fh), key=lambda r: r["timestamp"])
        series.setdefault(path.stem, IslandSeries(code=path.stem)).rows = rows

    def sort_key(s: IslandSeries) -> tuple[int, float, str]:
        players, _ = s.latest("unique_players")
        return (players is None, -(players or 0.0), s.code)

    return sorted(series.values(), key=sort_key)


def sparkline(rows: list[dict[str, str]], column: str, kind: str) -> str:
    """Inline SVG sparkline; gaps for missing days or null values."""
    width, height, pad = 240.0, 56.0, 4.0
    points: list[tuple[_dt.date, Optional[float]]] = [
        (_dt.date.fromisoformat(r["timestamp"][:10]), _num(r.get(column)))
        for r in rows[-SPARK_DAYS:]
    ]
    values = [v for _, v in points if v is not None]
    if not values:
        return '<p class="nodata">No values yet</p>'
    first = points[0][0]
    span = max((points[-1][0] - first).days, 1)
    top = max(values) or 1.0

    def xy(day: _dt.date, value: float) -> tuple[float, float]:
        x = pad + (width - 2 * pad) * (day - first).days / span
        y = height - pad - (height - 2 * pad) * value / top
        return round(x, 1), round(y, 1)

    segments: list[list[tuple[float, float]]] = []
    prev_day: Optional[_dt.date] = None
    for day, value in points:
        if value is None:
            prev_day = None
            continue
        if prev_day is None or (day - prev_day).days > 1:
            segments.append([])
        segments[-1].append(xy(day, value))
        prev_day = day

    parts = [
        f'<svg class="spark" viewBox="0 0 {width:g} {height:g}" role="img" '
        f'aria-label="{escape(column)} over {len(points)} days">',
        f'<line class="base" x1="{pad:g}" x2="{width - pad:g}" '
        f'y1="{height - pad:g}" y2="{height - pad:g}"/>',
    ]
    for seg in segments:
        if len(seg) == 1:
            parts.append(f'<circle class="pt" cx="{seg[0][0]}" cy="{seg[0][1]}" r="2.5"/>')
        else:
            d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(seg))
            parts.append(f'<path class="line" d="{d}"/>')
    last_day, last_value = next((d, v) for d, v in reversed(points) if v is not None)
    lx, ly = xy(last_day, last_value)
    parts.append(f'<circle class="end" cx="{lx}" cy="{ly}" r="4"/>')
    # Invisible, generous hit targets carry a native tooltip for every day.
    for day, value in points:
        if value is None:
            continue
        hx, _ = xy(day, value)
        parts.append(
            f'<rect class="hit" x="{hx - 5}" y="0" width="10" height="{height:g}">'
            f"<title>{day.isoformat()}: {_fmt(value, kind)}</title></rect>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _island_card(s: IslandSeries) -> str:
    title = escape(s.title or s.code)
    meta = [f'<code>{escape(s.code)}</code>']
    if s.creator_code:
        meta.append(f"by {escape(s.creator_code)}")
    if s.created_in:
        meta.append(escape(s.created_in))
    tags = "".join(f'<span class="tag">{escape(t)}</span>' for t in s.tags)
    out = [
        f'<section class="card" id="island-{escape(s.code)}">',
        f"<header><h2>{title}</h2>",
        f'<p class="meta">{" · ".join(meta)}</p>',
        f'<div class="tags">{tags}</div>' if tags else "",
        "</header>",
    ]
    if not s.rows:
        out.append('<p class="nodata">No days archived yet. The next scheduled run will add them.</p>')
        out.append("</section>")
        return "".join(out)
    out.append('<div class="tiles">')
    for column, label, kind in TILES:
        value, day = s.latest(column)
        when = f"on {day}" if day else "no value yet"
        out.append(
            f'<div class="tile"><div class="label">{label}</div>'
            f'<div class="value">{_fmt(value, kind)}</div>'
            f'<div class="when">{when}</div>{sparkline(s.rows, column, kind)}</div>'
        )
    out.append("</div>")
    recent = list(reversed(s.rows[-TABLE_ROWS:]))
    head = "".join(f'<th scope="col">{label}</th>' for _, label, _ in TABLE_COLUMNS)
    body = "".join(
        f'<tr><th scope="row">{escape(r["timestamp"][:10])}</th>'
        + "".join(f"<td>{_fmt(_num(r.get(c)), k)}</td>" for c, _, k in TABLE_COLUMNS)
        + "</tr>"
        for r in recent
    )
    out.append(
        f'<details><summary>Daily table ({len(s.rows)} day{"s" if len(s.rows) != 1 else ""} archived'
        f'{", latest " + str(len(recent)) + " shown" if len(recent) < len(s.rows) else ""})</summary>'
        f'<div class="scroll"><table><thead><tr><th scope="col">Day (UTC)</th>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div></details>"
    )
    out.append("</section>")
    return "".join(out)


CSS = """
:root{color-scheme:light;--bg:#f4f4f2;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;
--ink3:#6f6e69;--rule:#e2e1dc;--accent:#2a78d6;--tag:#ecebe7}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#111110;--surface:#1a1a19;
--ink:#ffffff;--ink2:#c3c2b7;--ink3:#9a998f;--rule:#2e2d2a;--accent:#3987e5;--tag:#262624}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.5rem;margin:0 0 4px}
.lede{color:var(--ink2);margin:0 0 24px;max-width:70ch}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:16px;margin:0 0 16px}
.card h2{font-size:1.1rem;margin:0;overflow-wrap:anywhere}
.meta{color:var(--ink2);margin:2px 0 0;font-size:.9rem}
.meta code{font:500 .9em ui-monospace,SFMono-Regular,Menlo,monospace}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tag{background:var(--tag);color:var(--ink2);border-radius:999px;padding:1px 10px;font-size:.8rem}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}
.tile{border:1px solid var(--rule);border-radius:10px;padding:10px 12px}
.label{color:var(--ink2);font-size:.85rem}
.value{font-size:1.6rem;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.2}
.when{color:var(--ink3);font-size:.8rem;margin-bottom:6px}
.spark{display:block;width:100%;height:auto}
.spark .line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.spark .pt{fill:var(--accent)}
.spark .end{fill:var(--accent);stroke:var(--surface);stroke-width:2}
.spark .base{stroke:var(--rule);stroke-width:1}
.spark .hit{fill:transparent}
.spark .hit:hover{fill:var(--rule);fill-opacity:.5}
.nodata{color:var(--ink3);margin:12px 0 0;font-size:.9rem}
details{margin-top:12px}
summary{cursor:pointer;color:var(--ink2);font-size:.9rem}
.scroll{overflow-x:auto;margin-top:8px}
table{border-collapse:collapse;width:100%;font-size:.85rem;font-variant-numeric:tabular-nums}
th,td{padding:4px 8px;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th[scope=row],thead th:first-child{text-align:left}
th[scope=row]{font-weight:500;font-variant-numeric:tabular-nums}
thead th{color:var(--ink2);font-weight:500}
footer{color:var(--ink3);font-size:.8rem;margin-top:32px}
footer a{color:inherit}
@media (max-width:640px){.tiles{grid-template-columns:1fr;gap:8px}.value{font-size:1.4rem}
.tile{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);column-gap:12px;align-items:center}
.tile .spark,.tile .nodata{grid-column:2;grid-row:1/4;margin:0}.when{margin:0}}
"""


def render_report(data_dir: Path) -> str:
    """Return the report HTML for the archive in ``data_dir``."""
    islands = load_archive(data_dir)
    days = sorted({r["timestamp"][:10] for s in islands for r in s.rows})
    if days:
        span = f"Daily snapshots from {days[0]} to {days[-1]} (UTC)."
    else:
        span = "No days archived yet."
    cards = "".join(_island_card(s) for s in islands) or '<p class="nodata">No islands tracked yet.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>islandpulse archive</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>islandpulse archive</h1>
<p class="lede">{len(islands)} Fortnite island{"s" if len(islands) != 1 else ""} tracked. {span}
Epic's Fortnite Data API only keeps the last 7 days, so this archive holds history the API no longer serves.</p>
{cards}
<footer>
<p>Data from Epic Games' public Fortnite Data API, provided as-is. Not affiliated with or endorsed by Epic Games.
Generated by <a href="https://github.com/abafaboy/islandpulse">islandpulse</a> {__version__}.</p>
</footer>
</main>
</body>
</html>
"""


def write_report(data_dir: Path, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(data_dir), encoding="utf-8")
    return out
