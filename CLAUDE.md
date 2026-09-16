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
- `db.conn()` is **re-entrant**, and callers may rely on that: only the
  outermost scope commits, inner scopes take a SAVEPOINT, so an inner failure
  undoes just its own writes. It did not used to be — a nested `with
  db.conn()` committed the OUTER transaction as soon as the inner block
  exited and dragged the outer's work into an inner rollback, which made it
  unsafe to call any helper that opens its own scope (`set_setting`, a report
  builder) from inside a transaction. Don't "simplify" the depth counter away.
- All httpx clients calling the LiteLLM proxy need `verify=False` — Okta's
  corporate proxy does SSL inspection and breaks default cert verification.
- Model identifiers live in `models.py` (`LITELLM_MODEL` for the LiteLLM proxy,
  `BEDROCK_MODEL_ID` for `bedrock_agent.py`'s Converse loop) — never hardcode a
  model string anywhere else. `reviews.py` still exposes `_MODEL`, now imported
  from there. The two ids are not interchangeable: the Bedrock one is a
  cross-region *inference profile* id whose `us.` prefix is part of the id on
  that API and is coupled to the client's region, and is a different form from
  the bare `anthropic.` prefix the Anthropic SDK's Bedrock client uses.
- SFDC stage strings live in `constants.py` (`STAGE_CLOSED_WON`,
  `PRESALES_TECH_WIN`, `FORECAST_RISK`) — import them, never re-type the
  literal. The same rule applies to the three-step SE attribution precedence
  (`attribution.py`) and to grouped-sheet parsing (`sheet_parse.py`): one
  copy, imported. Both shipped bugs recorded below came from a duplicated
  literal/query drifting out of sync with its siblings.
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
   `py mcp_ingest.py tech_forecast <file>`, or `py mcp_ingest.py slack <file>`
   (see the venv-path note near the end of this section — from a Bash tool it's
   `venv/Scripts/python.exe`, not `py`).
4. Delete the temp file afterward.

What a sync returns and what can stop it:

- Result keys. The three sheet syncs return `synced` / `unchanged` /
  `deleted` / `overrides_carried` / `unparsed_amounts` (`deals` has no
  per-row fingerprint, so its `unchanged` is always 0 and every payload row
  counts as `synced`; `closed_deals` omits `overrides_carried` — that table
  has no manual override columns). `unparsed_amounts` counts non-blank money
  cells that failed to parse, i.e. money silently dropped — mention it in the
  report if it's non-zero. Slack returns `synced` / `new` / `updated` /
  `unchanged`, counting rows actually WRITTEN rather than matches fetched (a
  re-run used to report a full lookback window of "new" activity).
- Shrink guard. A sync aborts with a `RuntimeError` when the payload has
  more than 20% fewer rows than are stored
  (`sheet_parse.guard_row_shrink` / `MIN_ROW_RETENTION_RATIO`), because a
  truncated fetch is indistinguishable from a shrunken sheet and the delete
  pass would hard-delete the missing rows. The usual cause is the `A1:Z1000`
  read range or a pagination cursor cutting the grid short: re-fetch wider
  first. Only when the sheet really did shrink (e.g. a fiscal-year rollover
  emptying the closed tab) pass `--allow-shrink` to `mcp_ingest.py`
  (`allow_shrink=True` on the `sync_*_from_values` functions). Never reach
  for the flag to make an error go away.
- Header mismatch. `sheet_parse.map_header` raises and names the missing
  columns when the header row doesn't match the expected layout, instead of
  reporting a cheerful `{"synced": 0}`. If that fires, the tab or range is
  wrong (the grid may start below row 1), not the sync.
- **One-time re-key churn.** Rows are now keyed by Salesforce opportunity ID
  (`oid:` prefix) when the sheet carries one, falling back to a composite
  built from the *parsed* ISO date (`sheet_parse.build_sheet_key`). The old
  keys embedded mutable fields, so a slipped close date, an advanced stage or
  a merely reformatted date cell deleted and reinserted the row — taking
  `assigned_se_rep_id`/`backup_se_rep_id`/`backup_note` with it. The first
  sync after this change re-keys existing rows, so expect one run with a
  large `synced` + `deleted` count and one week-over-week delta showing deals
  as dropped and re-added. That is expected, once. Manual overrides are
  carried across the re-key (`sheet_parse.match_rekeyed_rows`, reported as
  `overrides_carried`), so nothing is lost — report the churn as expected
  rather than re-syncing to "fix" it.
- New rep names discovered in the sheet are inserted `active = 0` (pending
  review on the Team page), never active. A typo'd or unfamiliar name must
  not become a current direct report on its own — same rule as the
  departed-rep rule above.

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
As of 2026-09-15 the sheet dropped its old three-level Team Member Name >
Team Role > Region grouping — it's now a flat, single-manager export, one
row per closed opportunity, no grouping/hierarchy left at all.
`closed_deals_sync.py` no longer has a `_GROUP_LEVELS` or calls
`sheet_parse.strip_group_label`; it just maps the flat header via
`map_header`. "Manager" (always "Claude Leroux") and "Opportunity Owner"
(the account owner) are constant/per-owner, not per-deal, so neither is a
usable `rep_name` source any more — every row attributes as "Unassigned"
(`se_rep_id = NULL`). Stage carries both "10 - Closed/Won" and a Closed/Lost
value — the tab covers all closed deals, not won deals only. Presales Stage
is the separate flat per-row column that drives `tech_win`.

**Rule: every dollar query against `closed_deals` filters on
`constants.STAGE_CLOSED_WON` — import the constant, don't re-type the
string.** Why it's a rule rather than a reminder: the filter was originally
documented here as "remember to add `AND sales_stage = '10 - Closed/Won'` at
each query site," and the site that forgot it (`app.py`'s `list_reps`
(`/api/reps`) `arr_total` subquery) shipped Lost-deal amounts as revenue
(fixed 2026-09). The literal now lives in exactly one place, so a new query
site inherits the right value by importing it; `reviews.py` and `top_items.py`
both do. `/api/closed-deals/summary`'s team-level query additionally filters
`WHERE se_rep_id IS NOT NULL` and reports `closed_won`/`closed_won_pct`
alongside `tech_win_pct` — Tech Win Rate's denominator is "closed deals with
an assigned SE," not "closed-won deals." `reviews.py` splits the same rows
into Closed-WON and Closed-LOST blocks in the LLM context: a lost deal stays
visible as SE evidence (a technical win can still close Lost) but never
reaches the revenue line.

