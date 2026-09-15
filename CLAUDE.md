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

## Context economy — keep data out of the conversation

Never `cat`, `Read`, or otherwise load a full CSV/JSON data file into the
conversation — this includes the `_mcp_payload_<kind>.json` temp payloads and
any exported sheet/Slack data. If you need to sanity-check a data file, use
`head -20`, `wc -l`, or `jq '.foo'` against it — never a full read. This is a
hard rule, not a style preference: a single sheet payload can be tens of
thousands of tokens, and reading it "just to check" defeats the entire point
of the MCP-assisted sync design below.

`mcp_ingest.py` deliberately prints one line of JSON — the sync counts, not
the rows. Never change it to print full row data, and never paste raw sheet
or Slack payload contents back into a chat response — a short summary
(rows synced/unchanged/deleted, any errors) is the only thing that should
ever leave the script and reach the user.

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
`closed_deals_sync.py` normalizes Sheet3's grid, but it's nested three
levels deep rather than SFDC's two: Team Member Name > Team Role > Region
(`_GROUP_LEVELS = ("rep_name", "team_role", "region")`). Each group-header
cell carries a running dollar total suffix instead of a row count, e.g.
`"Sean Keleher (USD 1,099,753.82)"`, so it has its own strip regex
(`_GROUP_SUFFIX_RE`) rather than reusing `_strip_group_count`. Team Role and
Region are grouping-only fields used to walk the structure — neither is
persisted to `closed_deals`. Stage carries both "10 - Closed/Won" and a
Closed/Lost value — the tab covers all closed deals, not won deals only.
Presales Stage is the separate flat per-row column that drives `tech_win`.
Because of this, `/api/closed-deals/summary`'s team-level query filters
`WHERE se_rep_id IS NOT NULL` and reports `closed_won`/`closed_won_pct`
alongside `tech_win_pct` — Tech Win Rate's denominator is "closed deals with
an assigned SE," not "closed-won deals." Any other query against
`closed_deals` — e.g. `app.py`'s `list_reps` (`/api/reps`) `arr_total`
subquery — must add `AND sales_stage = '10 - Closed/Won'` too, or it will
double-count Lost-deal amounts as revenue; this exact bug shipped once
(fixed 2026-09) because the mixed-data warning above wasn't cross-referenced
from that second query site.

`list_reps`'s `tech_forecast_arr` subquery had a parallel bug (fixed
2026-09-11): it attributed `tech_forecast_deals` rows to a rep via an
opportunity_name→`deals.se_rep_id` join only, which is step 3 of
`/api/tech-forecast`'s three-step precedence (`assigned_se_rep_id` override >
case-insensitive `lead_se_name` match > opportunity_name fallback). Reps
attributed via steps 1-2 got $0 in this column even with real forecasted ARR,
and the column's total didn't match the Tech Forecast page. The subquery now
mirrors the same three-step precedence as a correlated `COALESCE`.

"Claude This q and next" is nested one level deeper than SFDC/Sheet3:
group-header rows run Lead Sales Engineer > Deal Forecast Status, each
carrying a `(<count>)` suffix, before the individual deal rows. Deals with
no Lead SE assigned yet group under a bare `-` instead of a name —
`tech_forecast_sync.py` treats that the same as blank so it never
forward-fills into a real name. `_normalize_values` forward-fills both
levels and cascades the reset down: changing `lead_se_name` resets
`forecast_status` — a new Lead SE's first status group must never inherit
the previous SE's leftover fill. Unlike SFDC/Sheet3, every subtotal/
group-header row here is reliably identifiable by a blank Opportunity Name
column, so there's no need for a marker-string check — confirmed against
the live grid before writing the skip logic.

As of 2026-09-02, Presales Stage is a flat per-deal column (like Stage or
Account Region), not a group level — the sheet's underlying query was
restructured to expose it per-deal (genuinely blank for some deals not yet
staged) instead of as the old middle grouping level. Don't add it back to
`_GROUP_LEVELS` in `tech_forecast_sync.py`.

