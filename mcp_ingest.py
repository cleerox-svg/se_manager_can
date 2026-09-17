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
        {"values": [["Opportunity Name", "Amount (converted)", "Opportunity Owner",
                      "Close Date", "Stage", "Presales Stage", "Opportunity ID"],
                     ["Teknion - ODA", " $ 3,064.52 ", "Matt Hatherley", "5/4/2026",
                      "10 - Closed/Won", "", "006WR00000hfyU8"], ...]}
        (the raw "Tech wins and losses" grid from the standalone closed-deals
        sheet — as of the 2026-09-15 reformat this is a flat, single-manager
        export with no Team Member Name/Team Role/Region grouping; see
        closed_deals_sync.py's docstring for the current per-deal SE column
        status)

    py mcp_ingest.py tech_forecast <json_file>
        {"values": [["Presales Stage", "Amount (converted)", "Opportunity Name",
                      "Opportunity ID", "Opportunity Owner", "Stage", "Close Date", ...],
                     ["2 - Discovery & Technical Qualification", " $ 3,064.52 ", "Teknion - ODA",
                      "006WR00000hfyU8", "Matt Hatherley", "10 - Closed/Won", "5/4/2026", ...], ...]}
        (the raw "Canada SE Tech Forecast current and next q" grid from the
        standalone tech-forecast sheet — as of the 2026-09-15 reformat "Deal
        Forecast Status" is gone; see tech_forecast_sync.py's docstring for
        the current "Lead Sales Engineer" column status)

    py mcp_ingest.py slack <json_file>
        {"se_rep_id": 5, "matches": [
            {"ts": "1712345678.000200", "channel_id": "C123", "channel_name": "team-se",
             "text": "...", "permalink": "https://...", "posted_at": "2026-08-01T10:00:00"},
            ...
        ]}

    py mcp_ingest.py calendar_events <json_file>
        {"events": [
            {"category": "win_lab", "event_id": "abc123", "title": "Win Lab: Northwind",
             "start_time": "2026-09-15T15:00:00Z", "end_time": "2026-09-15T16:00:00Z",
             "attendees": ["someone@okta.com"], "description": "..."},
            {"category": "hiring_interview", "event_id": "def456",
             "title": "Interview: SE candidate", "start_time": "2026-09-16T18:00:00Z",
             "end_time": "2026-09-16T19:00:00Z", "attendees": [], "description": ""},
            {"category": "customer_meeting", "event_id": "ghi789",
             "title": "Acme Corp check-in", "start_time": "2026-09-17T14:00:00Z",
             "end_time": "2026-09-17T15:00:00Z", "attendees": ["buyer@acme.com"],
             "description": "..."},
            ...
        ]}
        (each event already classified by the `calendar-sync` agent's
        title/attendee heuristics before this file is written — `category`
        is one of 'win_lab' | 'hiring_interview' | 'customer_meeting'.
        `attendees` is optional shorthand for `attendees_json`; either is
        accepted)

    py mcp_ingest.py recruiting_notes <json_file>
        {"matches": [
            {"ts": "1712345678.000200", "channel_id": "D0RECRUIT",
             "text": "...", "permalink": "https://...", "posted_at": "2026-08-01T10:00:00"},
            ...
        ]}
        (Slack DM search matches with Cara McArthy, no `se_rep_id` — she
        isn't an SE report)

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
import calendar_sync
import closed_deals_sync
import recruiting_sync
import sheets_sync
import slack_sync
import tech_forecast_sync

_SHEET_KINDS = ("deals", "closed_deals", "tech_forecast")
_KINDS = _SHEET_KINDS + ("slack", "calendar_events", "recruiting_notes")


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

    if kind == "slack":
        if not isinstance(payload.get("se_rep_id"), int):
            _fail(
                "slack payload needs an integer 'se_rep_id' — resolve it from se_reps "
                "(GET /api/reps) by slack_user_id or name, don't guess it."
            )
        if not isinstance(payload.get("matches"), list):
            _fail("slack payload needs a 'matches' list (Slack search matches).")
        return

    if kind == "calendar_events":
        events = payload.get("events")
        if not isinstance(events, list):
            _fail("calendar_events payload needs an 'events' list.")
        for e in events:
            if not isinstance(e, dict):
                _fail("calendar_events payload's 'events' entries must be objects.")
            if e.get("category") not in ("win_lab", "hiring_interview", "customer_meeting"):
                _fail(
                    "each calendar_events entry needs a 'category' of "
                    "'win_lab', 'hiring_interview', or 'customer_meeting' "
                    f"(got {e.get('category')!r})."
                )
            if not e.get("event_id"):
                _fail("each calendar_events entry needs an 'event_id'.")
        return

    if kind == "recruiting_notes":
        if not isinstance(payload.get("matches"), list):
            _fail("recruiting_notes payload needs a 'matches' list (Slack search matches).")
        return


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

    default_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "se_manager_hub.db")
    db = Database(os.environ.get("DATABASE_PATH", default_db_path))
    db.init()

    if kind == "deals":
        result = sheets_sync.sync_deals_from_values(db, payload["values"], allow_shrink)
    elif kind == "closed_deals":
        result = closed_deals_sync.sync_closed_deals_from_values(db, payload["values"], allow_shrink)
    elif kind == "tech_forecast":
        result = tech_forecast_sync.sync_tech_forecast_from_values(db, payload["values"], allow_shrink)
    elif kind == "slack":
        result = slack_sync.sync_slack_notes_from_matches(db, payload["se_rep_id"], payload["matches"])
    elif kind == "calendar_events":
        result = calendar_sync.sync_calendar_events_from_values(db, payload["events"])
    else:
        result = recruiting_sync.sync_recruiting_notes_from_matches(db, payload["matches"])

    print(json.dumps(result))


if __name__ == "__main__":
    main()
