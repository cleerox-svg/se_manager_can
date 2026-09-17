# Progress

## Completed (2026-09-17)
- **ARR toggle (Look Forward & Inspect only)**: deals ≥$150K shown by default per quarter bucket, deals <$150K behind a nested `<details>` disclosure ("Show N deals below $150K"). No changes to Macro View, Look Back, Wrap-Up & Risk, or Win Rate. No stat card or badge restored.
- **`deals` table fingerprint diffing**: `sheets_sync.py` now computes a per-row fingerprint and skips unchanged rows, matching `closed_deals_sync.py`/`tech_forecast_sync.py`. `db.py` migrated `deals.row_fingerprint` via the existing idempotent `_migrate()` pattern. `.claude/agents/deals-sync.md` notes updated to describe delta detection instead of "always synced."
- **Sheet split migration** (both closed-deals and tech-forecast moved off the old Team Tracking Sheet into standalone spreadsheets):
  - Tech Forecast: `1g3KNpgKR-d_6InGgaP5dg6u1DPFCrph1hM1STI7mjrA`, tab "Canada SE Tech Forecast current and next q", gid `396663916`.
  - Closed deals: `12r7Y6BBtcowuyTnU_U6gUTTsn14SF3Ej-qcsweQA9OY`, tab "Tech wins and losses", gid `0` (new gid, was `1875218606`).
  - Updated docstrings/agent `.md` files/README/CLAUDE.md to match. `deals` (open pipeline) tab is untouched — still lives on the Team Tracking Sheet at gid `0`.

## Flagged, not yet resolved
- **"Lead Sales Engineer" column reappeared** on the Tech Forecast sheet — CLAUDE.md/README/docstrings still say it was dropped 2026-09-15. Not wired back into `_HEADER_MAP`/`_GROUP_LEVELS` yet. Need to confirm with user whether it's genuinely repopulated before touching sync logic.
- **New "POC" column** appears on both new sheets (tech forecast + closed deals), unmapped in either sync script.
- **"Sync now" button** in `TechForecast.jsx` only copies a clipboard prompt for manual paste into a Claude Code chat — not a real automated/scheduled trigger. Worth confirming this matches user's expectation of "auto refresh" now that the sheets are split out.

## Next steps
- Ask user about the Lead SE column and POC column before making sync-script changes.
- Commit and push the current batch (ARR toggle + fingerprinting + sheet migration).
