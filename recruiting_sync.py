"""Loads Cara McArthy's recruiting Slack DMs into the local
`recruiting_notes` table, for the Top Items scaffold's Hiring section.

Same shape as `slack_sync.py`'s MCP-assisted load path, minus `se_rep_id` —
Cara isn't an SE report, so there's no `se_reps` row to attach these notes
to. MCP-assisted only, same reasoning as `calendar_sync.py`: no
credential-based path, since this is filled by a live Claude Code session's
Slack MCP search, not a background job.
"""

from datetime import datetime, timezone

from db import utc_now_iso


def _ts_to_iso(ts: str) -> str:
    """Slack's `ts` is a UTC epoch — see `slack_sync._ts_to_iso` for why this
    must not be rendered in the host's local time."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _load_matches(db, matches: list[dict]) -> dict:
    """Upsert already-fetched Slack search matches into `recruiting_notes`.

    Returns what was actually WRITTEN, not how many matches were handed to
    us — same counting convention as `slack_sync._load_matches`."""
    fetched_at = utc_now_iso()
    new_count = 0
    updated_count = 0
    unchanged_count = 0

    with db.conn() as c:
        for m in matches:
            channel = m.get("channel") or {}
            channel_id = channel.get("id") or m.get("channel_id")
            ts = m.get("ts")
            posted_at = m.get("posted_at") or (_ts_to_iso(ts) if ts else None)

            prior = c.execute(
                "SELECT text, permalink FROM recruiting_notes "
                "WHERE message_ts = ? AND channel_id = ?",
                (ts, channel_id),
            ).fetchone()
            if prior is None:
                new_count += 1
            elif prior["text"] == m.get("text") and prior["permalink"] == m.get("permalink"):
                unchanged_count += 1
            else:
                updated_count += 1

            c.execute("""
                INSERT INTO recruiting_notes (
                    message_ts, channel_id, text, permalink, posted_at, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_ts, channel_id) DO UPDATE SET
                    text = excluded.text, permalink = excluded.permalink,
                    fetched_at = excluded.fetched_at
            """, (
                ts, channel_id, m.get("text"), m.get("permalink"), posted_at, fetched_at,
            ))

    return {
        "synced": new_count + updated_count,
        "new": new_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
    }


def sync_recruiting_notes_from_matches(db, matches: list[dict]) -> dict:
    """MCP-assisted path: caller already fetched matches (via the Slack MCP
    search tool) — just load them. Safe to re-run; upserts are idempotent."""
    return _load_matches(db, matches)