**Rule: SE attribution for `tech_forecast_deals` comes from
`attribution.py`** — `EFFECTIVE_SE_ID_SQL` (or `LEAD_SE_ID_SQL` /
`ATTRIBUTED_SE_ID_SQL` when a caller needs to show which step resolved a
deal), and `effective_se_id(row)` for the Python-side equivalent. The
precedence is `assigned_se_rep_id` override > case-insensitive `lead_se_name`
match > opportunity_name→`deals.se_rep_id` fallback. Same history as above:
`list_reps`'s `tech_forecast_arr` subquery was hand-written with step 3 only
(fixed 2026-09-11), so reps attributed via steps 1-2 showed $0 despite real
forecasted ARR and the column's total didn't match the Tech Forecast page.
Step 2 matches `lower(trim(...))` on both sides, not bare `lower(...)`. The
sheet is hand-maintained and a single trailing space on a Lead SE cell was
enough to drop the match — which surfaces not as an error but as the deal
reporting "Unassigned" while its ARR quietly leaves that rep's total.
`db.py`'s `idx_se_reps_name_norm` indexes the same `lower(trim(name))`
expression: SQLite matches an index by its exact expression, so changing one
without the other silently drops back to a full scan per row. Anything beyond
whitespace ("NicDaSilva", "Da Silva, Nic") is deliberately NOT matched —
guessing risks booking revenue against the wrong person — and instead comes
back as `lead_se_unmatched` on the deal, which the UI shows as "SE not on
roster: <name>". That is a different problem from `needs_lead_se` (the sheet
names nobody) and the two must stay distinguishable: they used to render as
the same chip while the Needs Lead SE card, which keys off the raw name,
listed only one of them.

Don't re-write the COALESCE at a new call site — interpolate the constant
(it takes no caller input, and `db.py` carries the two indexes that keep it
fast: `idx_deals_opp_name` and the `lower(name)` expression index on
`se_reps`).

