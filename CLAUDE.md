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
3. Run `py mcp_ingest.py deals <file>` or `py mcp_ingest.py slack <file>`.
4. Delete the temp file afterward.

For Slack, `se_rep_id` must be resolved from `se_reps` first (by
`slack_user_id` or name) — look it up via `GET /api/reps` or a direct query,
don't guess it.

## Git workflow

**No GitHub for now** — work stays local only. Local `git commit` is fine;
do not create a remote repo or run `git push` unless the user explicitly
says otherwise.

## Docs

Always update README.md after any non-trivial feature change. Work in small
chunks with a visible task list.

## Key files

| File | Purpose |
|---|---|
| `app.py` | Flask routes |
| `db.py` | SQLite schema + thread-local connections |
| `sheets_sync.py` | Google Sheets → `deals` table |
| `slack_sync.py` | Slack `search.messages` → `slack_notes` table |
| `mcp_ingest.py` | CLI bridge — loads MCP-fetched JSON into the DB, no credentials needed |
| `reviews.py` | LiteLLM-backed review drafting |
| `static/style.css` | Okta dark theme (shared tokens with NaughtRFP) |
| `static/app.js` | SPA frontend — router, API helper, page renderers |
| `templates/index.html` | SPA shell |

## Not built yet

Gong integration — user is wiring this up themselves.
