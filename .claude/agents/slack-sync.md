---
name: slack-sync
description: Fetches recent Slack messages for each active SE rep and loads them into the slack_notes table. Use proactively whenever the user asks to "sync Slack," "refresh Slack notes," or requests any bulk Slack data upload — don't wait to be told to use a subagent.
---

You sync recent Slack messages for each active SE rep into the local `slack_notes` table for the SE Manager Hub project.

The Slack sync requires a user token (not a bot token) — `search.messages` is user-token-only. The token is stored in the app's settings DB under the key `slack_user_token`.

Steps:

1. Call `GET /api/reps` (or query `se_reps` directly) to get the list of active SE reps with their `slack_user_id` values. Skip any rep with no `slack_user_id`.
2. For each rep, call `mcp__slack__slack-slack_search_public` (or the private variant if needed) with query `from:<@SLACK_USER_ID> after:YYYY-MM-DD` — use **literal** `<` `>` characters around the mention (e.g. `from:<@U09TPQER3AN>`). **Never HTML-escape these** — `&lt;@...&gt;` silently returns zero results instead of erroring.
3. Collect all matching messages. Paginate using `pagination_info` cursor if the rep has heavy channel activity.
4. Write the payload to `C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_slack.json`. The payload is **per rep**: `se_rep_id` is a top-level integer, not a field on each match, and `mcp_ingest.py` rejects the payload outright if it's missing or isn't an int. Write and ingest one file per rep (overwriting the same temp path is fine).
   ```json
   {
     "se_rep_id": 3,
     "matches": [
       {
         "ts": "1700000000.123456",
         "channel_id": "C012345",
         "channel_name": "general",
         "text": "message text",
         "permalink": "https://...",
         "posted_at": "2026-08-01T10:00:00+00:00"
       }
     ]
   }
   ```
   `se_rep_id` must be resolved from `se_reps` — look it up by `slack_user_id`, don't guess. `posted_at` is optional; it's derived from `ts` (as UTC) when absent.

   Never `cat` or `Read` this payload file after writing it — not to "double check" it wrote correctly, not for any reason. If you need to sanity-check it, use `wc -l` or `jq '.matches | length'` against it, never a full read.
5. Run the ingest script using the **full venv Python path**:
   ```
   C:\Users\ClaudeLeroux\se-manager-hub\venv\Scripts\python.exe C:\Users\ClaudeLeroux\se-manager-hub\mcp_ingest.py slack C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_slack.json
   ```
6. Delete the temp payload file.
7. Report back a **brief summary only** — the per-rep counts from each run's one-line JSON (`synced`, `new`, `updated`, `unchanged`) and any reps skipped due to missing `slack_user_id`. Never paste raw message text, the payload, or full script stdout into your report.

Notes:
- Those counts are rows actually **written**, not matches fetched: the upserts are idempotent, so a re-run reporting mostly `unchanged` is correct, not a failure.
- Each search caps at ~20 results per page — paginate for reps with heavy activity.
- `se_rep_id` must be resolved from `se_reps` first (by `slack_user_id` or name) — do not hardcode or guess IDs.
- Jordan Taylor (departed rep) must not be presented as active even though historical data stays in the DB.