As of 2026-09-02, Presales Stage became a flat per-deal column (like Stage
or Account Region), not a group level — the sheet's underlying query was
restructured to expose it per-deal (genuinely blank for some deals not yet
staged) instead of as the old middle grouping level.

As of 2026-09-15, "Claude This q and next" dropped both "Lead Sales
Engineer" and "Deal Forecast Status" entirely — there is no grouping left
on this tab at all, and `tech_forecast_sync.py` has no `_GROUP_LEVELS`.
`lead_se_name` and `forecast_status` are always `NULL` in `tech_forecast_deals`
now; attribution falls through to `attribution.py`'s opportunity-name join
against `deals.se_rep_id` as the sole remaining signal. One consequence:
`tech_forecast_report.py`'s `build_needs_lead_se`, which reads the raw
`lead_se_name`, now flags every tech-forecast deal rather than genuinely
unassigned ones — a known, accepted side effect, not a bug to chase.

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
*previous* sync and sets `notes_stale` on the row if unchanged. It must be
evaluated on **both** sides of the fingerprint gate in `load_rows`: a
completely untouched deal matches its fingerprint and skips the upsert, and
that frozen row is precisely the one the flag exists to catch — computing
staleness only on the changed path meant "nobody has touched this in three
weeks" could never fire at all. Same reasoning as the org tags: both are
derived from a comparison, not from the row's own content, so the
fingerprint can't stand in for either.

Alongside the boolean, each sync stamps `notes_last_changed_at` with the
moment the Pre-Sales Next Steps text actually moved, and carries the old
value forward untouched while it hasn't. `notes_stale` alone only says
"unchanged since the previous sync", which can't distinguish a deal that
went quiet on Friday from one that went quiet in July — so the flag chip
reads "Stale 3 weeks" / "Stale 2+ months" off the timestamp. Rows synced
before the column existed keep a NULL stamp and fall back to the undated
"No update this week" wording: we genuinely don't know when they last
moved, and back-filling `now` would show a month-old deal as fresh.

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
`Subtotal` in the Lead SE column itself. Both are handled by the shared
`sheet_parse.strip_group_label`; if a future column gets added to the grouped
layout, check whether it needs the same treatment before trusting a raw sync.

`strip_group_label` returns **three distinct signals**, and a caller that
collapses any two of them reintroduces a shipped bug:

- a real name/label — a group boundary; resolve pending rows, set the fill;
- `""` (the default for a bare `-`) — a genuine "nobody assigned yet"
  boundary: reset the fill at this level and cascade the reset downward, so
  the next group can't inherit the previous one's name. `sheets_sync.py`
  passes `unassigned="Unassigned"` instead, which makes `-` a normal named
  group that forward-fills like any other lead. (`closed_deals_sync.py` no
  longer calls `strip_group_label` at all — its tab lost its grouping
  entirely on 2026-09-15, so `row.get("rep_name")` is always unset and
  `load_rows` falls back to `"Unassigned"` unconditionally.);
- `None` for a blank cell or a bare `Subtotal`/`Total` marker — row-shape
  noise, *not* a boundary. Inherit the current fill and keep buffering.
  Marker text can land one column over from its own level, so resetting on it
  discards deal rows still waiting on a late-arriving group name — that's
  exactly how NOVA Chemicals / MacEwan University lost their Lead SE
  (bf03fc7). Marker matching is an exact match on the stripped cell, never a
  substring scan: a substring test drops real opportunities named
  "TotalEnergies" or "Total Rewards Platform".

In a fresh Bash-tool session (no venv activation), `py`/`python` resolve to
the global interpreter, not this project's venv, so use
`venv/Scripts/python.exe <script>` rather than assuming the venv is on PATH.

That note used to say the symptom was `ModuleNotFoundError: No module named
'gspread'` on `py mcp_ingest.py`. That specific failure is fixed and the
diagnosis was wrong: the cause wasn't PATH, it was that `sheets_sync` and
`slack_sync` imported gspread/google-auth/slack_sdk at module scope, so the
credential-free MCP path — the primary one, which needs none of them — died
before running a line. Those imports now live inside the functions that
actually need a credential, and `tests/test_mcp_ingest.py` runs the whole
path in a subprocess with the packages blocked. **Don't hoist them back to
module scope**; the wrong interpreter will still bite you on other
dependencies, which is why the first paragraph stands.

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

