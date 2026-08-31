# SE Manager Hub — project notes for Claude

## Run

```bash
py app.py
```

Use `py`, not `python` — on this machine `python` resolves to the Windows
Store alias and fails.

## Architecture rules

- SQLite via thread-local connections (`db._get_con()`), same pattern as
  NaughtRFP's `db.py` — never add a `check_same_thread=False` workaround
  elsewhere, it's already handled in the connection layer.
- All httpx clients calling the LiteLLM proxy need `verify=False` — Okta's
  corporate proxy does SSL inspection and breaks default cert verification.
- Model names live in `reviews.py` as a constant (`_MODEL`) — never hardcode
  a model string anywhere else.
- Slack sync must use a **user token**, not a bot token — `search.messages`
  is user-token-only in the Slack Web API.
- Jordan Taylor (and any other departed rep) must never be presented as an
  active/current direct report. Their historical deals stay visible in the
  dashboard — pipeline data is real regardless of who's assigned — but the
  Team page's active/inactive flag governs who counts as "current team" for
  review generation.

## MCP-assisted sync (no credentials needed)

`sheets_sync.py` and `slack_sync.py` each have two entry points: a
credential-based one (service account / Slack user token, used by the
Settings-page Sync buttons) and a data-based one that just loads
already-fetched rows/matches (`sync_deals_from_values`,
`sync_slack_notes_from_matches`). The latter is what powers "hey Claude,
sync deals" requests, since the user hasn't set up a service account or
Slack App for this project — this is the primary path, not a fallback.

When asked to sync, in a live Claude Code session:
1. Fetch the sheet (`get_all_values()`-shaped grid) or Slack search results
   using the connected Google Sheets / Slack MCP tools.
2. Write a temp JSON payload matching `mcp_ingest.py`'s docstring shape to
   `_mcp_payload_<kind>.json` in the project root (already gitignored).
3. Run `py mcp_ingest.py deals <file>`, `py mcp_ingest.py closed_deals <file>`,
   or `py mcp_ingest.py slack <file>`.
4. Delete the temp file afterward.

The Team Tracking Sheet's tabs get renamed by the user from time to time —
don't trust hardcoded tab names in this file, always confirm live via
`get_spreadsheet_info` (which lists by stable `gid`) before a sync. As of
2026-08-24 there are three tabs (the "Clari" tab that used to exist is
gone): "Lead SE Pipeline SFDC" (gid `0`, open pipeline → `deals` — formerly
called "SFDC"), "Canada SE Closed This Fiscal Year" (gid `1875218606`,
closed-won export → `closed_deals`, one row per closed opportunity,
`tech_win` flag set when Presales Stage is `'6 - Technical Win'` —
formerly "Sheet3"), and "Satish Technical Forecast Current Q" (gid
`931673469`, Technical Forecast pipeline → `tech_forecast_deals` —
formerly "Sheet4"). The Google Drive content-export tool
(`google_drive-get_drive_file_content`) only returns the default/first
sheet as CSV — it cannot target a tab by name. To read a specific tab,
authenticate and use the dedicated `mcp__google_sheets__*` tools instead:
`get_spreadsheet_info` to confirm the current tab name/gid, then
`read_sheet_values` with an explicit `TabName!A1:Z1000`-style range.
`closed_deals_sync.py` normalizes Sheet3's grid the same way
`sheets_sync.py` does for SFDC, except the group-header suffix is a
running dollar total (`"Sean Keleher (USD 1,095,169.27)"`) not a row
count, so it has its own strip regex rather than reusing
`_strip_group_count`.

Sheet4 is nested one level deeper than SFDC/Sheet3: group-header rows run
Account Owner AVP Region > Presales Stage > Deal Forecast Status, each
carrying a `(<count>)` suffix, before the individual deal rows.
`tech_forecast_sync.py` forward-fills all three levels and resets the
`forecast_status` fill whenever `presales_stage` changes (a new stage
group always starts a fresh status group). Unlike SFDC/Sheet3, every
subtotal/group-header row here is reliably identifiable by a blank
Opportunity Name column, so there's no need for a marker-string check —
confirmed against the live 23-row grid before writing the skip logic.
Staleness is snapshot-diff based, not date-parsed: each sync compares the
incoming pre-sales notes text against the value stored from the *previous*
sync and sets `notes_stale` on the row if unchanged.

For Slack, `se_rep_id` must be resolved from `se_reps` first (by
`slack_user_id` or name) — look it up via `GET /api/reps` or a direct query,
don't guess it.

Slack search queries must use literal `<` `>` characters around user
mentions (`from:<@U09TPQER3AN> after:2026-05-13`) — passing HTML-escaped
entities (`&lt;@U...&gt;`) sends the literal escaped string to Slack's
search backend and silently returns zero results instead of erroring, which
reads as "this rep has no Slack activity" when they actually do. If a sync
comes back empty for every rep, suspect this before concluding there's no
data. Each search also caps at ~20 results per page with a pagination
cursor (`pagination_info`) — for reps with heavy channel activity, one page
may not cover the full lookback window.

The Team Tracking Sheet's grouped layout has two more quirks beyond the
forward-fill already described in `sheets_sync.py`'s module docstring:
group-header cells read like `Nic Da Silva (9)` / `2 - Discovery (3)` — a
live row count appended to the name/stage, not part of it — and the
*per-lead* subtotal row (unlike the per-stage one) puts the literal word
`Subtotal` in the Lead SE column itself. Both are handled by
`_strip_group_count`; if a future column gets added to the grouped layout,
check whether it needs the same treatment before trusting a raw sync.

