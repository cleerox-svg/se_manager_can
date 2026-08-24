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
  direct report).
- **Person detail** — a rep's open deals, recent Slack activity (via
  `search.messages` for their user ID), and an AI-drafted review for the
  current half, editable in-app.
- **Technical Forecast** — weekly Technical Forecast Call view modeled on
  Okta's Presales Technical Win Process, synced from the Team Tracking
  Sheet's Technical Forecast tab (currently "Satish Technical Forecast
  Current Q" — tab names get renamed by the user from time to time, see
  CLAUDE.md). Four sections: Macro View (stat-grid — total tech forecast
  ARR, Must-Win count/$, Forecasted Risk count, stale-notes count), Look
  Back (recent technical wins, blending closed `tech_win` deals with open
  deals already at "6 - Technical Win"), Look Forward & Inspect (open
  technical pipeline, split into a Must-Win ($150K+) table shown by default
  plus a collapsible flyout for everything below $150K — each row shows
  Stage, Presales Stage, Forecast Status, Tech Win Date, Amount, Flags,
  Pre-Sales next steps, and SE Manager notes, with the Opportunity Owner
  shown as "AE" since this sheet has no SE-specific field), and Wrap-Up &
  Risk (Forecasted Risk and/or stale-notes deals, Must-Wins surfaced
  first). A Must-Win is any deal >= $150K. A deal's pre-sales notes are
  flagged stale ("No update this week") when they're unchanged from the
  previous sync — not by parsing dates in the freeform text. A "Present
  mode" toggle hides the sidebar/topbar for clean screen-sharing during the
  Monday call. A light/dark theme toggle (sidebar footer) persists via
  `localStorage`.
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

- `se_reps` — roster, Slack user ID, active/inactive flag.
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
  pre-sales/SE-manager notes).
  Loaded the same MCP-assisted way (`py mcp_ingest.py tech_forecast
  <json_file>`). Each sync diffs incoming pre-sales notes against the
  previously-stored value per row to set `notes_stale`.
- `slack_notes` — synced from Slack search per rep.
- `reviews` — drafted/edited review content, one row per (rep, period).

## Conventions

- Local only for now — no GitHub, no remote repo. Local `git commit`s are
  fine; nothing gets pushed anywhere.
- Update this README after any non-trivial feature change.
- Work in small, reviewable chunks with a visible task list.
