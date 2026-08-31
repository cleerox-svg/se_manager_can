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
  Sheet's Technical Forecast tab (currently "Satish Technical Forecast
  Current Q" — tab names get renamed by the user from time to time, see
  CLAUDE.md). Five sections: Macro View (stat-grid — total tech forecast
  ARR, Must-Win count/$, Forecasted Risk count, stale-notes count — plus an
  "AE Forecast Coverage" panel sourced from the weekly Clari CSV export, see
  "Clari AE cross-reference" below), Look Back (recent technical wins,
  blending closed `tech_win` deals with open deals already at "6 - Technical
  Win"), Look Forward & Inspect (open technical pipeline, split into a
  Must-Win ($150K+) table shown by default plus a collapsible flyout for
  everything below $150K — each row shows Stage, Presales Stage, Forecast
  Status, Tech Win Date, Amount, an SE dropdown, Flags, Pre-Sales next
  steps, and SE Manager notes, with the Opportunity Owner shown as "AE"
  since this sheet has no SE-specific field — see "SE attribution" below),
  and Wrap-Up & Risk (Forecasted Risk and/or stale-notes deals, Must-Wins
  surfaced first, same AE/SE display as Look Forward & Inspect). A Must-Win
  is any deal >= $150K. A deal's pre-sales notes are flagged stale ("No
  update this week") when they're unchanged from the previous sync — not by
  parsing dates in the freeform text; a blank pre-sales-notes field is
  flagged separately as "No TW Strategy". A "Present mode" toggle hides the
  sidebar/topbar for clean screen-sharing during the Monday call. A
  light/dark theme toggle (sidebar footer) persists via `localStorage`.
- **SE attribution (Team ↔ Technical Forecast)** — `tech_forecast_deals`
  has no automatic `se_rep_id` of its own (see `tech_forecast_sync.py`), so
  both the Team page's "Tech Forecast ARR" figure and the Technical
  Forecast page's per-row SE dropdown are derived live in `app.py` by
  matching Opportunity Name against `deals.opportunity_name`, which does
  carry `se_rep_id` (~90% match rate; unmatched rows fall back to
  "Unassigned"). The Technical Forecast page's SE dropdown lets the manager
  override that auto-match per deal (`assigned_se_rep_id`, stored on
  `tech_forecast_deals`) — an explicit override always wins over the
  auto-match, and the dropdown pre-selects whichever one is currently
  effective while remaining editable.
- **Clari AE cross-reference** — a weekly manual CSV drop (This Quarter /
  Next Quarter exports from Clari, see "Clari data model" below) that
  surfaces, per AE, their quota, native Auth0/Okta forecast, a derived
  gap-to-forecast per product, blended pipeline-coverage ratios, and that
  AE's own open (non-Technical-Win) technical pipeline $/count — so the call
  can flag "a tech win here would most help this AE close their gap." Shown
  as its own Macro View card; renders an empty state until the first sync.
  No in-app upload — Claude Leroux drops the CSVs in the `Clari Reporting`
  folder and asks Claude to sync (see CLAUDE.md).
- **Slack preread** — `GET /api/tech-forecast/preread` assembles an
  Executive Takeaway, Key Metrics, Pipeline Breakdown, Top deals (excluding
  Technical Win/Final Due Diligence), week-over-week deltas, and the AE
  cross-reference into one payload modeled on the "Tech Win Forecast & Risk
  Summary" format the manager's own chain uses. No in-app send button —
  Claude drafts the Slack message from this payload on request and posts it
  via the Slack MCP tools after review.
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
  (Presales Stage, Deal Forecast Status, Technical Win Date, overall Stage,
  pre-sales/SE-manager notes, plus a manually-set `assigned_se_rep_id`
  override — see "SE attribution" above).
  Loaded the same MCP-assisted way (`py mcp_ingest.py tech_forecast
  <json_file>`). Each sync diffs incoming pre-sales notes against the
  previously-stored value per row to set `notes_stale`, and also captures a
  same-day snapshot (see `tech_forecast_snapshots` below).
- `clari_ae_snapshots` — one row per (source label, AE, Clari Field, Data
  Type), holding only the row matching *today's* date window from the
  weekly Clari CSV export — see "Clari data model" in CLAUDE.md. Loaded by
  `clari_sync.py`, a manual local-file parser (no Clari API/MCP surface
  exists).
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
