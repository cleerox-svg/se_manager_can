# SE Manager Hub

A dashboard for an SE manager to track the team's current-quarter pipeline,
recent Slack activity per rep, and draft mid-year/check-in reviews — modeled
on [NaughtRFP](../rfp-responder)'s stack and Okta dark-theme UI.

## What it does

- **Actions** — a card-grid launcher (`action-card-grid`, one `action-card`
  per action with an icon, title, and description) that opens a focused
  module in place when clicked, rather than listing every action's UI at
  once. Three cards today: **Team Prep Message** (Slack-ready Monday-call
  draft from the week's forecast), **SFDC Updates** (proposed SE Manager
  note per open opportunity, current + next quarter), and **Top Items**
  (drafts the manager's weekly Top Items summary — Hiring, Customer
  Meetings/Win Labs, Canadian Public Sector, and Other/Technical Wins —
  matching the format of the team's shared Top Items Google Doc). Top
  Items' "Generate" button scaffolds a starter draft: Other/Technical Wins
  auto-fills from `closed_deals` closed in the last 7 days, and Win Labs /
  Hiring / Customer Meetings auto-fill the same way from `calendar_events`
  (classified by the `calendar-sync` agent into `win_lab` /
  `hiring_interview` / `customer_meeting`) and `recruiting_notes` (Slack DMs
  with recruiter Cara McArthy, via `hiring-slack-sync`) — Hiring combines
  calendar interviews with Slack recruiting context, and Hiring/Customer
  Meetings are flagged `_(heuristic — review before sending)_` since neither
  is a high-confidence signal the way a "Win Lab" title or a closed-won
  stage is. Canadian Public Sector remains the one editable placeholder.
  "Save" upserts it to
  `top_items_entries` keyed by today's date, and "Copy to clipboard" pastes
  it straight into the shared doc. This is a manual weekly action, not an
  automated cron — the Flask app has no Calendar/Gmail/Slack
  service-account credentials, so full email/calendar/Slack alignment
  needs a live Claude Code session's MCP tools, same as the sheet/Slack
  sync pattern above (Win Labs/Hiring/Customer Meetings have no
  credential-based path at all — MCP-assisted via `calendar-sync` /
  `hiring-slack-sync` is the only way these three sections fill in).
- **Dashboard** — team-wide rollup sourced from Technical Forecast data, no
  individual SE names shown at top level. Three stat cards (closed deals,
  % closed won, % technical win, from `/api/closed-deals/summary`'s
  name-free `team` object), a stacked ARR-trend area chart over the last 180
  days of `tech_forecast_snapshots` (Technical Win / In Flight / Untagged —
  `/api/dashboard/arr-trend` takes `?days=`, 7 to 1095, to widen or narrow
  that window; it used to read the whole unbounded history), a stage-funnel
  bar chart per confidence (reusing `tech_forecast_report.build_breakdown()`),
  and a quarter-over-quarter Technical Win ARR bar chart grouped by Okta
  fiscal quarter (see "Fiscal quarters" in CLAUDE.md). The tech-win trend
  counts a deal once even when it appears in both `closed_deals` and
  `tech_forecast_deals`, reports `closed_lost_count` separately (a technical
  win that closed Lost stays visible in the count but adds no revenue), and
  puts undated rows in a labeled "Undated" bucket sorted last. Built with
  `recharts`.
- **Team** — roster of SEs derived from the sheet's "Lead Sales Engineer"
  column, with an active/inactive toggle (used to mark departed reps —
  their historical deals stay visible, they just don't show up as a current
  direct report). Also the aligned hub for the manager's Team ↔ Technical
  Forecast workflow: each row shows Tech Forecast ARR (that rep's share of
  the technical pipeline, attributed live — see Technical Forecast below),
  an ARR-vs-target progress bar for the full fiscal year (target editable
  in place), and the current half's review status (Not started / Draft /
  Final), clickable to expand an inline editor with Generate draft / Save
  draft / Mark final — the same actions as the Person page's Review tab, so
  write-ups can be updated without leaving the Team page.