The sheet's query isn't scoped to our team only — it also carries deals
whose Opportunity Owner: Manager is Greg Rainbird, a different sales org.
`tech_forecast_sync.py` no longer drops those rows; instead it tags any row
where that field matches (`_OTHER_ORG_MANAGER_TAGS`, a manager → `(product,
segment)` mapping) with `product`/`segment` values so they stay visible on
the page but are clearly marked as belonging to a different org — even when
one of our own Lead SEs is still attached (e.g. Luis Santos, since gone
inactive). `product`/`segment` are re-derived on every sync (unlike the
manual `assigned_se_rep_id`/`backup_se_rep_id` overrides, which a sync must
never clobber) and aren't part of the row fingerprint, so tagging alone
never triggers spurious staleness. If another manager's team shows up mixed
in later, add them to that same mapping rather than special-casing Lead SE.
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

## Fiscal quarters

Okta's fiscal year starts **Feb 1**, not Jan 1 — FY26 runs Feb 2026 through
Jan 2027, named by its start year. `tech_forecast_report.fiscal_quarter()`
implements this (`FY<start-year>-Q<n>`, e.g. Aug 2026 → `FY26-Q3`) and powers
the Look Back — Recent Technical Wins grouping. This is deliberately
separate from `app.py`'s `current_quarter()` and `sheets_sync.py`'s
`_quarter()`, which are plain calendar quarters (Jan-Mar = Q1, etc.) used for
the open SFDC pipeline's "current quarter" filter — a different feature with
its own (calendar-based) notion of quarter. Don't unify these without
checking which behavior each caller actually needs.

`tech_forecast_report.build_tech_win_trend()` (used by the Dashboard's
`/api/dashboard/tech-win-trend` endpoint) also groups by `fiscal_quarter()` /
`fiscal_quarter_sort_key()` — the new Dashboard standardizes on fiscal
quarters to match Technical Forecast, diverging from the old Dashboard's
calendar-quarter `current_quarter()`.

`tech_forecast_report.quarter_bucket()` reuses `fiscal_quarter()` to label a
deal's target Technical Win date (Tech Win Date, falling back to Close Date)
as `current`/`next`/`later`/`None` relative to *today's* fiscal quarter — this
powers the Slack draft's Current Quarter / Next Quarter split under "Come
ready to discuss." `_offset_quarter_key` shifts a `(fy, q)` sort-key tuple by
N quarters (wrapping year boundaries) to compute the "next quarter" label
without re-deriving fiscal-quarter math a second time.

