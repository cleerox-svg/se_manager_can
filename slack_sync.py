"""Pulls Slack activity for each active SE rep into the local `slack_notes` table.

Uses `search.messages`, which the Slack Web API only supports for a *user*
token (`xoxp-...`) — a bot token cannot call it. The token needs at least
the `search:read`, `users:read`, `channels:read` and `groups:read` user
scopes (see SETUP.md).
"""

from datetime import datetime, timedelta, timezone

# slack_sdk is imported inside the functions that need a token, so the
# MCP-assisted path (`sync_slack_notes_from_matches`) runs without it installed.

from db import utc_now_iso

_LOOKBACK_DAYS_DEFAULT = 90


def _slack_api_error():
    """The `SlackApiError` class, imported on demand.

    Only the token-based path can raise it, and that path has already imported
    slack_sdk by the time this is reached — keeping it out of module scope is
    what lets the credential-free path run without the package installed.
    """
    from slack_sdk.errors import SlackApiError

    return SlackApiError


def _ts_to_iso(ts: str) -> str:
    """Slack's `ts` is a UTC epoch. `fromtimestamp` without a tz renders it in
    the host's local time, so the same message imported from two machines gets
    two different `posted_at` values — and every one of them disagrees with the
    UTC `fetched_at` sitting next to it."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _search_for_rep(client, slack_user_id: str, after: str | None) -> list[dict]:
    query = f"from:<@{slack_user_id}>"
    if after:
        query += f" after:{after}"

    results = []
    page = 1
    while True:
        try:
            resp = client.search_messages(query=query, sort="timestamp", sort_dir="desc", count=100, page=page)
        except _slack_api_error() as e:
            raise RuntimeError(f"Slack search failed for {slack_user_id}: {e.response['error']}") from e

        matches = resp.get("messages", {}).get("matches", [])
        results.extend(matches)

        paging = resp.get("messages", {}).get("paging", {})
        if page >= paging.get("pages", 1) or page >= 5:
            break
        page += 1

    return results


def _load_matches(db, se_rep_id: int, matches: list[dict]) -> dict:
    """Upsert already-fetched search-result-shaped messages into `slack_notes`.

    Accepts either the raw `search.messages` shape (nested `channel: {id, name}`)
    or a flat shape (`channel_id`/`channel_name`) — the latter is what the
    MCP-assisted path passes in, since it's simpler to build by hand.

    Returns what was actually WRITTEN, not how many matches were handed to us:
    these upserts are idempotent, so re-running a sync used to report the same
    "synced" count as the first run and read as if a whole lookback window of
    new activity had just arrived."""
    fetched_at = utc_now_iso()
    new_count = 0
    updated_count = 0
    unchanged_count = 0

    with db.conn() as c:
        for m in matches:
            channel = m.get("channel") or {}
            channel_id = channel.get("id") or m.get("channel_id")
            channel_name = channel.get("name") or m.get("channel_name")
            ts = m.get("ts")
            posted_at = m.get("posted_at") or (_ts_to_iso(ts) if ts else None)

            prior = c.execute(
                "SELECT text, permalink FROM slack_notes "
                "WHERE se_rep_id = ? AND message_ts = ? AND channel_id = ?",
                (se_rep_id, ts, channel_id),
            ).fetchone()
            if prior is None:
                new_count += 1
            elif prior["text"] == m.get("text") and prior["permalink"] == m.get("permalink"):
                unchanged_count += 1
            else:
                updated_count += 1

            c.execute("""
                INSERT INTO slack_notes (
                    se_rep_id, message_ts, channel_id, channel_name, text, permalink, posted_at, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(se_rep_id, message_ts, channel_id) DO UPDATE SET
                    text = excluded.text, permalink = excluded.permalink,
                    fetched_at = excluded.fetched_at
            """, (
                se_rep_id, ts, channel_id, channel_name,
                m.get("text"), m.get("permalink"), posted_at, fetched_at,
            ))

    return {
        "synced": new_count + updated_count,
        "new": new_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
    }


def sync_slack_notes(db, slack_user_token: str, lookback_days: int = _LOOKBACK_DAYS_DEFAULT) -> dict:
    """Credential-based path: search as the token's user via the Slack API."""
    from slack_sdk import WebClient

    client = WebClient(token=slack_user_token)

    with db.conn() as c:
        reps = c.execute(
            "SELECT id, name, slack_user_id FROM se_reps WHERE active = 1 AND slack_user_id IS NOT NULL"
        ).fetchall()

    synced = {}
    for rep in reps:
        last_synced = db.get_setting(f"slack_last_synced_{rep['id']}")
        after = last_synced or (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).date().isoformat()

        matches = _search_for_rep(client, rep["slack_user_id"], after)
        counts = _load_matches(db, rep["id"], matches)

        # UTC, to match both the `after:` window we just searched and the
        # `fetched_at` stamped on the rows themselves.
        db.set_setting(
            f"slack_last_synced_{rep['id']}",
            datetime.now(timezone.utc).date().isoformat(),
        )
        synced[rep["name"]] = counts

    return synced


def sync_slack_notes_from_matches(db, se_rep_id: int, matches: list[dict]) -> dict:
    """MCP-assisted path: caller already fetched matches (e.g. via the Slack
    MCP search tool) — just load them. Safe to re-run; upserts are idempotent."""
    return _load_matches(db, se_rep_id, matches)