In a fresh Bash-tool session (no venv activation), `py`/`python` resolve to
the global interpreter, not this project's venv — `py mcp_ingest.py ...`
fails with `ModuleNotFoundError: No module named 'gspread'` even though
`requirements.txt` is fully installed in `venv/`. Use
`venv/Scripts/python.exe <script>` directly instead of `py <script>` when
running ingest/sync scripts from Claude Code, rather than assuming the venv
is on PATH.

## Clari manual local-file sync

Clari (AE-level quota/forecast/pipeline-coverage tool) has no MCP/API
surface reachable from this app, so `clari_sync.py` skips the
fetch-vs-load split the MCP-assisted scripts use and just reads a local
file directly — there is no automated or scheduled path, this is always a
manual, chat-mediated flow:

1. Claude Leroux drops the week's two CSV exports (This Quarter / Next
   Quarter) into `C:\Users\ClaudeLeroux\Desktop\Claude Code Projects\Clari
   Reporting\` (override via `CLARI_EXPORT_DIR` env var).
2. Ask Claude to sync; it runs
   `venv/Scripts/python.exe clari_sync.py this_quarter` and
   `... next_quarter` (same venv-not-on-PATH caveat as other scripts — `py`
   resolves to the global interpreter in a fresh Bash session).
3. `clari_sync.py` globs the folder for the newest filename containing
   "this quarter"/"next quarter" (case/underscore-insensitive) rather than
   trusting a hardcoded date-stamped name.

The export is AE-level, not deal-level — a long/tidy weekly time series
per AE (Field, Data Type, Week, Start Day, End Day, Data Value) with zero
opportunity- or SE-level identifiers. The one clean join key is `User`,
which is an exact string match for `tech_forecast_deals.opportunity_owner`
(confirmed live — e.g. "Ahmed Majid", "Dylan Amin", "Ryan Nell" appear in
both). Only the `(Field, Data Type)` pairs in
`tech_forecast_report.CLARI_ALLOWED_PAIRS` are kept — most combinations
(freeform Notes/Adjustment Notes, "Forecast Updated" Yes/No, etc.) carry no
identifiers of use here.

`Timeframe` has a dual role that's easy to miss: Clari exports a monthly
breakdown for `Forecast`/`Forecast [Auth]`/`Forecast [Okta]` (Timeframe
values like "August FY 2027") *alongside* a quarterly rollup ("Q3"/"Q4" —
the label shifts by fiscal quarter, so `clari_sync.py` matches the bare
`^Q\d+$` pattern rather than hardcoding one). Every other field only ever
has the quarterly-rollup row. Only the rollup row is kept, so this always
reports the AE's whole-quarter numbers. The Auth0/Okta split on `Forecast`
itself is native to Clari (`Forecast [Auth]`/`Forecast [Okta]`, Data Type
`Forecast Value`) — only `Gap to Forecast` and the two `Coverage` fields
are blended-only in Clari, so those two are *derived* in
`build_ae_crossref` (quota minus that product's native forecast) rather
than read directly; they're suffixed `_derived`/`_blended` in the
crossref payload so callers don't mistake them for a number Clari itself
reports.

Week index isn't trustworthy on its own (it resets/shifts across
exports) — rows are matched against *today's* date falling within Start
Day/End Day instead. `clari_ae_snapshots` is scoped to
`WHERE source_label = ?` on delete (both This Quarter and Next Quarter
share one table, so an unscoped delete would wipe one label's rows while
loading the other), and a zero-row sync (e.g. run on a day outside any
week's date window — expected for Next Quarter's file until its first week
starts) skips the delete step entirely rather than zeroing that label's
data.

## Git workflow

**No GitHub for now** — work stays local only. Local `git commit` is fine;
do not create a remote repo or run `git push` unless the user explicitly
says otherwise.

## Docs

Always update README.md after any non-trivial feature change. Work in small
chunks with a visible task list.

## Key files

| File | Purpose |
|---|---|
| `app.py` | Flask routes |
| `db.py` | SQLite schema + thread-local connections |
| `sheets_sync.py` | Google Sheets "Lead SE Pipeline SFDC" tab → `deals` table |
| `closed_deals_sync.py` | Google Sheets "Canada SE Closed This Fiscal Year" tab (closed-won/technical-win export) → `closed_deals` table |
| `tech_forecast_sync.py` | Google Sheets "Satish Technical Forecast Current Q" tab (Technical Forecast pipeline) → `tech_forecast_deals` table; also captures the daily snapshot used for week-over-week deltas |
| `tech_forecast_report.py` | Pure aggregation/report logic for the Technical Forecast page + Slack preread (bucket totals, key metrics, top deals, weekly deltas, AE cross-reference) — no Flask dependency, reused by `app.py` and `tech_forecast_sync.py` |
| `clari_sync.py` | Manual local-file parser — weekly Clari AE-level CSV export (`Clari Reporting\` folder) → `clari_ae_snapshots` table |
| `slack_sync.py` | Slack `search.messages` → `slack_notes` table |
| `mcp_ingest.py` | CLI bridge — loads MCP-fetched JSON into the DB, no credentials needed |
| `seed_arr_targets.py` | One-off: sets `se_reps.arr_target` by name (FY26 H2: Sean/Rishika $2.5M, Valentin/Nic $1.5M) |
| `reviews.py` | LiteLLM-backed review drafting |
| `static/style.css` | Okta dark theme (shared tokens with NaughtRFP) |
| `static/app.js` | SPA frontend — router, API helper, page renderers |
| `templates/index.html` | SPA shell |

## Not built yet

Gong integration — user is wiring this up themselves.
