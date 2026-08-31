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
2026-08-31 there are three tabs: "Lead SE Pipeline SFDC" (gid `0`, open
pipeline → `deals` — formerly called "SFDC"), "Canada SE Closed This
Fiscal Year" (gid `1875218606`, closed-won export → `closed_deals`, one
row per closed opportunity, `tech_win` flag set when Presales Stage is
`'6 - Technical Win'` — formerly "Sheet3"), and "Claude This q and next"
(gid `396663916`, Technical Forecast pipeline → `tech_forecast_deals` —
replaced "Satish Technical Forecast Current Q"/gid `931673469`; this tab
auto-refreshes every 24 hours, so a live fetch is always treated as
fresh). The Google Drive content-export tool
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

"Claude This q and next" is nested one level deeper than SFDC/Sheet3:
group-header rows run Lead Sales Engineer > Presales Stage > Deal Forecast
Status, each carrying a `(<count>)` suffix, before the individual deal
rows. Deals with no Lead SE assigned yet group under a bare `-` instead of
a name — `tech_forecast_sync.py` treats that the same as blank so it never
forward-fills into a real name. `_normalize_values` forward-fills all
three levels and cascades the reset down: changing `lead_se_name` resets
both `presales_stage` and `forecast_status`, and changing `presales_stage`
resets `forecast_status` — a new Lead SE's first stage/status group must
never inherit the previous SE's leftover fill. Unlike SFDC/Sheet3, every
subtotal/group-header row here is reliably identifiable by a blank
Opportunity Name column, so there's no need for a marker-string check —
confirmed against the live 80-row grid before writing the skip logic.
Staleness is snapshot-diff based, not date-parsed: each sync compares the
incoming Pre-Sales Next Steps text against the value stored from the
*previous* sync and sets `notes_stale` on the row if unchanged.

The sheet's three notes columns (Pre-Sales Notes, SE Manager Notes,
Pre-Sales Next Steps) hold long dated logs, newest entry first (e.g. "RK
Aug-31-2026 : ... \r\n\r\nRK Aug-24-2026 : ..."). `mcp__google_sheets__
google_sheets-read_sheet_values` truncates any single cell at roughly 300
characters (confirmed by fetching an isolated cell — it's the tool's own
per-cell limit, not a display artifact of wide-range reads), which in
practice keeps the newest dated entry and cuts off older history with a
trailing "...". Per Claude Leroux (2026-08-31), that's an acceptable
tradeoff for this sheet specifically, since the newest entry is what
matters for the Monday call — no workaround needed, just don't be
surprised when a synced note looks cut off mid-sentence.

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
| `tech_forecast_sync.py` | Google Sheets "Claude This q and next" tab (Technical Forecast pipeline, grouped Lead SE > Presales Stage > Deal Forecast Status) → `tech_forecast_deals` table; also captures the daily snapshot used for week-over-week deltas |
| `tech_forecast_report.py` | Pure aggregation/report logic for the Technical Forecast page + Slack preread (bucket totals, key metrics, top deals, weekly deltas, needs-Lead-SE list) — no Flask dependency, reused by `app.py` and `tech_forecast_sync.py` |
| `slack_sync.py` | Slack `search.messages` → `slack_notes` table |
| `mcp_ingest.py` | CLI bridge — loads MCP-fetched JSON into the DB, no credentials needed |
| `seed_arr_targets.py` | One-off: sets `se_reps.arr_target` by name (FY26 H2: Sean/Rishika $2.5M, Valentin/Nic $1.5M) |
| `reviews.py` | LiteLLM-backed review drafting |
| `static/style.css` | Okta dark theme (shared tokens with NaughtRFP) |
| `static/app.js` | SPA frontend — router, API helper, page renderers |
| `templates/index.html` | SPA shell |

## Not built yet

Gong integration — user is wiring this up themselves.
