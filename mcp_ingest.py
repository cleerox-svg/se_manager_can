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

    py mcp_ingest.py closed_deals <json_file>
        {"values": [["Team Member Name", "Team Role",
                      "Opportunity : Account Name : Account Owner : User Sales Region",
                      "Opportunity Name", "Manager", "Amount (converted)", "Opportunity Owner",
                      "Close Date", "Stage", "Presales Stage", "Opportunity ID"],
                     ["Rishika Kondaveeti (USD 2,538,735.02)", "Lead Sales Engineer (USD 2,538,735.02)",
                      "Canada (USD 2,538,735.02)", "Teknion - ODA", "Claude Leroux", " $ 3,064.52 ",
                      "Matt Hatherley", "5/4/2026", "10 - Closed/Won", "", "006WR00000hfyU8"], ...]}
        (the raw "Canada SE Closed This Fiscal Year" grid from the Team
        Tracking Sheet, nested three levels deep: Team Member Name > Team
        Role > Region)

    py mcp_ingest.py tech_forecast <json_file>
        {"values": [["Account Owner AVP Region", "Presales Stage", "Deal Forecast Status",
                      "Amount (converted)", "Opportunity Name", ..., "Technical Win Date", ...],
                     ["AMER CAN (11)", "2 - Discovery & Technical Qualification (1)", "Strong (1)", ...], ...]}
        (the raw "Sheet4" grid from the Team Tracking Sheet)

    py mcp_ingest.py slack <json_file>
        {"se_rep_id": 5, "matches": [
            {"ts": "1712345678.000200", "channel_id": "C123", "channel_name": "team-se",
             "text": "...", "permalink": "https://...", "posted_at": "2026-08-01T10:00:00"},
            ...
        ]}

Add --allow-shrink to a sheet kind to waive the truncated-fetch guard, which
otherwise aborts a sync whose payload is far smaller than what's stored (the
usual cause is a read range or pagination cursor cutting the grid short, not a
real shrink).

Prints ONE line of JSON — the sync's counts. Never row data: see CLAUDE.md.
"""

import json
import os
import sys

from db import Database
import closed_deals_sync
import sheets_sync
import slack_sync
import tech_forecast_sync

_SHEET_KINDS = ("deals", "closed_deals", "tech_forecast")
_KINDS = _SHEET_KINDS + ("slack",)


def _fail(message: str):
    """Abort with a readable reason on stderr, leaving stdout's one-line-of-
    JSON contract intact."""
    sys.exit(f"mcp_ingest: {message}")


def _validate(kind: str, payload):
    """Check the payload's shape up front.

    Without this an ordinary mistake — a payload written as a bare list, a
    "rows" key instead of "values", a forgotten se_rep_id — surfaced as a bare
    KeyError/TypeError traceback from somewhere deep in a sync, which reads
    like a bug in the sync rather than "your file is the wrong shape."
    Deliberately shape-only: nothing here inspects or echoes row content.
    """
    if not isinstance(payload, dict):
        _fail(f"payload must be a JSON object, got {type(payload).__name__}.")

    if kind in _SHEET_KINDS:
        values = payload.get("values")
        if values is None:
            _fail(f"payload is missing the 'values' key (keys present: {sorted(payload)}).")
        if not isinstance(values, list) or not all(isinstance(r, list) for r in values):
            _fail("'values' must be a list of row lists — the raw grid, header row included.")
        if not values:
            _fail("'values' is empty; nothing to sync (a truncated or wrong-range fetch?).")
        return

    if not isinstance(payload.get("se_rep_id"), int):
        _fail(
            "slack payload needs an integer 'se_rep_id' — resolve it from se_reps "
            "(GET /api/reps) by slack_user_id or name, don't guess it."
        )
    if not isinstance(payload.get("matches"), list):
        _fail("slack payload needs a 'matches' list (Slack search matches).")


def main():
    args = [a for a in sys.argv[1:] if a != "--allow-shrink"]
    allow_shrink = "--allow-shrink" in sys.argv[1:]
    if len(args) != 2 or args[0] not in _KINDS:
        print(__doc__)
        sys.exit(1)

    kind, path = args
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except OSError as e:
        _fail(f"can't read {path}: {e.strerror}.")
    except json.JSONDecodeError as e:
        _fail(f"{path} isn't valid JSON: {e.msg} (line {e.lineno}, column {e.colno}).")

    _validate(kind, payload)

    db = Database(os.environ.get("DATABASE_PATH", "se_manager_hub.db"))
    db.init()

    if kind == "deals":
        result = sheets_sync.sync_deals_from_values(db, payload["values"], allow_shrink)
    elif kind == "closed_deals":
        result = closed_deals_sync.sync_closed_deals_from_values(db, payload["values"], allow_shrink)
    elif kind == "tech_forecast":
        result = tech_forecast_sync.sync_tech_forecast_from_values(db, payload["values"], allow_shrink)
    else:
        result = slack_sync.sync_slack_notes_from_matches(db, payload["se_rep_id"], payload["matches"])

    print(json.dumps(result))


if __name__ == "__main__":
    main()
