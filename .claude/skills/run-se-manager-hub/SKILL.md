---
name: run-se-manager-hub
description: Build, start, and curl-test the SE Manager Hub Flask+React app — use when asked to run, start, launch, build, or smoke-test se-manager-hub, or to check its /api/settings or /api/reps endpoints.
---

SE Manager Hub is a Flask app (`app.py`) that serves a pre-built React
(Vite) frontend from `frontend/dist` and exposes a JSON API under
`/api/*`, backed by a local SQLite file (`se_manager_hub.db`). There is
no browser-automation tooling available in this environment
(`chromium-cli` is not installed, and no other local alternative was
found) — the app is driven with `curl` against its JSON API instead.
See `smoke.sh` in this directory for the primary agent-facing driver.

## Prerequisites

A Python virtualenv already exists at `venv/` with all of
`requirements.txt` installed (flask, python-dotenv, gspread,
google-auth, slack_sdk, anthropic, httpx). In a fresh Claude Code Bash
session the venv is **not** on `PATH`, so call its interpreter
directly rather than `py`/`python`:

```bash
cd "C:\Users\ClaudeLeroux\se-manager-hub"
venv/Scripts/python.exe -c "import flask, gspread, httpx; print('deps OK')"
```

## Build

The frontend is already built and committed at `frontend/dist/` — no
build step is required to run the app. If you've changed anything
under `frontend/src/`, rebuild with:

```bash
cd "C:\Users\ClaudeLeroux\se-manager-hub\frontend" && npm run build
```

`app.py` serves `frontend/dist/index.html` at `/` and the hashed
assets alongside it (`static_folder=frontend/dist`, `static_url_path=""`).

## Run (agent path)

Use `smoke.sh` in this directory — it backgrounds the server, polls
`/api/settings` until it answers, curls two endpoints, then kills the
server:

```bash
cd "C:\Users\ClaudeLeroux\se-manager-hub"
.claude/skills/run-se-manager-hub/smoke.sh
```

Verified output from an actual run:

```
started pid 1574, log: /tmp/se-manager-hub.log
up after 1s
-- /api/settings --
{"current_quarter":"2026-Q3","current_review_period":"2026-H2","deals_last_synced_at":"2026-09-03T14:47:14.668653","google_sheets_configured":false,"litellm_configured":false,"sheet_id":"","slack_configured":false}

-- /api/reps (first 500 bytes) --
[{"active":1,"arr_target":0.0,"arr_total":0,"created_at":"2026-09-03 18:47:14","deal_count":6,...,"tech_forecast_arr":0,...}, ...]
```

Server logs go to `/tmp/se-manager-hub.log`. Change the port with
`PORT=5051 .claude/skills/run-se-manager-hub/smoke.sh` (the script reads
`$PORT`, defaulting to `5050`, and passes it through to both the app and
its own curl calls).

To poke a different endpoint manually instead of (or after) running the
full script, launch the same way and curl directly, e.g.:

```bash
cd "C:\Users\ClaudeLeroux\se-manager-hub"
venv/Scripts/python.exe app.py &> /tmp/se-manager-hub.log &
sleep 2
curl -s http://127.0.0.1:5050/api/tech-forecast | head -c 500
kill %1
```

## Run (human path)

```bash
py app.py
```

Then open `http://127.0.0.1:5050/` in a browser. Not usable in this
headless container — no browser is available here, hence the curl-based
driver above.

## Gotchas

- **No browser automation available.** `chromium-cli` is not installed
  in this environment and no alternative was found, so the app must be
  driven via its JSON API (`curl`) rather than clicking through the UI.
- **venv is not on `PATH`** in a fresh Claude Code Bash session — `py`/
  `python app.py` will fail or silently use the wrong interpreter. Always
  call `venv/Scripts/python.exe` directly.
- **Don't read `.env` directly** to check what's configured — use
  `GET /api/settings` instead, which already reports
  `google_sheets_configured` / `slack_configured` / `litellm_configured`
  as booleans without exposing secret values.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'gspread'` (or similar) running `py app.py` | The venv isn't on `PATH` in this shell — use `venv/Scripts/python.exe app.py` instead of `py app.py`. |
