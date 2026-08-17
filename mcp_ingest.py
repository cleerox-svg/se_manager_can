"""CLI bridge for Claude to push MCP-fetched data into the local DB.

This is the MCP-assisted alternative to sheets_sync/slack_sync's
credential-based paths — no Google service account or Slack App needed.
Claude fetches data live via its connected Google Sheets / Slack MCP tools,
writes it to a temp JSON file, then runs this script to load it.

Usage:
    py mcp_ingest.py deals <json_file>
        {"values": [["Lead Sales Engineer", "Stage", ...], ["Nic Da Silva", ...], ...]}
        (the raw sheet grid: header row + data rows, same shape as
        gspread's get_all_values())

    py mcp_ingest.py slack <json_file>
        {"se_rep_id": 5, "matches": [
            {"ts": "1712345678.000200", "channel_id": "C123", "channel_name": "team-se",
             "text": "...", "permalink": "https://...", "posted_at": "2026-08-01T10:00:00"},
            ...
        ]}
"""

import json
import os
import sys

from db import Database
import sheets_sync
import slack_sync


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("deals", "slack"):
        print(__doc__)
        sys.exit(1)

    kind, path = sys.argv[1], sys.argv[2]
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    db = Database(os.environ.get("DATABASE_PATH", "se_manager_hub.db"))
    db.init()

    if kind == "deals":
        result = sheets_sync.sync_deals_from_values(db, payload["values"])
    else:
        result = slack_sync.sync_slack_notes_from_matches(db, payload["se_rep_id"], payload["matches"])

    print(json.dumps(result))


if __name__ == "__main__":
    main()
