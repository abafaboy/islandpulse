# Changelog

## 0.1.0 - 2026-09-24

First release.

- `Client` for `https://api.fortnite.com/ecosystem/v1` (stdlib only, Python 3.10+):
  `island()`, `metrics()`, `islands_page()`, `iter_islands()` with cursor pagination.
- Typed `Island` and `DailyMetrics` records; metrics merged per timestamp, `null` kept as `None`.
- Client-side guards for island codes, the 7-day window and the timestamp format.
- Retries with exponential backoff on 429/5xx/network errors, honouring `Retry-After`.
- CLI: `island`, `metrics`, `new`, `archive`, `report`.
- Append-only CSV archive with timestamp dedupe and null-fill merge.
- Self-contained HTML report with inline SVG sparklines, light and dark themes.
- GitHub Actions: daily archive with commit-back and optional Pages deploy; CI on 3.10-3.13.
