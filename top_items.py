"""Top Items weekly summary — pure report-building + persistence helpers.

No Flask dependency — reused by app.py's routes. Mirrors tech_forecast_report.py's
convention of accepting a db instance and opening its own connection internally.
"""
from datetime import date

from salesforce_links import opportunity_url

_ROW_COLUMNS = "id, entry_date, content, status, created_at, updated_at"


def _row_to_dict(row):
    return dict(row) if row else None


def build_scaffold(db) -> str:
    with db.conn() as c:
        deal_rows = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM closed_deals "
                "WHERE sales_stage = '10 - Closed/Won' "
                "AND close_date >= date('now', '-7 days')"
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

    today = date.today()
    today_str = f"{today:%B} {today.day}, {today:%Y}"

    return f"""Date: {today_str}

- Hiring
  - _(add from calendar/email/Slack)_
- Customer Meetings/Win Labs
  - _(add from calendar/email/Slack)_
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
