"""Pulls the Team Tracking Sheet's "Canada SE Closed This Fiscal Year" tab
(closed-won export) into the local `closed_deals` table.

Grouped/hierarchical layout nested three levels deep: Team Member Name >
Team Role > Region (`_GROUP_LEVELS`), each group-header cell carrying a
running dollar total suffix instead of a row count, e.g. "Rishika
Kondaveeti (USD 2,538,735.02)" rather than "Nic Da Silva (9)". We
forward-fill all three group columns and cascade the reset downward — same
pattern as tech_forecast_sync.py's lead_se_name > forecast_status grouping —
so changing rep_name resets team_role and region, and changing team_role
resets region, meaning a new rep's or role's first row never inherits a
stale value left over from the group above it. As with tech_forecast_sync.py,
a `pending` buffer retroactively backfills deal rows in case a group's name
only ever appears on its own trailing Subtotal row rather than its leading
row. Team Role and Region are grouping-only fields used to walk this
structure correctly — neither is persisted to `closed_deals`.

Every row in this tab has Stage = "10 - Closed/Won" since the tab itself is
scoped to closed deals only; Presales Stage is a separate flat per-row
column (blank, or "6 - Technical Win") that drives the `tech_win` flag — it
is not a group level.

We drop subtotal/total rows and any row with a blank Opportunity Name to get
one clean row per closed opportunity.
"""

import re
from datetime import datetime

_HEADER_MAP = {
    "Team Member Name": "rep_name",
    "Team Role": "team_role",
    "Opportunity : Account Name : Account Owner : User Sales Region": "region",
    "Opportunity Name": "opportunity_name",
    "Amount (converted)": "amount",
    "Close Date": "close_date",
    "Presales Stage": "presales_stage",
    "Opportunity ID": "opportunity_id",
    "Stage": "sales_stage",
}

_GROUP_LEVELS = ("rep_name", "team_role", "region")

_SKIP_MARKERS = ("subtotal", "total")

_GROUP_SUFFIX_RE = re.compile(r"\s*\(USD[^)]*\)\s*$")


def _strip_group_suffix(raw: str) -> str:
    """Strip the trailing running-total, e.g. 'Sean Keleher (USD 1,095,169.27)'
    -> 'Sean Keleher'. A bare 'Subtotal'/'Total' group cell collapses to ''
    so it never forward-fills and poisons the next group's rows."""
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
    if not opp:
        return True
    joined = " ".join([
        cells.get("rep_name") or "",
        cells.get("team_role") or "",
        cells.get("region") or "",
        opp,
    ]).lower()
    return any(marker in joined for marker in _SKIP_MARKERS)


def _normalize_values(values: list[list[str]]) -> list[dict]:
    """Turn a raw grid (header row + data rows) into one normalized dict per
    real closed opportunity."""
    if not values:
        return []

    header = values[0]
    col_keys = [_HEADER_MAP.get(h.strip()) for h in header]

    rows: list[dict] = []
    fill = {level: "" for level in _GROUP_LEVELS}
    # A group's name usually rides on its first deal row (normal leading
    # label, forward-filled below), but some groups' name may only ever
    # appear on that group's own trailing Subtotal row, after every one of
    # its deals has already been read — same quirk tech_forecast_sync.py
    # handles for Lead SE groups. `pending` buffers deal rows since the last
    # resolved boundary at each level so a late-arriving name can be
    # backfilled retroactively onto rows already appended to `rows` (the
    # buffered dicts are the same objects, mutated in place).
    pending: dict[str, list[dict]] = {level: [] for level in _GROUP_LEVELS}

    for raw_row in values[1:]:
        cells = {}
        for key, val in zip(col_keys, raw_row):
            if key:
                cells[key] = (val or "").strip()

        for level in _GROUP_LEVELS:
            raw_val = cells.get(level, "")
            if raw_val:
                stripped = _strip_group_suffix(raw_val)
                if stripped:
                    for pending_row in pending[level]:
                        pending_row[level] = stripped
                    pending[level] = []
                    fill[level] = stripped
                    cells[level] = stripped
                else:
                    # Bare marker — this level's group is done; don't let it
                    # bleed into whatever group comes next.
                    fill[level] = ""
                    pending[level] = []
                    cells[level] = ""
                if level == "rep_name":
                    fill["team_role"] = ""
                    fill["region"] = ""
                    pending["team_role"] = []
                    pending["region"] = []
                elif level == "team_role":
                    fill["region"] = ""
                    pending["region"] = []
            else:
                cells[level] = fill[level]
                if not fill[level] and cells.get("opportunity_name"):
                    pending[level].append(cells)

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
                    sheet_key, rep_name, se_rep_id, opportunity_name, opportunity_id, amount,
                    close_date, sales_stage, tech_win, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(sheet_key) DO UPDATE SET
                    rep_name = excluded.rep_name, se_rep_id = excluded.se_rep_id,
                    opportunity_id = excluded.opportunity_id, amount = excluded.amount,
                    close_date = excluded.close_date, sales_stage = excluded.sales_stage,
                    tech_win = excluded.tech_win, last_synced_at = datetime('now')
            """, (
                sheet_key, rep_name, se_rep_id, row.get("opportunity_name"), row.get("opportunity_id"),
                _parse_amount(row.get("amount", "")), close_date, row.get("sales_stage"),
                row.get("tech_win", 0),
            ))

        if seen_keys:
            placeholders = ",".join("?" * len(seen_keys))
            c.execute(f"DELETE FROM closed_deals WHERE sheet_key NOT IN ({placeholders})", seen_keys)

    db.set_setting("closed_deals_last_synced_at", datetime.now().isoformat())
    return {"synced": len(rows)}


def sync_closed_deals_from_values(db, values: list[list[str]]) -> dict:
    """MCP-assisted path: caller already fetched the tab's raw grid —
    normalize and load it, no service account needed."""
    return load_rows(db, _normalize_values(values))
