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
- `deals` — synced from the Team Tracking Sheet's "SFDC" tab, one row per
  open opportunity.
- `closed_deals` — synced from the Team Tracking Sheet's "Sheet3" tab
  (closed-won export), one row per closed opportunity, flagged `tech_win`
  when Presales Stage is "6 - Technical Win". Loaded the same MCP-assisted
  way as `deals` (`py mcp_ingest.py closed_deals <json_file>`), and folded
  into `reviews.py`'s LLM context so future generated drafts lead with real
  closed-deal/technical-win evidence.
- `slack_notes` — synced from Slack search per rep.
- `reviews` — drafted/edited review content, one row per (rep, period).

## Conventions

- Local only for now — no GitHub, no remote repo. Local `git commit`s are
  fine; nothing gets pushed anywhere.
- Update this README after any non-trivial feature change.
- Work in small, reviewable chunks with a visible task list.
