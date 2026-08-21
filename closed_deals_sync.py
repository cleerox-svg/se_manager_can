"""Pulls the Team Tracking Sheet's "Sheet3" tab (closed-won / technical-win
export, e.g. from Clari) into the local `closed_deals` table.

Same grouped/hierarchical layout as the "SFDC" tab that `sheets_sync.py`
handles, but the group header carries a running dollar total instead of a
row count, e.g. "Sean Keleher (USD 1,095,169.27)" rather than "Nic Da Silva
(9)". We forward-fill the rep-name column and drop subtotal/total rows to
get one clean row per closed opportunity.
"""

import re
from datetime import datetime

_HEADER_MAP = {
    "Team Member Name": "rep_name",
    "Opportunity Name": "opportunity_name",
    "Amount (converted)": "amount",
    "Close Date": "close_date",
    "Presales Stage": "presales_stage",
}

_SKIP_MARKERS = ("subtotal", "total")

_GROUP_SUFFIX_RE = re.compile(r"\s*\(USD[^)]*\)\s*$")


def _strip_group_suffix(raw: str) -> str:
    """Strip the trailing running-total, e.g. 'Sean Keleher (USD 1,095,169.27)'
    -> 'Sean Keleher'. A bare 'Subtotal'/'Total' group cell collapses to ''
    so it never forward-fills and poisons the next rep's rows."""
    stripped = _GROUP_SUFFIX_RE.sub("", raw).strip()
    if stripped.lower() in _SKIP_MARKERS:
        return ""
    return stripped


def _parse_amount(raw: str) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_close_date(raw: str) -> str | None:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _is_skip_row(cells: dict) -> bool:
    opp = (cells.get("opportunity_name") or "").strip()
    rep = (cells.get("rep_name") or "").strip()
    if not opp:
        return True
    joined = f"{rep} {opp}".lower()
    return any(marker in joined for marker in _SKIP_MARKERS)


def _normalize_values(values: list[list[str]]) -> list[dict]:
    """Turn a raw Sheet3 grid (header row + data rows) into one normalized
    dict per real closed opportunity."""
    if not values:
        return []

    header = values[0]
    col_keys = [_HEADER_MAP.get(h.strip()) for h in header]

    rows: list[dict] = []
    fill = {"rep_name": ""}

    for raw_row in values[1:]:
        cells = {}
        for key, val in zip(col_keys, raw_row):
            if key:
                val = (val or "").strip()
                if key == "rep_name":
                    val = _strip_group_suffix(val)
                cells[key] = val

        if cells.get("rep_name"):
            fill["rep_name"] = cells["rep_name"]
        else:
            cells["rep_name"] = fill["rep_name"]

        if _is_skip_row(cells):
            continue

        cells["tech_win"] = 1 if cells.get("presales_stage") == "6 - Technical Win" else 0
        rows.append(cells)

    return rows


def load_rows(db, rows: list[dict]) -> dict:
    """Upsert already-normalized rows into the `closed_deals` table."""
    se_rep_ids: dict[str, int] = {}
    with db.conn() as c:
        for row in c.execute("SELECT id, name FROM se_reps"):
            se_rep_ids[row["name"]] = row["id"]

    seen_keys = []
    with db.conn() as c:
        for row in rows:
            rep_name = row.get("rep_name") or "Unassigned"
            se_rep_id = se_rep_ids.get(rep_name)
            close_date = _parse_close_date(row.get("close_date", ""))
            sheet_key = "|".join([rep_name, row.get("opportunity_name", ""), row.get("close_date", "")])
            seen_keys.append(sheet_key)

            c.execute("""
                INSERT INTO closed_deals (
                    sheet_key, rep_name, se_rep_id, opportunity_name, amount,
                    close_date, tech_win, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(sheet_key) DO UPDATE SET
                    rep_name = excluded.rep_name, se_rep_id = excluded.se_rep_id,
                    amount = excluded.amount, close_date = excluded.close_date,
                    tech_win = excluded.tech_win, last_synced_at = datetime('now')
            """, (
                sheet_key, rep_name, se_rep_id, row.get("opportunity_name"),
                _parse_amount(row.get("amount", "")), close_date, row.get("tech_win", 0),
            ))

        if seen_keys:
            placeholders = ",".join("?" * len(seen_keys))
            c.execute(f"DELETE FROM closed_deals WHERE sheet_key NOT IN ({placeholders})", seen_keys)

    db.set_setting("closed_deals_last_synced_at", datetime.now().isoformat())
    return {"synced": len(rows)}


def sync_closed_deals_from_values(db, values: list[list[str]]) -> dict:
    """MCP-assisted path: caller already fetched Sheet3's raw grid — normalize
    and load it, no service account needed."""
    return load_rows(db, _normalize_values(values))
