"""Top Items weekly summary — pure report-building + persistence helpers.

No Flask dependency — reused by app.py's routes. Mirrors tech_forecast_report.py's
convention of accepting a db instance and opening its own connection internally.
"""
from datetime import date

from constants import STAGE_CLOSED_WON
from salesforce_links import opportunity_url

_ROW_COLUMNS = "id, entry_date, content, status, created_at, updated_at"

# Cap on the wins listed in the scaffold. A week's closed-won list is short in
# practice, but this block is pasted into a message a human reads, so the
# query is bounded rather than trusting the data to stay small.
DEFAULT_WINS_LIMIT = 25


def _row_to_dict(row):
    return dict(row) if row else None


def _calendar_rows(db, category, limit):
    with db.conn() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT title, start_time FROM calendar_events "
                "WHERE category = ? AND start_time >= date('now', '-7 days') "
                "ORDER BY start_time LIMIT ?",
                (category, limit),
            ).fetchall()
        ]


def _recruiting_rows(db, limit):
    with db.conn() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT text, posted_at FROM recruiting_notes "
                "WHERE posted_at >= date('now', '-7 days') "
                "ORDER BY posted_at LIMIT ?",
                (limit,),
            ).fetchall()
        ]


def _event_bullet(row):
    title = row.get("title") or "(untitled event)"
    start = (row.get("start_time") or "")[:10]
    return f"    - {title}" + (f" - {start}" if start else "")


def build_scaffold(db, wins_limit=DEFAULT_WINS_LIMIT) -> str:
    with db.conn() as c:
        # `closed_deals` holds Won *and* Lost rows, so the Closed/Won filter is
        # what keeps a lost deal out of the "wins" block — same rule CLAUDE.md
        # records for every dollar query against this table. Ordered and
        # bounded so the pasted list is deterministic top-down by ARR rather
        # than in SQLite's arbitrary row order.
        deal_rows = [
            dict(r)
            for r in c.execute(
                "SELECT opportunity_name, opportunity_id, amount FROM closed_deals "
                "WHERE sales_stage = ? "
                "AND close_date >= date('now', '-7 days') "
                "ORDER BY amount DESC, opportunity_name LIMIT ?",
                (STAGE_CLOSED_WON, wins_limit),
            ).fetchall()
        ]

    if deal_rows:
        wins = []
        for r in deal_rows:
            amount = r.get("amount") or 0
            link = opportunity_url(r.get("opportunity_id"))
            bullet = f"{r.get('opportunity_name')} ${amount:,.0f}"
            if link:
                bullet += f" - {link}"
            wins.append(f"    - {bullet}")
        wins_block = "\n".join(wins)
    else:
        wins_block = "    - _(no technical wins/closed deals synced this week)_"

    # Win Labs — high-confidence, same tier as Technical Wins: every invite
    # has "Win Lab" literally in the title, classified by the calendar-sync
    # agent before it ever reaches this table.
    win_lab_rows = _calendar_rows(db, "win_lab", wins_limit)
    if win_lab_rows:
        win_lab_block = "\n".join(_event_bullet(r) for r in win_lab_rows)
    else:
        win_lab_block = "    - _(no Win Labs synced this week)_"

    # Hiring — calendar interviews first, then Slack context from Cara
    # McArthy's recruiting DMs. Both are heuristic (title/description
    # keyword scan on the calendar side), reviewed by the manager before
    # sending like every other section here.
    hiring_interview_rows = _calendar_rows(db, "hiring_interview", wins_limit)
    recruiting_rows = _recruiting_rows(db, wins_limit)
    hiring_lines = [_event_bullet(r) for r in hiring_interview_rows]
    hiring_lines += [f"    - {r.get('text')}" for r in recruiting_rows if r.get("text")]
    if hiring_lines:
        hiring_block = "\n".join(hiring_lines)
    else:
        hiring_block = "    - _(no interviews or recruiting notes synced this week)_"

    # Customer Meetings — no consistent naming convention, so this is an
    # external-attendee heuristic (>= 1 attendee outside okta.com) rather
    # than a high-confidence signal. Explicit review-caveat header per the
    # plan, distinct from Win Labs/Technical Wins.
    customer_meeting_rows = _calendar_rows(db, "customer_meeting", wins_limit)
    if customer_meeting_rows:
        customer_meeting_block = "\n".join(_event_bullet(r) for r in customer_meeting_rows)
    else:
        customer_meeting_block = "    - _(no customer meetings synced this week)_"

    today = date.today()
    today_str = f"{today:%B} {today.day}, {today:%Y}"

    return f"""Date: {today_str}

- Hiring
{hiring_block}
- Customer Meetings/Win Labs
  - Win Labs
{win_lab_block}
  - Customer Meetings _(heuristic — review before sending)_
{customer_meeting_block}
- Canadian Public Sector
  - _(add from calendar/email/Slack)_
- Other
  - Technical Wins along with Deal Closed won last week
{wins_block}
"""


def get_latest(db) -> dict | None:
    with db.conn() as c:
        row = c.execute(
            f"SELECT {_ROW_COLUMNS} FROM top_items_entries ORDER BY entry_date DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row)


def get_history(db, limit=20) -> list[dict]:
    with db.conn() as c:
        rows = c.execute(
            f"SELECT {_ROW_COLUMNS} FROM top_items_entries ORDER BY entry_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_entry(db, content: str) -> dict:
    today = date.today().isoformat()
    with db.conn() as c:
        c.execute(
            "INSERT INTO top_items_entries (entry_date, content, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(entry_date) DO UPDATE SET "
            "content = excluded.content, updated_at = datetime('now')",
            (today, content),
        )
        row = c.execute(
            f"SELECT {_ROW_COLUMNS} FROM top_items_entries WHERE entry_date = ?", (today,)
        ).fetchone()
    return _row_to_dict(row)
