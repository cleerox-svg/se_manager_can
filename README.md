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

See [SETUP.md](SETUP.md) for the one-time Google service account + Slack
app setup, then:

```bash
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
py app.py
```

## Data model

- `se_reps` — roster, Slack user ID, active/inactive flag.
- `deals` — synced from the Team Tracking Sheet, one row per opportunity.
- `slack_notes` — synced from Slack search per rep.
- `reviews` — drafted/edited review content, one row per (rep, period).

## Conventions

- Push to GitHub only — never sync this repo into a local Desktop folder.
- Update this README after any non-trivial feature change.
- Work in small, reviewable chunks with a visible task list.
