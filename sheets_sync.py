"""Pulls the Team Tracking Sheet (Google Sheets) into the local `deals` table.

The sheet is exported in a grouped/hierarchical layout: the "Lead Sales
Engineer" and "Stage" columns are only populated on the first row of each
group and left blank on the rows that follow, and each group is interspersed
with "Subtotal" / "Total" rows. We forward-fill the group columns and drop
the subtotal rows to get one clean row per opportunity.
"""

import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

_HEADER_MAP = {
    "Lead Sales Engineer": "lead_se",
    "Stage": "stage",
    "Opportunity Name": "opportunity_name",
    "Account Owner Geo-Seg": "geo_seg",
    "Close Date": "close_date",
    "Amount": "amount",
    "SE Manager Notes": "se_manager_notes",
    "Pre-Sales Notes": "presales_notes",
    "Billing State/Province": "billing_state",
    "POC": "poc",
    "SE Needed": "se_needed",
    "Opportunity Record Type": "record_type",
    "Type": "type",
}

_SKIP_MARKERS = ("subtotal", "total")


def _client(service_account_json_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(service_account_json_path, scopes=_SCOPES)
    return gspread.authorize(creds)


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


def _parse_bool(raw: str) -> int:
    return 1 if str(raw).strip().upper() in ("TRUE", "YES", "Y", "1") else 0


def _parse_close_date(raw: str) -> str | None:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _quarter(iso_date: str | None) -> str | None:
    if not iso_date:
        return None
    d = datetime.strptime(iso_date, "%Y-%m-%d")
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _is_skip_row(cells: dict) -> bool:
    opp = (cells.get("opportunity_name") or "").strip()
    lead = (cells.get("lead_se") or "").strip()
    if not opp:
        return True
    joined = f"{lead} {opp}".lower()
    return any(marker in joined for marker in _SKIP_MARKERS)


def fetch_rows(service_account_json_path: str, sheet_id: str, worksheet_index: int = 0) -> list[dict]:
    """Read the sheet and return one normalized dict per real opportunity row."""
    ws = _client(service_account_json_path).open_by_key(sheet_id).get_worksheet(worksheet_index)
    values = ws.get_all_values()
    if not values:
        return []

    header = values[0]
    col_keys = [_HEADER_MAP.get(h.strip()) for h in header]

    rows: list[dict] = []
    fill = {"lead_se": "", "stage": ""}

    for raw_row in values[1:]:
        cells = {}
        for key, val in zip(col_keys, raw_row):
            if key:
                cells[key] = val.strip()

        for group_col in ("lead_se", "stage"):
            if cells.get(group_col):
                fill[group_col] = cells[group_col]
            else:
                cells[group_col] = fill[group_col]

        if _is_skip_row(cells):
            # A populated Lead SE on an otherwise-empty row still updates
            # the forward-fill value even though we don't keep the row.
            continue

        rows.append(cells)

    return rows


def sync_deals(db, service_account_json_path: str, sheet_id: str, worksheet_index: int = 0) -> dict:
    rows = fetch_rows(service_account_json_path, sheet_id, worksheet_index)

    se_rep_ids: dict[str, int] = {}
    with db.conn() as c:
        for row in c.execute("SELECT id, name FROM se_reps"):
            se_rep_ids[row["name"]] = row["id"]

    seen_keys = []
    with db.conn() as c:
        for row in rows:
            lead_se = row.get("lead_se") or "Unassigned"
            if lead_se not in se_rep_ids and lead_se != "Unassigned":
                cur = c.execute("INSERT INTO se_reps (name) VALUES (?)", (lead_se,))
                se_rep_ids[lead_se] = cur.lastrowid

            se_rep_id = se_rep_ids.get(lead_se)
            close_date = _parse_close_date(row.get("close_date", ""))
            sheet_key = "|".join([lead_se, row.get("stage", ""), row.get("opportunity_name", "")])
            seen_keys.append(sheet_key)

            c.execute("""
                INSERT INTO deals (
                    sheet_key, lead_se, se_rep_id, stage, opportunity_name, geo_seg,
                    close_date, amount, se_manager_notes, presales_notes, billing_state,
                    poc, se_needed, record_type, type, quarter, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(sheet_key) DO UPDATE SET
                    lead_se = excluded.lead_se, se_rep_id = excluded.se_rep_id,
                    stage = excluded.stage, geo_seg = excluded.geo_seg,
                    close_date = excluded.close_date, amount = excluded.amount,
                    se_manager_notes = excluded.se_manager_notes,
                    presales_notes = excluded.presales_notes,
                    billing_state = excluded.billing_state, poc = excluded.poc,
                    se_needed = excluded.se_needed, record_type = excluded.record_type,
                    type = excluded.type, quarter = excluded.quarter,
                    last_synced_at = datetime('now')
            """, (
                sheet_key, lead_se, se_rep_id, row.get("stage"), row.get("opportunity_name"),
                row.get("geo_seg"), close_date, _parse_amount(row.get("amount", "")),
                row.get("se_manager_notes"), row.get("presales_notes"), row.get("billing_state"),
                _parse_bool(row.get("poc", "")), _parse_bool(row.get("se_needed", "")),
                row.get("record_type"), row.get("type"), _quarter(close_date),
            ))

        if seen_keys:
            placeholders = ",".join("?" * len(seen_keys))
            c.execute(f"DELETE FROM deals WHERE sheet_key NOT IN ({placeholders})", seen_keys)

    db.set_setting("deals_last_synced_at", datetime.now().isoformat())
    return {"synced": len(rows)}
