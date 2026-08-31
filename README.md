# SE Manager Hub

A dashboard for an SE manager to track the team's current-quarter pipeline,
recent Slack activity per rep, and draft mid-year/check-in reviews — modeled
on [NaughtRFP](../rfp-responder)'s stack and Okta dark-theme UI.

## What it does

- **Dashboard** — current-quarter deals pulled from the Team Tracking Sheet
  (Google Sheets), filterable by quarter/stage/search, with POC and
  SE-Needed flags surfaced.
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
  time, see CLAUDE.md). The sheet is grouped by Lead Sales Engineer first
  (then Presales Stage, then Deal Forecast Status), including a literal
  "no Lead SE assigned yet" group — see "SE attribution" below. Five
  sections: Macro View (stat-grid — total tech forecast ARR, Must-Win
  count/$, Forecasted Risk count, stale-notes count, and Needs Lead SE
  count/$), Look Back (recent technical wins, blending closed `tech_win`
  deals with open deals already at "6 - Technical Win"), Look Forward &
  Inspect (open technical pipeline, split into a Must-Win ($150K+) table
  shown by default plus a collapsible flyout for everything below $150K —
  each row shows Stage, Presales Stage, Forecast Status, Tech Win Date,
  Amount, an SE dropdown (with a "No Lead SE (sheet)" badge when the sheet
  itself has no Lead SE set), Flags, and all three of Pre-Sales Notes, SE
  Manager Notes, and Pre-Sales Next Steps as distinct columns), and
  Wrap-Up & Risk (Forecasted Risk and/or stale-notes deals, Must-Wins
  surfaced first, same SE display as Look Forward & Inspect). A Must-Win
  is any deal >= $150K. A deal is flagged stale ("No update this week")
  when its Pre-Sales Next Steps text is unchanged from the previous sync —
  not by parsing dates in the freeform text. A "Present mode" toggle hides
  the sidebar/topbar for clean screen-sharing during the Monday call. A
  light/dark theme toggle (sidebar footer) persists via `localStorage`.
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
- **Settings** — sync status/buttons for Google Sheets and Slack, and a
  placeholder for Gong (not built — planned as a future integration).

## Stack

Python 3.14 (`py`, not `python`) + Flask + SQLite3, vanilla JS/HTML frontend
with no build step. Review drafting calls the LiteLLM proxy
(`https://llm.atko.ai`) using the same client pattern as NaughtRFP.

## Run it

```bash
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
py app.py
```

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
- `closed_deals` — synced from the Team Tracking Sheet's closed-won export
  tab, one row per closed opportunity, flagged `tech_win`
  when Presales Stage is "6 - Technical Win". Loaded the same MCP-assisted
  way as `deals` (`py mcp_ingest.py closed_deals <json_file>`), and folded
  into `reviews.py`'s LLM context so future generated drafts lead with real
  closed-deal/technical-win evidence.
- `tech_forecast_deals` — synced from the Team Tracking Sheet's Technical
  Forecast tab, one row per open deal in the technical-win pipeline
  (`lead_se_name` straight from the sheet, Presales Stage, Deal Forecast
  Status, Technical Win Date, overall Stage, Pre-Sales Notes, SE Manager
  Notes, Pre-Sales Next Steps, plus a manually-set `assigned_se_rep_id`
  override — see "SE attribution" above).
  Loaded the same MCP-assisted way (`py mcp_ingest.py tech_forecast
  <json_file>`). Each sync diffs incoming Pre-Sales Next Steps against the
  previously-stored value per row to set `notes_stale`, and also captures a
  same-day snapshot (see `tech_forecast_snapshots` below).
- `tech_forecast_snapshots` — one row per sync day, holding that day's
  bucket totals and per-deal state as JSON — the baseline
  `tech_forecast_report.build_weekly_deltas` diffs the next sync against to
  produce the preread's "Key Changes vs Last Week" section.
- `slack_notes` — synced from Slack search per rep.
- `reviews` — drafted/edited review content, one row per (rep, period),
  `status` of `draft` or `final` — settable from either the Team page's
  inline editor or the Person page's Review tab.

## Conventions

- Local only for now — no GitHub, no remote repo. Local `git commit`s are
  fine; nothing gets pushed anywhere.
- Update this README after any non-trivial feature change.
- Work in small, reviewable chunks with a visible task list.
