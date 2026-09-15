# SE Manager Hub

A dashboard for an SE manager to track the team's current-quarter pipeline,
recent Slack activity per rep, and draft mid-year/check-in reviews — modeled
on [NaughtRFP](../rfp-responder)'s stack and Okta dark-theme UI.

## What it does

- **Dashboard** — team-wide rollup sourced from Technical Forecast data, no
  individual SE names shown at top level. Three stat cards (closed deals,
  % closed won, % technical win, from `/api/closed-deals/summary`'s
  name-free `team` object), a stacked ARR-trend area chart across the full
  `tech_forecast_snapshots` history (Technical Win / In Flight / Untagged),
  a stage-funnel bar chart per forecast status (reusing
  `tech_forecast_report.build_breakdown()`), and a quarter-over-quarter
  Technical Win ARR bar chart grouped by Okta fiscal quarter (see "Fiscal
  quarters" in CLAUDE.md). Built with `recharts`.
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
  Okta's Presales Technical Win Process, synced from the Team Tracking
  Sheet's Technical Forecast tab (currently "Claude This q and next" —
  auto-refreshes every 24h, tab names get renamed by the user from time to
  time, see CLAUDE.md). The sheet is grouped by Lead Sales Engineer first,
  then Deal Forecast Status, including a literal "no Lead SE assigned yet"
  group — see "SE attribution" below. Presales Stage is a flat per-deal
  column (not a group level), genuinely blank for deals not yet staged. The
  sheet's query also carries deals belonging to Greg Rainbird's sales org
  (a different team) — those are dropped entirely during sync, even when a
  now-inactive Lead SE of ours is still attached, since they aren't ours to
  track here. A "Sync now" button next to Present mode copies a ready-made
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
  "Tech win (open)" badge if it hasn't actually closed won yet), Look Forward &
  Inspect (open technical pipeline table, grouped into collapsible sections —
  same `<details class="flyout">` pattern as Look Back — by target Technical
  Win date's fiscal-quarter bucket, in fixed order Overdue → Current Quarter →
  Next Quarter → Later/Unscheduled; within each group, deals are sorted by
  Amount (ARR) descending. Each group's summary line shows the bucket label,
  deal count, and dollar total, same as Look Back's group headers. Each row
  shows Stage (now a colored badge — green for Closed/Won, red for
  Closed/Lost, blue for still-open — instead of plain text), Presales
  Stage, Forecast Status, Tech Win Date, Amount, an SE dropdown (with a
  "No Lead SE (sheet)" badge when the sheet itself has no Lead SE set),
  Flags, and all three of Pre-Sales Notes, SE Manager Notes, and Pre-Sales
  Next Steps as distinct columns), and Wrap-Up & Risk (Forecasted Risk
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
  "Come ready to discuss" section shows the deal's Lead SE (not the AE) and
  is split into Current quarter / Next quarter / Unscheduled-or-later
  sub-sections by each deal's target Technical Win date's Okta fiscal
  quarter (`tech_forecast_report.quarter_bucket`, relative to today's
  fiscal quarter), each deal followed by a heuristic, rule-based discussion
  question (`build_discussion_question` — not LLM-generated; picks from
  missing-next-steps / stale-notes / at-risk / stage-based prompts in that
  priority order, since each is a stronger signal than the last, and phrased
  around Command of the Message / Opportunity Analysis & Coaching Guide
  qualification pillars — compelling event, Champion, Decision Criteria/
  Process, Proof Points — rather than generic stage-progress language). A separate
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
  generic fallback. Same editable-textarea-plus-Copy-button UX as Team Prep
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

Data gets in via one of two paths — see [SETUP.md](SETUP.md):
- **Ask Claude to sync** (no setup) — Claude uses its own Google Sheets /
  Slack MCP access and loads the result with `mcp_ingest.py`.
- **Automated background sync** (optional) — a Google service account +
  Slack App/user token, wired to the Settings-page Sync buttons.

## Data model

- `se_reps` — roster, Slack user ID, active/inactive flag, `arr_target`
  (full-fiscal-year closed-won ARR target, manager-set — seeded once via
  `seed_arr_targets.py`, editable in place from the Team page).
- `deals` — synced from the Team Tracking Sheet's open-pipeline tab, one row
  per open opportunity.
- `closed_deals` — synced from the Team Tracking Sheet's closed-deal export
  tab ("Canada SE Closed This Fiscal Year"), one row per closed opportunity —
  both Closed/Won and Closed/Lost, not won deals only — flagged `tech_win`
  when Presales Stage is "6 - Technical Win". Loaded the same MCP-assisted
  way as `deals` (`py mcp_ingest.py closed_deals <json_file>`), and folded
  into `reviews.py`'s LLM context so future generated drafts lead with real
  closed-deal/technical-win evidence. Also carries `opportunity_id` (for
  Salesforce links) and `sales_stage` (the sheet's "Stage" column, either
  "10 - Closed/Won" or "11- Closed/Lost") alongside `tech_win`, distinguishing
  actual Closed Won status from the Tech Win flag. `/api/closed-deals/summary`
  aggregates both into win-rate percentages — team-wide and per-rep —
  rendered as `% Closed Won` / `% Tech Win` bars on the Technical Forecast
  page; both percentages vary meaningfully by rep since the tab mixes Won and
  Lost outcomes. The team-wide block shows two figures side by side: the
  all-time rate across the whole sheet, and a second rate scoped to deals
  closed within the current Okta fiscal quarter (`team_current_quarter`,
  labeled with that quarter, e.g. "FY26-Q3") — added since the all-time
  figure alone reads as "recent" performance when it actually spans the
  whole season. Per-rep breakdown stays all-time only.
- `tech_forecast_deals` — synced from the Team Tracking Sheet's Technical
  Forecast tab, one row per open deal in the technical-win pipeline
  (`lead_se_name` straight from the sheet, Presales Stage — a flat per-deal
  field, genuinely blank for un-staged deals — Deal Forecast Status,
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
  at least one row actually changed or was deleted. The return value
  reports `synced` (changed + new), `unchanged`, and `deleted` counts.
- `tech_forecast_snapshots` — one row per sync day, holding that day's
  bucket totals and per-deal state as JSON — the baseline
  `tech_forecast_report.build_weekly_deltas` diffs the next sync against to
  produce the preread's "Key Changes vs Last Week" section.
- `slack_notes` — synced from Slack search per rep.
- `reviews` — drafted/edited review content, one row per (rep, period),
  `status` of `draft` or `final` — settable from either the Team page's
  inline editor or the Person page's Review tab.

## Sub-agents

Four Claude Code custom agents live in `.claude/agents/` and auto-load in
every Claude Code session opened against this project — "sync tech
forecast", "sync deals", "sync closed deals", and "sync Slack" requests are
handled by the matching function-specific agent rather than ad-hoc
instructions each time:

| Agent | File | Trigger |
|---|---|---|
| `tech-forecast-sync` | `.claude/agents/tech-forecast-sync.md` | "sync tech forecast", "refresh tech forecast" |
| `deals-sync` | `.claude/agents/deals-sync.md` | "sync deals", "refresh pipeline" |
| `closed-deals-sync` | `.claude/agents/closed-deals-sync.md` | "sync closed deals", "refresh closed deals" |
| `slack-sync` | `.claude/agents/slack-sync.md` | "sync Slack", "refresh Slack notes" |

Each agent runs the full MCP-assisted sync flow for its data type: confirm
the live tab name via gid, fetch data, write a temp JSON payload, run
`mcp_ingest.py` through `venv/Scripts/python.exe`, delete the temp file,
report the result (including the synced/unchanged/deleted counts above).

The `/sync-se-hub` skill (`.claude/skills/sync-se-hub/SKILL.md`) is the
recommended way to trigger a sync — `/sync-se-hub` or "sync everything" runs
all four agents in parallel, or name a single kind ("sync deals", "sync
closed deals", "sync tech forecast", "sync Slack") to run just that one.
Asking Claude in prose without the slash command still works, since it
dispatches to the same agents — the skill just standardizes the parallel
fan-out and reporting.

## Conventions

- No GitHub by default — work stays local only. Local `git commit`s are
  fine; don't create a remote repo or run `git push` unless explicitly
  authorized for that specific task. Exception on record: the React
  migration (`REACT_MIGRATION_PLAN.md`, Phases 0-6) was explicitly
  authorized to push each phase to `origin/main`, and that migration is now
  complete — see CLAUDE.md's Git workflow section for the full policy.
- Update this README after any non-trivial feature change.
- Work in small, reviewable chunks with a visible task list.