`tech_forecast_report.quarter_bucket_detailed()` reuses `fiscal_quarter()` to
label a deal's target Technical Win date (Tech Win Date, falling back to Close
Date) as `current`/`next`/`overdue`/`later`/`None` relative to *today's*
fiscal quarter — this powers the Slack draft's Current Quarter / Next Quarter
split under "Come ready to discuss" and the Look Forward bucket order.
`overdue` (target quarter already closed) used to sink into `later`, which
meant the most urgent deals on the board got no SFDC note draft at all. The
older three-way `quarter_bucket()` is kept for `app.py`, which layers its own
overdue refinement on top of it; new code in that module calls the `_detailed`
form. `offset_quarter_key` (public now; `_offset_quarter_key` remains as an
alias for the pre-rename caller) shifts a `(fy, q)` sort-key tuple by N
quarters, wrapping year boundaries, and `next_fiscal_quarter_label()` is the
public one-call way to label the following quarter instead of chaining
`fiscal_quarter_sort_key` / `offset_quarter_key` / `quarter_label` by hand.

`build_tech_win_trend()` dedupes: a won deal lives in `closed_deals`
(`tech_win = 1`) *and* stays in `tech_forecast_deals` at Technical
Win/Closed-Won, so it used to be counted and totalled twice in its quarter.
It also reports `closed_lost_count` — a technical win that closed Lost stays
visible in `count` (it happened) but contributes nothing to `amount` — and
labels undated rows as an explicit `"Undated"` bucket sorted last, rather
than a `null` quarter that sorted ahead of every real one.

`build_weekly_deltas(current_rows, prior_states)` is pure: the caller passes
the rows it already holds plus the previous snapshot's parsed
`deal_states_json`. It used to take `db` and re-read `tech_forecast_deals` in
a second transaction, so a sync landing mid-request could leave the deltas
describing a different set of rows than the metrics beside them. The list
builders (`build_needs_lead_se`, `build_missing_notes`, `build_sfdc_updates`)
take a `limit` (`DEFAULT_LIST_LIMIT = 25`) instead of returning unbounded
lists.

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

## Frontend theming & charts

**`UI_STANDARDS.md` is the reference** — tokens, measured contrast ratios, the
stage ramp, component patterns. It holds the values; this section holds only
the rules, and no hex code appears in both. A value written down twice drifts,
which is the same lesson as the stage strings and the attribution query above.

The standard is enforced by `tests/test_ui_contrast.py`, which parses
`style.css` and fails on a violation — so these are checked, not remembered.

Two rules matter more than the rest, because breaking either is invisible in
whichever theme you happen to have open:

- **Status hues are per-theme.** `--green`/`--amber`/`--red`/`--purple`/
  `--teal` (and `--text-muted`) are declared in BOTH `:root` and
  `body.light-mode`, with different values. They used to be declared once,
  stepped for navy, and inherited by light mode — where amber sat at 2.03:1
  while carrying the "No update this week" flag. Adding a status colour means
  adding it twice, and adding it to the test's `_SEMANTIC` list.
- **Light mode's surfaces stay distinct.** `--bg-app`/`--bg-card`/
  `--bg-card-hover`/`--bg-input`/`--bg-tag` were all `#FFFFFF`, which didn't
  just look flat: hover feedback stopped working (hover colour == base colour)
  and the progress-bar track vanished, so a rep at 0% rendered as empty space.

The rest, in brief — rationale and values in `UI_STANDARDS.md`: presales stage
is ordinal so its chart fills step along one hue with "Untagged" as a recessive
neutral; legend and tooltip text take theme ink, never the series colour (the
pale end of a ramp is a fill colour, not a legible text colour); money columns
are `numeric: true`; deal flags carry a severity rather than three identical
ambers; and `notes_stale` is a SQLite integer, so guard it with `!!` in JSX or
React renders a literal `0`.

## Git workflow

Per Claude Leroux (2026-09-15): keep `origin/main` always up to date, not
just local. Commit and push after any meaningful change — don't batch
unpushed commits or wait for the user to ask. This supersedes the prior
"no GitHub by default" rule (which had scoped push authorization to the
React migration only); that scoping no longer applies.

## Sub-agents & delegation

