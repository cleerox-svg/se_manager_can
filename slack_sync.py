"""Pulls Slack activity for each active SE rep into the local `slack_notes` table.

Uses `search.messages`, which the Slack Web API only supports for a *user*
token (`xoxp-...`) — a bot token cannot call it. The token needs at least
the `search:read`, `users:read`, `channels:read` and `groups:read` user
scopes (see SETUP.md).
"""

from datetime import datetime, timedelta

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

_LOOKBACK_DAYS_DEFAULT = 90


def _ts_to_iso(ts: str) -> str:
    return datetime.fromtimestamp(float(ts)).isoformat()


def _search_for_rep(client: WebClient, slack_user_id: str, after: str | None) -> list[dict]:
    query = f"from:<@{slack_user_id}>"
    if after:
        query += f" after:{after}"

    results = []
    page = 1
    while True:
        try:
            resp = client.search_messages(query=query, sort="timestamp", sort_dir="desc", count=100, page=page)
        except SlackApiError as e:
            raise RuntimeError(f"Slack search failed for {slack_user_id}: {e.response['error']}") from e

        matches = resp.get("messages", {}).get("matches", [])
        results.extend(matches)

        paging = resp.get("messages", {}).get("paging", {})
        if page >= paging.get("pages", 1) or page >= 5:
            break
        page += 1

    return results


def _load_matches(db, se_rep_id: int, matches: list[dict]) -> int:
    """Upsert already-fetched search-result-shaped messages into `slack_notes`.

    Accepts either the raw `search.messages` shape (nested `channel: {id, name}`)
    or a flat shape (`channel_id`/`channel_name`) — the latter is what the
    MCP-assisted path passes in, since it's simpler to build by hand."""
    with db.conn() as c:
        for m in matches:
            channel = m.get("channel") or {}
            channel_id = channel.get("id") or m.get("channel_id")
            channel_name = channel.get("name") or m.get("channel_name")
            ts = m.get("ts")
            posted_at = m.get("posted_at") or (_ts_to_iso(ts) if ts else None)
            c.execute("""
                INSERT INTO slack_notes (
                    se_rep_id, message_ts, channel_id, channel_name, text, permalink, posted_at, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(se_rep_id, message_ts, channel_id) DO UPDATE SET
                    text = excluded.text, permalink = excluded.permalink, fetched_at = datetime('now')
            """, (
                se_rep_id, ts, channel_id, channel_name,
                m.get("text"), m.get("permalink"), posted_at,
            ))
    return len(matches)


def sync_slack_notes(db, slack_user_token: str, lookback_days: int = _LOOKBACK_DAYS_DEFAULT) -> dict:
    """Credential-based path: search as the token's user via the Slack API."""
    client = WebClient(token=slack_user_token)

    with db.conn() as c:
        reps = c.execute(
            "SELECT id, name, slack_user_id FROM se_reps WHERE active = 1 AND slack_user_id IS NOT NULL"
        ).fetchall()

    synced = {}
    for rep in reps:
        last_synced = db.get_setting(f"slack_last_synced_{rep['id']}")
        after = last_synced or (datetime.now() - timedelta(days=lookback_days)).date().isoformat()

        matches = _search_for_rep(client, rep["slack_user_id"], after)
        count = _load_matches(db, rep["id"], matches)

        db.set_setting(f"slack_last_synced_{rep['id']}", datetime.now().date().isoformat())
        synced[rep["name"]] = count

    return synced


def sync_slack_notes_from_matches(db, se_rep_id: int, matches: list[dict]) -> int:
    """MCP-assisted path: caller already fetched matches (e.g. via the Slack
    MCP search tool) — just load them. Safe to re-run; upserts are idempotent."""
    return _load_matches(db, se_rep_id, matches)