- **Person detail** — a rep's open deals, recent Slack activity (via
  `search.messages` for their user ID), and an AI-drafted review for the
  current half, editable in-app. The Review tab shows the same ARR-vs-target
  progress bar (full-fiscal-year closed-won ARR vs. the rep's target) and a
  "Mark final" button alongside "Save draft" — status is reflected as a
  badge next to the tab label and on the Team page.
- **Technical Forecast** — weekly Technical Forecast Call view modeled on
  Okta's Presales Technical Win Process, synced from the standalone
  Technical Forecast sheet's tab (currently "Canada SE Tech Forecast
  current and next q" — auto-refreshes every 24h, tab names get renamed by
  the user from time to time, see CLAUDE.md). As of 2026-09-15 the sheet dropped both "Lead Sales
  Engineer" and "Deal Forecast Status" entirely — there is no per-deal SE
  or forecast-confidence signal left in the tab at all, so every synced row
  now attributes purely via the opportunity-name→`deals.se_rep_id` fallback
  (see "SE attribution" below) rather than a name match, and forecast
  status is always blank. Presales Stage remains a flat per-deal column
  (not a group level), genuinely blank for deals not yet staged. The
  sheet's query also carries deals belonging to Greg Rainbird's sales org
  (a different team) — those are kept but tagged with a `product`/`segment`
  pair during sync so they stay visible while clearly marked as another org's,
  even when a now-inactive Lead SE of ours is still attached. A "Sync now" button next to Present mode copies a ready-made
  sync request to the clipboard for pasting into a Claude Code chat (no
  live in-app fetch —
  see "Data model" below). Five sections: Macro View (stat-grid — Current
  Quarter ARR and Next Quarter ARR (each labeled with its Okta fiscal
  quarter, e.g. "FY26-Q3", replacing the old single opaque Total Tech
  Forecast ARR figure), Forecasted Risk count, stale-notes count, and Needs
  Lead SE count/$ — all 5 cards are clickable, scrolling to (and
  auto-expanding, if collapsed) the matching section below), Look Back (recent technical wins, blending closed `tech_win`
  deals with open deals already at "6 - Technical Win", grouped by Okta
  fiscal quarter — most recent first, FY starts Feb 1, see CLAUDE.md — then
  by SE, then by amount within each SE. Each quarter and each SE sub-group is
  a collapsible `<details class="flyout">` (open by default) whose summary
  line always shows the win count and dollar total, so the totals stay
  visible even when collapsed. A group of wins with no SE
  attributed gets a "No SE" badge on its subheader; individual still-open
  wins with no fresh SE update since the last sync get a per-row
  "No new notes" badge — closed wins never get that flag since the sheet's
  closed-won export has no notes columns at all. Each row's Status badge
  ("Closed win" vs. "Tech win (open)") is driven by `sales_stage ===
  '10 - Closed/Won'`, not by which table the row came from — a row can come
  from either `closed_deals` or `tech_forecast_deals` and still need the
  "Tech win (open)" badge if it hasn't actually closed won yet. Each row now
  carries that classification explicitly from the API —
  `win_status` (`closed_won` / `closed_lost` / `open`), `counts_as_revenue`,
  and `revenue_amount`, which is 0 for anything that isn't closed won — so a
  technically-won but commercially-lost deal stays on the page without
  inflating a dollar total), Look Forward &
  Inspect (open technical pipeline table, grouped into collapsible sections —
  same `<details class="flyout">` pattern as Look Back — by target Technical
  Win date's fiscal-quarter bucket, in fixed order Overdue → Current Quarter →
  Next Quarter → Later/Unscheduled; within each group, deals are sorted by
  Amount (ARR) descending. Each group's summary line shows the bucket label,
  deal count, and dollar total, same as Look Back's group headers. Each deal
  renders as a full-width card (not a table row) so its notes don't need
  truncation or a tooltip: a header with the opportunity name/link, AE, Stage
  (colored badge — green for Closed/Won, red for Closed/Lost, blue for
  still-open), Presales Stage, Confidence, Billing State/Province, and
  Amount; a meta row with an SE dropdown (with a "No Lead SE (sheet)" badge
  when the sheet itself has no Lead SE set), Flags, and Tech Win Date; and a
  responsive 3-column notes section showing the full text of Pre-Sales
  Notes, Pre-Sales Next Steps, and SE Manager Notes side by side, wrapping to
  fewer columns on narrower screens), and Wrap-Up & Risk (Forecasted Risk
  and/or stale-notes deals, same SE display as Look Forward & Inspect).
  A deal is flagged stale ("No update this week")
  when its Pre-Sales Next Steps text is unchanged from the previous sync —
  not by parsing dates in the freeform text. See "Actions" below for the
  weekly Slack preread draft (moved off this page into its own tab).
  Opportunity links in the draft (`_slack_opp_link`) render as plain
  `Name (https://...)` text rather than Slack mrkdwn `<url|name>` syntax,
  since this is a copy-paste-into-compose-box workflow, not a
  `chat.postMessage` send — mrkdwn link syntax only gets parsed server-side
  on Web API sends, so pasting it literally let Slack's client-side
  auto-linker swallow the `|name>` into the URL and mangle it. Right
  after Key Metrics, the draft includes a static, team-wide Command of the
  Message recital ("The Mantra" — `tech_forecast_report._MANTRA`): the same
  six-part Challenges->Outcomes / Required Capabilities / Metrics / How We
  Do It / How We Do It Better / Proof Points script every time, anchored on
  Okta's "Identity security - breach protection" Value Driver. It's
  deliberately one static script rather than per-deal — per-deal would need
  new Value-Driver-tagging fields that don't exist yet. The
  "Come ready to discuss" section is split into Current Quarter / Next
  Quarter sections (titled with each quarter's Okta fiscal-quarter label,
  e.g. "Current Quarter — FY26-Q3") by each deal's target Technical Win
  date's fiscal quarter (`tech_forecast_report.quarter_bucket`, relative to
  today's fiscal quarter; the "later" bucket still appears further down,
  ungrouped). Within each quarter section, deals are grouped by Lead SE
  (case-insensitive, so a name typed with different casing in the sheet
  still groups together) and the SE groups are sorted highest-to-lowest by
  that SE's aggregate ARR in the section, so the manager sees whoever has
  the most on the line first; deals with no Lead SE on file are grouped
  under a literal "No Lead SE on file" heading, always last regardless of
  its ARR. Each SE sub-heading shows their name and aggregate ARR, plus a
  plain-text alias (e.g. `@Rishika`) for exactly the 4 reps who report to
  Claude Leroux — Rishika Kondaveeti, Nic Da Silva, Sean Keleher, Valentin
  Bourneuf — via a hardcoded name→alias map
  (`tech_forecast_report._SLACK_ALIAS_BY_NAME`), not a real Slack `<@U...>`
  mention: that syntax only resolves as a live mention when sent via the
  Slack API, not when pasted as literal text into Slack's compose box, so it
  read as broken/dead text once copy-pasted. Every other SE (and the "No
  Lead SE on file" group) just shows their plain name, no mention at all —
  this is deliberately scoped to the 4 direct reports, not tied to whether
  `se_reps.slack_user_id` is on file. Each deal line keeps a
  heuristic, rule-based discussion question (`build_discussion_question` —
  not LLM-generated; picks from missing-next-steps / stale-notes / at-risk /
  stage-based prompts in that priority order, since each is a stronger
  signal than the last, and phrased around Command of the Message /
  Opportunity Analysis & Coaching Guide qualification pillars — compelling
  event, Champion, Decision Criteria/Process, Proof Points — rather than
  generic stage-progress language) but no longer repeats the SE's name per
  deal line, since it's now implied by the sub-heading above it. A separate
  "Missing notes" section lists every open (non-Technical-Win) deal across
  the full pipeline with a blank Pre-Sales Next Steps field, not just the
  ones in "Come ready to discuss." A "Present mode" toggle hides the
  sidebar/topbar for clean screen-sharing during the Monday call. A
  light/dark theme toggle (sidebar footer) persists via `localStorage`.
- **Actions** — its own tab with a "Team Prep Message" card (moved off the
  Technical Forecast page). A "Generate draft" button formats the weekly
  Slack preread (`/api/tech-forecast/preread`) into a ready-to-post message
  in an editable textarea plus a "Copy to clipboard" button — copy-paste
  only, no direct-to-Slack send (the configured Slack token is
  `search.messages`-scoped only) and no LLM call yet (no `LITELLM_API_KEY`
  configured), so the draft is built with plain string templating in
  `tech_forecast_report.build_slack_draft` rather than an AI prompt; swapping
  in an LLM polish pass later only needs to change that one function. A
  second card, "SFDC Updates," drafts a per-opportunity note ready to paste
  into Salesforce: `GET /api/tech-forecast/sfdc-updates` returns every
  commercially-open deal (`sales_stage != "10 - Closed/Won"`) in the current
  or next fiscal quarter, each with its opportunity name (doubling as the
  account label, since `tech_forecast_deals` has no true `account_name`
  field), Salesforce link, and a rule-based proposed note
  (`tech_forecast_report.draft_sfdc_note` — same no-LLM-configured reasoning
  as the discussion-question heuristic above) that prefers a Technical Win
  confirmation, then the newest SE Manager Notes entry, then the newest
  Pre-Sales Notes entry, then the raw Pre-Sales Next Steps text, then a
  generic fallback. Every drafted note is prefixed with `CL MM/DD/YYYY : `
  (today's date, computed at call time, with a space before the colon) to
  match the initials+date convention already used in the sheet's hand-typed
  note history. Same editable-textarea-plus-Copy-button UX as Team Prep
  Message.
- **SE attribution (Team ↔ Technical Forecast)** — the sheet now carries
  real Lead SE attribution natively (`lead_se_name`), so `app.py` resolves
  each deal's effective SE with this precedence: (1) an explicit manager
  override (`assigned_se_rep_id`, set via the Technical Forecast page's SE
  dropdown — always wins), (2) `lead_se_name` matched case-insensitively
  against `se_reps`, (3) an opportunity-name join against
  `deals.se_rep_id`, kept as a fallback for the rows the sheet hasn't
  attributed yet, (4) "Unassigned". Separately, `needs_lead_se` reports the
  literal "sheet has no Lead SE set" signal for a deal, independent of
  whatever attribution the app manages to resolve — this drives the Needs
  Lead SE stat card and per-row badge, and the manager's own override
  doesn't clear it (it's about what the sheet itself says, not what the app
  has resolved).
- **Slack preread** — `GET /api/tech-forecast/preread` assembles an
  Executive Takeaway, Key Metrics, Pipeline Breakdown, Top deals (excluding
  Technical Win/Final Due Diligence), week-over-week deltas, and the list
  of deals needing a Lead SE into one payload modeled on the "Tech Win
  Forecast & Risk Summary" format the manager's own chain uses. No in-app
  send button — Claude drafts the Slack message from this payload on
  request and posts it via the Slack MCP tools after review.
- **Salesforce links** — wherever an opportunity name is shown (Technical
  Forecast tables and the Slack preread draft), it links out to that deal's
  Salesforce Lightning page when the sheet carried an Opportunity ID;
  otherwise it renders as plain text, no warning shown.
- **Settings** — sync status/buttons for Google Sheets and Slack, and a
  placeholder for Gong (not built — planned as a future integration).

## Stack

Python 3.14 (`py`, not `python`) + Flask + SQLite3, React (Vite) frontend
under `frontend/`, built to `frontend/dist` and served by Flask at `/`.
Review drafting calls the LiteLLM proxy (`https://llm.atko.ai`) using the
same client pattern as NaughtRFP. Sidebar nav/theme-toggle icons are
`lucide-react`.

Shared backend modules, each the single source for something that used to be
copy-pasted per file:

- `constants.py` — the SFDC/sheet literals that drive revenue math
  (`STAGE_CLOSED_WON`, `PRESALES_TECH_WIN`, `FORECAST_RISK`). These were
  re-typed at roughly fifteen query sites, which is how a Closed/Lost amount
  once got counted as revenue.
- `attribution.py` — the three-step SE attribution precedence as SQL
  (`EFFECTIVE_SE_ID_SQL` and its component parts) plus a Python equivalent,
  so a new query can't implement only part of it (see "SE attribution" above).
- `sheet_parse.py` — grouped-sheet parsing shared by the three sheet syncs:
  amounts and dates, group-header labels, row keys and fingerprints, the
  header check and the truncated-fetch guard. No db/Flask/gspread imports.
- `top_items.py` — Top Items scaffold/persistence, mirroring
  `tech_forecast_report.py`'s pure-logic, no-Flask convention.
- `calendar_sync.py` / `recruiting_sync.py` — MCP-assisted-only loaders (no
  credential-based path) for `calendar_events` and `recruiting_notes`,
  same upsert shape as `slack_sync.py`'s MCP-assisted entry point.

## Run it

```bash
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
cd frontend && npm install && npm run build && cd ..
py app.py
```

`GET /` serves the built React app from `frontend/dist` (Flask's static
folder is pointed at it — see `app.py`). `frontend/dist` is committed to the
repo, so `py app.py` works right after a fresh clone without needing Node —
but re-run `npm run build` inside `frontend/` after pulling any change that
touches `frontend/src/`, since the committed build won't update itself.

For frontend development with hot reload, run `npm run dev` inside
`frontend/` (proxies `/api/*` to the Flask server on port 5050) alongside
`py app.py`.

`LOG_LEVEL` (default `INFO`) sets the app's log level. The app logs through
`logging` and returns JSON for every error, including unhandled ones — the
browser gets a generic message and the traceback goes to the log, since
exception text can carry a service-account path or a token fragment. If a
request fails, the log is where the reason is.

## Running the tests

```bash
python3 -m pytest
```

(`venv\Scripts\python.exe -m pytest` on the user's machine, where `py`
resolves to the global interpreter.) Config lives in `pytest.ini`; the suite
itself is under `tests/`, and covers the pure backend helpers — the shared
sheet parsing and the fiscal-quarter math among them. Run it after touching
`sheet_parse.py`, the three `*_sync.py` modules, `tech_forecast_report.py`,
`constants.py` or `attribution.py`.

It also covers the frontend palette: `tests/test_ui_contrast.py` parses
`frontend/src/style.css` and fails if a colour token drops below WCAG AA, if a
status hue is declared for only one theme, if light mode's surfaces collapse
onto one white, or if the presales-stage ramp stops reading in order. Those are
failures you can't see in whichever theme you happen to have open — a shared
amber sat at 2.03:1 on white for a while, carrying the "No update this week"
flag — so they're checked rather than remembered. The palette itself, with the
measured ratios and the patterns built on it, is in
[UI_STANDARDS.md](UI_STANDARDS.md); run the suite after editing `style.css`.

Data gets in via one of two paths — see [SETUP.md](SETUP.md):
- **Ask Claude to sync** (no setup) — Claude uses its own Google Sheets /
  Slack MCP access and loads the result with `mcp_ingest.py`.
- **Automated background sync** (optional) — a Google service account +
  Slack App/user token, wired to the Settings-page Sync buttons.

## Data model

- `se_reps` — roster, Slack user ID, active/inactive flag, `direct_report`
  flag (marks Claude Leroux's current direct reports — backfilled by name in
  `db.py`'s migration on every startup, not yet editable from the UI),
  `arr_target` (full-fiscal-year closed-won ARR target, manager-set —
  seeded once via `seed_arr_targets.py`, editable in place from the Team
  page). A Lead SE name the deals sync sees for the first time is inserted
  **inactive**, so a new (or typo'd) name never becomes a current direct
  report on its own — activate it from the Team page after a look.
- `deals` — synced from the Team Tracking Sheet's open-pipeline tab, one row
  per open opportunity.
- `closed_deals` — synced from the standalone closed-deal export sheet's
  tab ("Tech wins and losses"), one row per closed opportunity —
  both Closed/Won and Closed/Lost, not won deals only — flagged `tech_win`
  when Presales Stage is "6 - Technical Win". Loaded the same MCP-assisted
  way as `deals` (`py mcp_ingest.py closed_deals <json_file>`), and folded
  into `reviews.py`'s LLM context — split into Closed-WON and Closed-LOST
  blocks, so a lost deal still counts as SE evidence (the technical win
  happened) without its amount reaching the revenue line — so future
  generated drafts lead with real closed-deal/technical-win evidence. Also carries `opportunity_id` (for
  Salesforce links) and `sales_stage` (the sheet's "Stage" column, either
  "10 - Closed/Won" or "11- Closed/Lost") alongside `tech_win`, distinguishing
  actual Closed Won status from the Tech Win flag. `/api/closed-deals/summary`
  aggregates both into win-rate percentages — team-wide and per-rep —
  rendered as `% Closed Won` / `% Tech Win` bars on the Technical Forecast
  page; both percentages vary meaningfully by rep since the tab mixes Won and
  Lost outcomes. A "My team" / "All reps" toggle drives the whole Technical
  Forecast page's data fetch — deals, recent wins, and every derived ARR/win-rate
  total on the page, not just this card — passing `?direct_report=1` to scope
  the numbers to `se_reps.direct_report` reps only ("My team," the default);
  omitting the param (or `0`) keeps today's unfiltered "All reps" view. The
  filter resolves the *effective* SE (`attribution.py`'s three-step precedence),
  not the raw `se_rep_id` column, so deals attributed via manual override or
  Lead SE name match are still scoped correctly. The team-wide block shows two figures side by side: the
  all-time rate across the whole sheet, and a second rate scoped to deals
  closed within the current Okta fiscal quarter (`team_current_quarter`,
  labeled with that quarter, e.g. "FY26-Q3") — added since the all-time
  figure alone reads as "recent" performance when it actually spans the
  whole season. Per-rep breakdown stays all-time only. The 2026-09-15
  reformat briefly dropped the tab's "Team Member Name" column (and the old
  three-level Team Member Name > Team Role > Region grouping with it) down
  to a flat single-manager export, leaving no per-deal SE signal for one
  day. As of 2026-09-16 the sheet carries a flat "Lead Sales Engineer"
  column instead, which is what `rep_name` is sourced from now — "Manager"
  is constant (the SE Manager) but "Opportunity Owner" varies per deal since
  it's the Account Executive, not the SE, so neither feeds `rep_name`. Rows
  without a "Lead Sales Engineer" value still fall back to
  `rep_name = "Unassigned"` (`se_rep_id = NULL`). Closed-won vs. closed-lost
  detection is unaffected, since it keys on `sales_stage`, not `rep_name`.
- `tech_forecast_deals` — synced from the standalone Technical Forecast
  sheet's tab, one row per open deal in the technical-win pipeline. As of
  the 2026-09-15 reformat, the sheet dropped "Lead Sales Engineer" and
  "Deal Forecast Status" entirely — `lead_se_name` and `forecast_status` are
  always stored NULL now (the column mappings and group levels stay in
  `tech_forecast_sync.py` for forward compatibility, in case the columns
  come back, but nothing currently populates them), so every row attributes
  via the opportunity-name→`deals.se_rep_id` fallback (see "SE attribution"
  above) rather than a name match, and `tech_forecast_report.py`'s
  `build_needs_lead_se` — which reads the raw sheet name, not the resolved
  attribution — now flags every deal rather than genuinely unassigned ones.
  What's left: Presales Stage — a flat per-deal
  field, genuinely blank for un-staged deals — Confidence and Billing
  State/Province,
  Technical Win Date, overall Stage, Pre-Sales Notes, SE Manager Notes,
  Pre-Sales Next Steps, plus a manually-set `assigned_se_rep_id`
  override — see "SE attribution" above).
  Loaded the same MCP-assisted way (`py mcp_ingest.py tech_forecast
  <json_file>`) — the Technical Forecast page's "Sync now" button is a
  clipboard reminder for this workflow, not a live fetch, since no Google
  service account is configured (see SETUP.md Option B). Each sync diffs
  incoming Pre-Sales Next Steps against the previously-stored value per row
  to set `notes_stale`, and also captures a same-day snapshot (see
  `tech_forecast_snapshots` below).
  Sync is delta-aware: `load_rows` pre-loads every existing row's stored
  MD5 fingerprint (`row_fingerprint`, hashed from the 16 mutable text
  fields plus parsed close date/technical win date/amount) in one query,
  then skips the DB write entirely for any incoming row whose fingerprint
  is unchanged — no wasted writes, and `_capture_snapshot` only fires when
  at least one row actually changed or was deleted. `notes_stale` and the
  cross-org `product`/`segment` tags are re-evaluated on both sides of that
  fingerprint check: both are derived from a comparison rather than the row's
  own content, and a completely frozen deal — the one staleness exists to
  catch — is exactly the row the fingerprint skips. See "Sync behavior"
  below for what a sync returns and what can stop it.
  Each sync also stamps `notes_last_changed_at` when the Pre-Sales Next Steps
  text actually moves, which is what lets the flag chip say "Stale 3 weeks"
  rather than the undated "No update this week". Deals synced before that
  column existed keep a NULL stamp and show the old wording.
- `tech_forecast_snapshots` — one row per sync day, holding that day's
  bucket totals and per-deal state as JSON — the baseline
  `tech_forecast_report.build_weekly_deltas` diffs the next sync against to
  produce the preread's "Key Changes vs Last Week" section. The per-deal
  state includes each deal's close and technical-win dates, so
  `build_quarter_arr_history` can re-bucket past snapshots and chart how this
  quarter's forecast ARR built up; that feeds the sparkline and the "since
  last sync" delta on the Technical Forecast ARR tiles. Every point is
  measured against *today's* quarter, so the line doesn't silently rebase at
  a quarter boundary, and snapshots taken before those dates were recorded
  are skipped rather than plotted as $0.

  **The tiles have a cold start — expect a day, not a re-sync.** A snapshot
  row upserts on `snapshot_date`, so every sync in one day writes the *same*
  row: three syncs today still produce one history point. The sparkline needs
  two points and the delta deliberately compares against an earlier *day*, so
  neither appears until your next sync on a following day. Re-running the sync
  will not bring them up. Snapshots written before the target dates were
  recorded don't count toward the two, so the clock starts at the first sync
  on this code. To check a snapshot is the new format:

  ```bash
  sqlite3 se_manager_hub.db "
  SELECT snapshot_date,
         CASE WHEN instr(deal_states_json,'technical_win_date') > 0
              THEN 'yes' ELSE 'NO - old code' END AS has_target_dates
  FROM tech_forecast_snapshots ORDER BY snapshot_date DESC LIMIT 5;"
  ```
- `slack_notes` — synced from Slack search per rep.
- `calendar_events` — Google Calendar events, MCP-fetched and classified
  by the `calendar-sync` agent into `win_lab` / `hiring_interview` /
  `customer_meeting` before load, one row per (`category`, `event_id`).
  Feeds the Top Items scaffold's Win Labs and Hiring/Customer Meetings
  sections; the latter two categories are heuristic (title/description
  keyword scan, or ≥1 non-`okta.com` attendee) and need human review.
- `recruiting_notes` — Slack DM search matches with recruiter Cara
  McArthy, MCP-fetched by the `hiring-slack-sync` agent, one row per
  (`message_ts`, `channel_id`). No `se_rep_id` — she isn't an SE report.
  Feeds the Top Items scaffold's Hiring section alongside
  `calendar_events`' `hiring_interview` rows.
- `reviews` — drafted/edited review content, one row per (rep, period),
  `status` of `draft` or `final` — settable from either the Team page's
  inline editor or the Person page's Review tab.
- `top_items_entries` — one row per weekly Top Items draft, keyed by
  `entry_date` (upserted, so re-saving the same day overwrites rather than
  duplicating). `top_items.py` (mirrors `tech_forecast_report.py` — pure
  logic, no Flask dependency) builds the scaffold and backs
  `GET /api/top-items/latest`, `GET /api/top-items/history`,
  `POST /api/top-items/scaffold`, and `POST /api/top-items`.

## Sync behavior

Things a sync now does that are worth knowing before running one:

- **Row keys, and a one-time churn.** Rows are keyed by Salesforce
  opportunity ID when the sheet carries one, falling back to a composite
  built from the *parsed* close date. The old keys embedded mutable
  columns, so a slipped close date, an advanced stage — or a date cell
  merely reformatted from `5/4/2026` to `05/04/2026` — changed the key,
  which deleted and reinserted the row and took its manual SE/backup-SE
  assignment with it. **The first sync after this change re-keys the rows
  already stored**, so expect one run reporting an unusually large
  synced/deleted count, and one week-over-week delta showing deals as
  dropped and re-added. That is expected, and it happens once. Manual
  overrides are carried onto the replacement rows (reported as
  `overrides_carried`), so nothing is lost — no need to re-sync or re-enter
  assignments.
- **Truncated-fetch guard.** A sync refuses to run when the incoming payload
  has more than 20% fewer rows than are already stored, because a truncated
  fetch (a read range or pagination cursor cutting the grid short) looks
  exactly like a shrunken sheet, and the delete pass would hard-delete every
  missing row. Re-fetch with a wider range first. If the sheet genuinely did
  shrink that much — a fiscal-year rollover emptying the closed tab, say —
  pass `--allow-shrink` to `mcp_ingest.py` (`allow_shrink=True` on the
  `sync_*_from_values` functions).
- **Header check.** If the tab's header row doesn't carry the columns a sync
  needs, it now fails with the missing column names instead of quietly
  reporting `{"synced": 0}` — which is what a wrong tab, a wrong range, or a
  grid starting below row 1 used to look like.
- **What a sync reports.** The sheet syncs return `synced`, `unchanged`,
  `deleted`, `overrides_carried` and `unparsed_amounts` (that last one counts
  non-blank money cells that couldn't be parsed — money that would otherwise
  vanish silently; `deals` has no per-row fingerprint, so its `unchanged` is
  always 0). The Slack sync reports rows actually written — `synced`, `new`,
  `updated`, `unchanged` — rather than matches fetched, so re-running it no
  longer reads as a fresh lookback window of activity.
- **Snapshot retention.** `db.prune_snapshots()` drops
  `tech_forecast_snapshots` rows older than ~400 days while always keeping
  the most recent handful. It is deliberately **not** called on startup (an
  app restart must not be destructive) and currently has no caller — run it
  by hand if the daily per-deal blobs grow unwieldy.

## Sub-agents

Six Claude Code custom agents live in `.claude/agents/` and auto-load in
every Claude Code session opened against this project — "sync tech
forecast", "sync deals", "sync closed deals", "sync Slack", "sync
calendar", and "sync hiring Slack" requests are handled by the matching
function-specific agent rather than ad-hoc instructions each time:

| Agent | File | Trigger |
|---|---|---|
| `tech-forecast-sync` | `.claude/agents/tech-forecast-sync.md` | "sync tech forecast", "refresh tech forecast" |
| `deals-sync` | `.claude/agents/deals-sync.md` | "sync deals", "refresh pipeline" |
| `closed-deals-sync` | `.claude/agents/closed-deals-sync.md` | "sync closed deals", "refresh closed deals" |
| `slack-sync` | `.claude/agents/slack-sync.md` | "sync Slack", "refresh Slack notes" |
| `calendar-sync` | `.claude/agents/calendar-sync.md` | "sync calendar", "refresh Win Labs" |
| `hiring-slack-sync` | `.claude/agents/hiring-slack-sync.md` | "sync hiring Slack", "refresh recruiting notes" |

Each agent runs the full MCP-assisted sync flow for its data type: confirm
the live tab name via gid (sheet kinds), fetch data, write a temp JSON
payload, run `mcp_ingest.py` through `venv/Scripts/python.exe`, delete the
temp file, report the result (the counts described under "Sync behavior"
above). `calendar-sync` and `hiring-slack-sync` have no credential-based
alternative at all — MCP-assisted is the only path for Calendar/recruiting
data on this project.

The `/sync-se-hub` skill (`.claude/skills/sync-se-hub/SKILL.md`) is the
recommended way to trigger a sync — `/sync-se-hub` or "sync everything" runs
all six agents in parallel, or name a single kind ("sync deals", "sync
closed deals", "sync tech forecast", "sync Slack", "sync calendar", "sync
hiring Slack") to run just that one. Asking Claude in prose without the
slash command still works, since it dispatches to the same agents — the
skill just standardizes the parallel fan-out and reporting.

For the weekly Top Items summary specifically, `/sync-top-items`
(`.claude/skills/sync-top-items/SKILL.md`) is a narrower alternative that
only dispatches `calendar-sync` and `hiring-slack-sync` — the two feeds
`top_items.py`'s scaffold actually reads — skipping the four pipeline/Slack
agents that don't matter for that summary. It's a stand-in until Gong/API
access removes the need for a manual weekly sync at all.

## Conventions

- Keep `origin/main` up to date — commit and push after any meaningful
  change rather than batching unpushed work locally. This replaced the
  earlier "no GitHub by default" rule, which had scoped push authorization
  to the React migration only; see CLAUDE.md's Git workflow section for the
  full policy.
- Update this README after any non-trivial feature change.
- Work in small, reviewable chunks with a visible task list.