### Sync, upload & bulk-file work

**Standing rule, not a reminder: for any data upload, sync, or bulk file
work on this project, delegate to the matching subagent below — never run
the fetch → payload → ingest flow inline in the main thread.** This applies
every session, unprompted; don't wait for the user to say "use a subagent."

Six Claude Code custom agents live in `.claude/agents/` and are auto-loaded in every Claude Code session opened against this project directory:

| Agent | File | Trigger |
|---|---|---|
| `tech-forecast-sync` | `.claude/agents/tech-forecast-sync.md` | "sync tech forecast", "refresh tech forecast" |
| `deals-sync` | `.claude/agents/deals-sync.md` | "sync deals", "refresh pipeline" |
| `closed-deals-sync` | `.claude/agents/closed-deals-sync.md` | "sync closed deals", "refresh closed deals" |
| `slack-sync` | `.claude/agents/slack-sync.md` | "sync Slack", "refresh Slack notes" |
| `calendar-sync` | `.claude/agents/calendar-sync.md` | "sync calendar", "refresh Win Labs", "sync hiring interviews from calendar" |
| `hiring-slack-sync` | `.claude/agents/hiring-slack-sync.md` | "sync hiring Slack", "refresh recruiting notes", "sync Cara's DMs" |

Each agent handles the full MCP-assisted sync flow for its data type: confirm live tab name/gid (sheet kinds), fetch data, write temp JSON payload, run `mcp_ingest.py` via `venv/Scripts/python.exe`, delete temp file, report result. Tab gid values are stable even when tab names change — sheet agents always confirm the live name via `get_spreadsheet_info` before reading. `calendar-sync` and `hiring-slack-sync` have no credential-based path at all (unlike the sheet/Slack-notes syncs) — MCP-assisted is the only path, since there's no service account or Slack App configured for Calendar/recruiting-DM access either.

Every agent must report back to the main thread with a **brief summary
only** — synced/unchanged/deleted counts and any errors, never the raw
payload, full script stdout, or row-level data. If a subagent's reply starts
looking like a data dump, that's a bug in the agent's instructions to fix,
since it erases the whole point of delegating.

The `/sync-se-hub` skill (`.claude/skills/sync-se-hub/SKILL.md`) is the slash-command entry point — it dispatches to these six agents in parallel (all six by default, or a subset if the user names specific kinds) rather than duplicating any sync logic itself.

### General project work (everything else)

**Standing rule, not a reminder: for any non-trivial project work that
isn't sync/upload/bulk-file work — feature implementation, bug fixes,
refactors, UI/frontend changes, research/investigation, doc updates —
delegate to a subagent by default, unprompted, every session.** Don't do
this work inline in the main thread; that's what burns context and
triggers premature compaction.

**Delegate to:** the built-in `general-purpose` Agent type. No custom
agent file is needed for this — `general-purpose` already has full tool
access, and when dispatched against this project directory it
automatically loads this same CLAUDE.md, so it inherits the
"brief summary only" reporting rule and the `progress.md` protocol for
free.