Per Claude Leroux (2026-09-02), the Slack draft's per-deal discussion
question (`build_discussion_question`) is deliberately rule-based, not
LLM-generated — `LITELLM_API_KEY` isn't configured (`litellm_configured:
false` in `/api/settings`), which is also why the existing review-drafting
"Generate draft" button on the Team/Person pages is currently non-functional
(returns a 400). The heuristic checks, in priority order (each is a stronger
signal than the next): missing Pre-Sales Next Steps entirely > `notes_stale`
(unchanged since last sync) > `forecast_status == "Forecasted Risk"` >
a per-`presales_stage` prompt. If `LITELLM_API_KEY` is ever configured,
revisit whether to upgrade this to an actual LLM call (reusing `reviews.py`'s
`_make_client` pattern) — the user's answer was "heuristic now," not a
permanent rejection of the LLM path.

Per Claude Leroux (2026-09-14), the Actions page's "SFDC Updates" card
(`GET /api/tech-forecast/sfdc-updates`, backed by
`tech_forecast_report.build_sfdc_updates`/`draft_sfdc_note`) is the same
"heuristic now" call: rule-based note drafting, not an LLM call, for the
same `LITELLM_API_KEY`-not-configured reason as `build_discussion_question`
above. `draft_sfdc_note` also deliberately surfaces the newest dated note
entry verbatim rather than synthesizing new prose from it — reusing whatever
the SE actually wrote avoids fabricating claims about a deal and keeps the
drafted note in the user's own words/patterns, which matters more here since
this note is meant to be pasted straight into Salesforce.

## Git workflow

Per Claude Leroux (2026-09-15): keep `origin/main` always up to date, not
just local. Commit and push after any meaningful change — don't batch
unpushed commits or wait for the user to ask. This supersedes the prior
"no GitHub by default" rule (which had scoped push authorization to the
React migration only); that scoping no longer applies.

## Sub-agents

**Standing rule, not a reminder: for any data upload, sync, or bulk file
work on this project, delegate to the matching subagent below — never run
the fetch → payload → ingest flow inline in the main thread.** This applies
every session, unprompted; don't wait for the user to say "use a subagent."

Four Claude Code custom agents live in `.claude/agents/` and are auto-loaded in every Claude Code session opened against this project directory:

| Agent | File | Trigger |
|---|---|---|
| `tech-forecast-sync` | `.claude/agents/tech-forecast-sync.md` | "sync tech forecast", "refresh tech forecast" |
| `deals-sync` | `.claude/agents/deals-sync.md` | "sync deals", "refresh pipeline" |
| `closed-deals-sync` | `.claude/agents/closed-deals-sync.md` | "sync closed deals", "refresh closed deals" |
| `slack-sync` | `.claude/agents/slack-sync.md` | "sync Slack", "refresh Slack notes" |

Each agent handles the full MCP-assisted sync flow for its data type: confirm live tab name/gid, fetch data, write temp JSON payload, run `mcp_ingest.py` via `venv/Scripts/python.exe`, delete temp file, report result. Tab gid values are stable even when tab names change — agents always confirm the live name via `get_spreadsheet_info` before reading.

Every agent must report back to the main thread with a **brief summary
only** — synced/unchanged/deleted counts and any errors, never the raw
payload, full script stdout, or row-level data. If a subagent's reply starts
looking like a data dump, that's a bug in the agent's instructions to fix,
since it erases the whole point of delegating.

The `/sync-se-hub` skill (`.claude/skills/sync-se-hub/SKILL.md`) is the slash-command entry point — it dispatches to these four agents in parallel (all four by default, or a subset if the user names specific kinds) rather than duplicating any sync logic itself.

## Docs

Always update README.md after any non-trivial feature change. Work in small
chunks with a visible task list.

## progress.md — surviving context compaction

For any task that spans multiple steps or sessions (a multi-phase migration,
a multi-file refactor, anything likely to hit a context compaction before
it's done), maintain `progress.md` in the project root with three sections:
**Completed** (what's done, one line each), **Next steps** (what's left, in
order), and **Key IDs** (file paths, gids, opportunity IDs, PR/branch names —
anything you'd otherwise have to re-derive). Update it after each meaningful
step, not just at the end.

After a compaction event, read `progress.md` first, before re-running any
investigation (`git log`, re-reading files, re-fetching sheet data) — it
should contain enough to resume without redoing that work. Delete or clear
the file's contents once the task it tracks is fully done; it's a working
scratchpad for one task, not a running log.

## Key files

| File | Purpose |
|---|---|
| `app.py` | Flask routes |
| `db.py` | SQLite schema + thread-local connections |
| `sheets_sync.py` | Google Sheets "Lead SE Pipeline SFDC" tab → `deals` table |
| `closed_deals_sync.py` | Google Sheets "Canada SE Closed This Fiscal Year" tab (closed-deal export, Won and Lost, technical-win flag) → `closed_deals` table |
| `tech_forecast_sync.py` | Google Sheets "Claude This q and next" tab (Technical Forecast pipeline, grouped Lead SE > Deal Forecast Status, Presales Stage flat per-deal) → `tech_forecast_deals` table; also captures the daily snapshot used for week-over-week deltas |
| `tech_forecast_report.py` | Pure aggregation/report logic for the Technical Forecast page + Slack preread (bucket totals, key metrics, top deals w/ fiscal-quarter bucket + heuristic discussion question, weekly deltas, needs-Lead-SE list, missing-notes list) and the Actions page's SFDC Updates card (`build_sfdc_updates`/`draft_sfdc_note` — rule-based per-opportunity Salesforce note drafts) — no Flask dependency, reused by `app.py` and `tech_forecast_sync.py` |
| `slack_sync.py` | Slack `search.messages` → `slack_notes` table |
| `mcp_ingest.py` | CLI bridge — loads MCP-fetched JSON into the DB, no credentials needed |
| `seed_arr_targets.py` | One-off: sets `se_reps.arr_target` by name (FY26 H2: Sean/Rishika $2.5M, Valentin/Nic $1.5M) |
| `reviews.py` | LiteLLM-backed review drafting |
| `frontend/` | React (Vite) frontend — `src/api.js` (fetch helpers), `src/App.jsx` (shell/router), `src/pages/`, `src/components/`, `src/style.css` (ported Okta dark theme). `npm run build` in `frontend/` produces `frontend/dist`, which is committed and served by Flask at `/` (see `app.py`'s `static_folder`) |

## Not built yet

Gong integration — user is wiring this up themselves.
