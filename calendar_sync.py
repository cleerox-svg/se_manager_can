"""Loads already-classified Google Calendar events into the local
`calendar_events` table, for the Top Items scaffold's Win Labs / Hiring /
Customer Meetings sections.

MCP-assisted only — there is no credential-based path here (unlike
`sheets_sync.py`/`slack_sync.py`), since this table only ever gets filled by
a live Claude Code session's Calendar MCP access, classified by the
`calendar-sync` agent before the payload is written. This module just loads
whatever it's handed.
"""

import json

from db import utc_now_iso


def _load_events(db, events: list[dict]) -> dict:
    """Upsert already-classified, already-fetched calendar events into
    `calendar_events`.

    Returns what was actually WRITTEN, not how many events were handed to
    us — same counting convention as `slack_sync._load_matches`, so a re-run
    reports `unchanged` rather than reading as a fresh week of activity."""
    fetched_at = utc_now_iso()
    new_count = 0
    updated_count = 0
    unchanged_count = 0

    with db.conn() as c:
        for e in events:
            category = e.get("category")
            event_id = e.get("event_id")
            title = e.get("title")
            start_time = e.get("start_time")
            end_time = e.get("end_time")
            description = e.get("description")
            attendees_json = e.get("attendees_json")
            if attendees_json is None and e.get("attendees") is not None:
                attendees_json = json.dumps(e.get("attendees"))

            prior = c.execute(
                "SELECT title, start_time, end_time, attendees_json, description "
                "FROM calendar_events WHERE category = ? AND event_id = ?",
                (category, event_id),
            ).fetchone()
            if prior is None:
                new_count += 1
            elif (
                prior["title"] == title
                and prior["start_time"] == start_time
                and prior["end_time"] == end_time
                and prior["attendees_json"] == attendees_json
                and prior["description"] == description
            ):
                unchanged_count += 1
            else:
                updated_count += 1

            c.execute("""
                INSERT INTO calendar_events (
                    category, event_id, title, start_time, end_time,
                    attendees_json, description, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, event_id) DO UPDATE SET
                    title = excluded.title, start_time = excluded.start_time,
                    end_time = excluded.end_time, attendees_json = excluded.attendees_json,
                    description = excluded.description, fetched_at = excluded.fetched_at
            """, (
                category, event_id, title, start_time, end_time,
                attendees_json, description, fetched_at,
            ))

    return {
        "synced": new_count + updated_count,
        "new": new_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
    }


def sync_calendar_events_from_values(db, events: list[dict]) -> dict:
    """MCP-assisted path: caller already fetched and classified events (via
    the Calendar MCP `get_events` tool, category assigned by the calling
    agent) — just load them. Safe to re-run; upserts are idempotent."""
    return _load_events(db, events)
