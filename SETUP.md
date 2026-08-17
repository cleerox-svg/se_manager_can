# Setup

## Option A: Claude-assisted sync (no setup)

If you're running this alongside a Claude Code session that already has the
Google Sheets and Slack MCP connectors, you don't need a service account or
a Slack App at all. Just ask Claude — e.g. "sync deals" or "pull Slack
activity for Nic" — and it will:

1. Read the sheet / search Slack live using its own MCP-connected access.
2. Write the result to a small temp JSON file (`_mcp_payload_*.json`,
   already gitignored).
3. Run `py mcp_ingest.py deals <file>` or `py mcp_ingest.py slack <file>`,
   which upserts straight into `se_manager_hub.db` — the same tables the
   credential-based sync writes to, so the app can't tell the difference.

Trade-off: this only happens when you ask, in a Claude chat — there's no
background/scheduled sync. The Sync buttons on the Settings page still call
the credential-based path below, so they'll show "Not configured" until you
either set that up or just keep syncing by asking Claude directly.

## Option B: Automated background sync (optional)

Two things need to be created outside this repo before the Sync buttons on
the Settings page will work standalone, without Claude in the loop. Nothing
below requires code changes — just config.

### 1. Google Sheets (Team Tracking Sheet)

The app reads the sheet as a service account, not as you, so syncing works
unattended and doesn't depend on your personal OAuth session.

1. In Google Cloud Console, create (or reuse) a project, then create a
   **Service Account** (IAM & Admin → Service Accounts).
2. Enable the **Google Sheets API** for that project.
3. Create a JSON key for the service account and download it.
4. Save the key file into this project's root as `service_account.json`
   (already gitignored — never commit it).
5. Open the Team Tracking Sheet and **share it** with the service account's
   email address (looks like `xxx@yyy.iam.gserviceaccount.com`) — Viewer
   access is enough.
6. In `.env`, set `SHEET_ID` (already defaulted to the current sheet) and
   `GOOGLE_SERVICE_ACCOUNT_JSON` if you saved the key under a different name.

### 2. Slack

`search.messages`, which is what powers the per-rep activity feed, is a
**user-token-only** Slack API method — a bot token cannot call it. You need
to install a Slack App to the workspace and generate a user OAuth token for
yourself.

1. Go to https://api.slack.com/apps → **Create New App** → From scratch.
2. Under **OAuth & Permissions**, add these **User Token Scopes**:
   - `search:read`
   - `users:read`
   - `channels:read`
   - `groups:read`
3. Install the app to your workspace.
4. Copy the **User OAuth Token** (starts with `xoxp-`) — not the bot token.
5. In `.env`, set `SLACK_USER_TOKEN` to that value.

Because it's a user token, the sync runs as *you* — it can only see channels
and DMs you're already a member of, same as searching in the Slack app.

## Review drafting (LiteLLM)

Needed either way — this isn't affected by which sync option you use above.

Set `LITELLM_API_KEY` in `.env` to your LiteLLM proxy key (same one used by
NaughtRFP). `LITELLM_BASE_URL` already defaults to `https://llm.atko.ai`.

## Run it

```bash
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in the values above
py app.py
```

Open http://127.0.0.1:5050.

## Gong

Not built yet — there's a placeholder on the Settings page. You said you'd
wire this one up yourself.