**Exception:** trivial actions (a quick spot-check, a single-line read,
confirming a subagent's claimed output) can stay in the main thread —
that's what direct tool use is for, not doing the actual work.

**Reporting:** same brief-summary-only bar as the sync rule above — report
pass/fail and what changed, never a raw diff or full command output dump.

**Multi-step tasks:** populate `progress.md` (see "progress.md — surviving
context compaction" below) as work progresses, not just at the end — this
is what lets delegated work survive compaction cleanly.

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
| `app.py` | Flask routes — JSON error handler (`LOG_LEVEL` env sets log level; exception detail goes to the log, never the browser), bounded/validated query params, 400/404 on the assign routes |
| `db.py` | SQLite schema + thread-local connections; query indexes; `utc_now_iso()` (use it for any column whose schema default is UTC `datetime('now')` — `datetime.now()` writes local time and disagrees with the row beside it); `prune_snapshots()`; `schema_version`-gated one-time cleanups. Schema includes `calendar_events` (`UNIQUE(category, event_id)`) and `recruiting_notes` (`UNIQUE(message_ts, channel_id)`), both additive, no `schema_version` bump needed |
| `constants.py` | Canonical SFDC/sheet literals: `STAGE_CLOSED_WON`, `PRESALES_TECH_WIN`, `FORECAST_RISK` — import, never re-type |
| `attribution.py` | The single copy of the three-step SE precedence: `EFFECTIVE_SE_ID_SQL`, `LEAD_SE_ID_SQL`, `ATTRIBUTED_SE_ID_SQL`, `effective_se_id(row)` |
| `sheet_parse.py` | Shared grouped-sheet parsing/loading for the three sheet syncs: `parse_amount`, `parse_date`, `strip_group_label`, `is_marker_cell`, `map_header`, `build_sheet_key`, `row_fingerprint`, `match_rekeyed_rows`, `guard_row_shrink`, `delete_keys`, `write_setting`. No db/Flask/gspread imports |
| `sheets_sync.py` | Google Sheets "Lead SE Pipeline SFDC" tab → `deals` table |
| `closed_deals_sync.py` | Google Sheets "Canada SE Closed This Fiscal Year" tab (closed-deal export, Won and Lost, technical-win flag) → `closed_deals` table |
| `tech_forecast_sync.py` | Google Sheets "Claude This q and next" tab (Technical Forecast pipeline, flat layout as of 2026-09-15 — no Lead SE/Deal Forecast Status grouping, Presales Stage flat per-deal) → `tech_forecast_deals` table; also captures the daily snapshot used for week-over-week deltas |
| `tech_forecast_report.py` | Pure aggregation/report logic for the Technical Forecast page + Slack preread (bucket totals, key metrics, top deals w/ fiscal-quarter bucket + heuristic discussion question, weekly deltas, needs-Lead-SE list, missing-notes list) and the Actions page's SFDC Updates card (`build_sfdc_updates`/`draft_sfdc_note` — rule-based per-opportunity Salesforce note drafts) — no Flask dependency, reused by `app.py` and `tech_forecast_sync.py` |
| `slack_sync.py` | Slack `search.messages` → `slack_notes` table |
| `calendar_sync.py` | MCP-assisted only — loads already-classified Google Calendar events (`win_lab` / `hiring_interview` / `customer_meeting`, classified by the `calendar-sync` agent) → `calendar_events` table |
| `recruiting_sync.py` | MCP-assisted only — loads Slack DM search matches with recruiter Cara McArthy → `recruiting_notes` table (no `se_rep_id`, she isn't an SE report) |
| `mcp_ingest.py` | CLI bridge — loads MCP-fetched JSON into the DB, no credentials needed |
| `seed_arr_targets.py` | One-off: sets `se_reps.arr_target` by name (FY26 H2: Sean/Rishika $2.5M, Valentin/Nic $1.5M) |
| `models.py` | Canonical model identifiers — `LITELLM_MODEL`, `BEDROCK_MODEL_ID`; the only place a model string is written |
| `bedrock_agent.py` | AWS Bedrock Converse tool-use loop computing SE metrics into `agent_metrics` (proof-of-concept; not imported by `app.py` yet). Auth via the existing Okta SSO → IAM Identity Center federation, no new credentials |
| `reviews.py` | LiteLLM-backed review drafting — the LLM context splits Closed-WON from Closed-LOST so lost deals stay visible as SE evidence but never reach the revenue line |
| `top_items.py` | Top Items weekly summary — pure scaffold/persistence helpers, no Flask dependency (`DEFAULT_WINS_LIMIT = 25`). Auto-fills Technical Wins (`closed_deals`), Win Labs and Hiring/Customer Meetings (`calendar_events`, `recruiting_notes`) over the same 7-day lookback; Canadian Public Sector stays a manual placeholder |
| `UI_STANDARDS.md` | Frontend design system — tokens with measured contrast, stage ramp, component patterns. The values live here; CLAUDE.md carries the rules |
| `tests/` | pytest suite — run with `python3 -m pytest` (`venv/Scripts/python.exe -m pytest` on the user's machine) |
| `frontend/` | React (Vite) frontend — `src/api.js` (fetch helpers), `src/App.jsx` (shell/router), `src/pages/`, `src/components/`, `src/style.css` (ported Okta dark theme). `npm run build` in `frontend/` produces `frontend/dist`, which is committed and served by Flask at `/` (see `app.py`'s `static_folder`) |

## Not built yet

Gong integration — user is wiring this up themselves.
