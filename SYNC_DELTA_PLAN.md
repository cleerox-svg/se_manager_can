# Delta-Aware Tech Forecast Sync — Remaining Work

## What's already done

- `db.py` — schema migration adds `opportunity_id TEXT` and `row_fingerprint TEXT` columns to `tech_forecast_deals` (both in `_migrate()` guards and the `CREATE TABLE IF NOT EXISTS` DDL). Already committed or present.
- `tech_forecast_sync.py` — `import hashlib` present; `_FINGERPRINT_FIELDS`, `_row_fingerprint()`, and the full delta-aware `load_rows()` rewrite are now in place. `load_rows` now:
  - Pre-loads all existing rows in one query (keyed by `sheet_key`)
  - Computes MD5 fingerprint of 16 text fields + 3 parsed fields
  - Skips DB writes for unchanged rows
  - Only calls `_capture_snapshot` when `changed_count > 0` or `deleted_count > 0`
  - Returns `{"synced": changed_count, "unchanged": unchanged_count, "deleted": deleted_count}`
- `.claude/agents/tech-forecast-sync.md` — exists, correct content
- `.claude/agents/deals-sync.md` — exists, correct content

## What still needs to be done

### 1. Create `.claude/agents/slack-sync.md`

File path: `C:\Users\ClaudeLeroux\se-manager-hub\.claude\agents\slack-sync.md`

Content to write:

```markdown
---
name: slack-sync
description: Fetches recent Slack messages for each active SE rep and loads them into the slack_notes table. Use when asked to "sync Slack" or "refresh Slack notes."
---

You sync recent Slack messages for each active SE rep into the local `slack_notes` table for the SE Manager Hub project.

The Slack sync requires a user token (not a bot token) — `search.messages` is user-token-only. The token is stored in the app's settings DB under the key `slack_user_token`.

Steps:

1. Call `GET /api/reps` (or query `se_reps` directly) to get the list of active SE reps with their `slack_user_id` values. Skip any rep with no `slack_user_id`.
2. For each rep, call `mcp__slack__slack-slack_search_public` (or the private variant if needed) with query `from:<@SLACK_USER_ID> after:YYYY-MM-DD` — use **literal** `<` `>` characters around the mention (e.g. `from:<@U09TPQER3AN>`). **Never HTML-escape these** — `&lt;@...&gt;` silently returns zero results instead of erroring.
3. Collect all matching messages. Paginate using `pagination_info` cursor if the rep has heavy channel activity.
4. Write the payload to `C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_slack.json`:
   ```json
   {
     "matches": [
       {
         "se_rep_id": 3,
         "ts": "1700000000.123456",
         "channel_id": "C012345",
         "channel_name": "general",
         "text": "message text",
         "permalink": "https://..."
       }
     ]
   }
   ```
   `se_rep_id` must be resolved from `se_reps` — look it up by `slack_user_id`, don't guess.
5. Run the ingest script using the **full venv Python path**:
   ```
   C:\Users\ClaudeLeroux\se-manager-hub\venv\Scripts\python.exe C:\Users\ClaudeLeroux\se-manager-hub\mcp_ingest.py slack C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_slack.json
   ```
6. Delete the temp payload file.
7. Report results to the user (how many messages loaded per rep, any reps skipped due to missing `slack_user_id`).

Notes:
- Each search caps at ~20 results per page — paginate for reps with heavy activity.
- `se_rep_id` must be resolved from `se_reps` first (by `slack_user_id` or name) — do not hardcode or guess IDs.
- Jordan Taylor (departed rep) must not be presented as active even though historical data stays in the DB.
```

### 2. Update `CLAUDE.md` — add Sub-agents section

Append the following section before the `## Key files` table (or after `## Docs`):

```markdown
## Sub-agents

Three Claude Code custom agents live in `.claude/agents/` and are auto-loaded in every Claude Code session opened against this project directory:

| Agent | File | Trigger |
|---|---|---|
| `tech-forecast-sync` | `.claude/agents/tech-forecast-sync.md` | "sync tech forecast", "refresh tech forecast" |
| `deals-sync` | `.claude/agents/deals-sync.md` | "sync deals", "refresh pipeline" |
| `slack-sync` | `.claude/agents/slack-sync.md` | "sync Slack", "refresh Slack notes" |

Each agent handles the full MCP-assisted sync flow for its data type: confirm live tab name/gid, fetch data, write temp JSON payload, run `mcp_ingest.py` via `venv/Scripts/python.exe`, delete temp file, report result. Tab gid values are stable even when tab names change — agents always confirm the live name via `get_spreadsheet_info` before reading.
```

### 3. Update `README.md`

Add a section documenting:
- Delta-aware sync: `tech_forecast_sync.py`'s `load_rows` now computes a per-row MD5 fingerprint of all 19 mutable fields; rows whose hash matches the stored `row_fingerprint` are skipped — no unnecessary DB writes or snapshot captures. Return value now includes `unchanged` and `deleted` counts alongside `synced`.
- Sub-agent workflow: three `.claude/agents/*.md` files auto-load each session, so "sync tech forecast / sync deals / sync Slack" requests are handled by function-specific agents rather than ad-hoc instructions.

### 4. Local git commit (NO push)

After all three items above are done, run:
```bash
cd C:\Users\ClaudeLeroux\se-manager-hub
git add tech_forecast_sync.py db.py .claude/agents/ CLAUDE.md README.md
git status
git commit -m "feat: delta-aware tech forecast sync + persistent Claude Code sub-agents

- tech_forecast_sync.py: load_rows now pre-loads all existing rows in one query,
  computes MD5 fingerprint of 19 mutable fields, skips DB writes for unchanged rows,
  only captures snapshot when something actually changed. Returns synced/unchanged/deleted counts.
- db.py: _migrate() adds opportunity_id and row_fingerprint columns to tech_forecast_deals
  (already done in prior session)
- .claude/agents/: three persistent sub-agent definitions auto-loaded each session —
  tech-forecast-sync, deals-sync, slack-sync — each handles its full MCP-assisted
  sync flow with venv Python path, correct Slack literal-bracket syntax, gid-based
  tab confirmation, and Greg Rainbird exclusion awareness

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

Do NOT run `git push`.
