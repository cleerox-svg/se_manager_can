"""Pulls the Team Tracking Sheet's "Sheet4" tab (Technical Forecast export —
Presales Stage, Deal Forecast Status, Technical Win Date) into the local
`tech_forecast_deals` table.

Same grouped/hierarchical layout as the other tabs, but nested three levels
deep instead of one: Account Owner AVP Region > Presales Stage > Deal
Forecast Status > individual deal rows. Each level's group-header cell
carries a row-count suffix ("AMER CAN (11)", "3 - Technical Scoping (2)",
"Strong (2)") and each level has its own Subtotal row where the *next*
column over reads the literal word "Subtotal" instead of a real group name.
We forward-fill all three group columns and drop any row with a blank
Opportunity Name (true for every subtotal/total row at every level, so it
alone is a reliable skip check).

This tab has no per-rep column at all (it's grouped by AE region, not by
SE), so unlike `deals`/`closed_deals` there's no `se_rep_id` column stored
on `tech_forecast_deals` — it covers the whole country's technical
pipeline, not just Claude Leroux's four tracked direct reports. SE
attribution for the Team page and Technical Forecast page is instead
derived live, in `app.py`, by matching each row's Opportunity Name against
`deals.opportunity_name` (which does carry `se_rep_id`) — not stored here,
so it always reflects the current `deals` table. Around 90% of current
rows match; unmatched rows (a deal that's since dropped off the open
pipeline) fall back to AE-only display.

Pre-Sales Next Steps is freeform, hand-typed text with no reliable
structured date. To flag "no update this week" we diff each row's
Pre-Sales Next Steps against the value it held as of the *previous* sync
(`notes_prev_sync`) rather than trying to parse dates out of the notes
text.
"""

import json
import re
from datetime import date, datetime

import tech_forecast_report as report

_HEADER_MAP = {
    "Account Owner AVP Region": "region",
    "Presales Stage": "presales_stage",
    "Deal Forecast Status": "forecast_status",
    "Amount (converted)": "amount",
    "Opportunity Name": "opportunity_name",
    "Opportunity Owner": "opportunity_owner",
    "Opportunity Owner: Manager": "opportunity_owner_manager",
    "Stage": "sales_stage",
    "Type": "deal_type",
    "Account Region": "account_region",
    "Close Date": "close_date",
    "SE Manager Notes": "se_manager_notes",
    "Pre-Sales Next Steps": "pre_sales_notes",
    "Technical Win Date": "technical_win_date",
    "Account Owner Geo-Seg": "geo_seg",
    "Account Owner Sales Segment": "sales_segment",
    "Account Owner Sales Geography": "sales_geo",
}

_GROUP_LEVELS = ("region", "presales_stage", "forecast_status")

_SKIP_MARKERS = ("subtotal", "total")

_GROUP_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")


def _strip_group_suffix(raw: str) -> str:
    """Strip the trailing row-count, e.g. 'AMER CAN (11)' -> 'AMER CAN'.
    A bare 'Subtotal'/'Total' group cell collapses to '' so it never
    forward-fills and poisons the next group's rows."""
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


def _parse_date(raw: str) -> str | None:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_values(values: list[list[str]]) -> list[dict]:
    """Turn a raw Sheet4 grid (header row + data rows) into one normalized
    dict per real open technical-forecast deal."""
    if not values:
        return []

    header = values[0]
    col_keys = [_HEADER_MAP.get(h.strip()) for h in header]

    rows: list[dict] = []
    fill = {level: "" for level in _GROUP_LEVELS}

    for raw_row in values[1:]:
        cells = {}
        for key, val in zip(col_keys, raw_row):
            if key:
                cells[key] = (val or "").strip()

        for level in _GROUP_LEVELS:
            raw_val = cells.get(level, "")
            stripped = _strip_group_suffix(raw_val)
            if stripped:
                if level == "presales_stage":
                    fill["forecast_status"] = ""
                fill[level] = stripped
                cells[level] = stripped
            else:
                cells[level] = fill[level]

        if not cells.get("opportunity_name"):
            continue

        cells["is_tech_win"] = 1 if cells.get("presales_stage") == "6 - Technical Win" else 0
        rows.append(cells)

    return rows


def load_rows(db, rows: list[dict]) -> dict:
    """Upsert already-normalized rows into the `tech_forecast_deals` table,
    diffing Pre-Sales Next Steps against the prior sync to flag stale rows."""
    seen_keys = []
    with db.conn() as c:
        for row in rows:
            close_date = _parse_date(row.get("close_date", ""))
            technical_win_date = _parse_date(row.get("technical_win_date", ""))
            sheet_key = "|".join([row.get("opportunity_name", ""), row.get("close_date", "")])
            seen_keys.append(sheet_key)

            new_notes = row.get("pre_sales_notes", "")
            existing = c.execute(
                "SELECT pre_sales_notes FROM tech_forecast_deals WHERE sheet_key = ?", (sheet_key,)
            ).fetchone()
            prior_notes = existing["pre_sales_notes"] if existing else None
            notes_stale = 1 if existing is not None and prior_notes == new_notes else 0

            c.execute("""
                INSERT INTO tech_forecast_deals (
                    sheet_key, opportunity_name, amount, presales_stage, forecast_status,
                    sales_stage, deal_type, account_region, geo_seg, sales_segment, sales_geo,
                    close_date, technical_win_date, opportunity_owner, opportunity_owner_manager,
                    se_manager_notes, pre_sales_notes, notes_prev_sync, notes_stale, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(sheet_key) DO UPDATE SET
                    amount = excluded.amount, presales_stage = excluded.presales_stage,
                    forecast_status = excluded.forecast_status, sales_stage = excluded.sales_stage,
                    deal_type = excluded.deal_type, account_region = excluded.account_region,
                    geo_seg = excluded.geo_seg, sales_segment = excluded.sales_segment,
                    sales_geo = excluded.sales_geo, close_date = excluded.close_date,
                    technical_win_date = excluded.technical_win_date,
                    opportunity_owner = excluded.opportunity_owner,
                    opportunity_owner_manager = excluded.opportunity_owner_manager,
                    se_manager_notes = excluded.se_manager_notes,
                    pre_sales_notes = excluded.pre_sales_notes,
                    notes_prev_sync = excluded.notes_prev_sync,
                    notes_stale = excluded.notes_stale, last_synced_at = datetime('now')
            """, (
                sheet_key, row.get("opportunity_name"), _parse_amount(row.get("amount", "")),
                row.get("presales_stage"), row.get("forecast_status"), row.get("sales_stage"),
                row.get("deal_type"), row.get("account_region"), row.get("geo_seg"),
                row.get("sales_segment"), row.get("sales_geo"), close_date, technical_win_date,
                row.get("opportunity_owner"), row.get("opportunity_owner_manager"),
                row.get("se_manager_notes"), new_notes, prior_notes, notes_stale,
            ))

        if seen_keys:
            placeholders = ",".join("?" * len(seen_keys))
            c.execute(f"DELETE FROM tech_forecast_deals WHERE sheet_key NOT IN ({placeholders})", seen_keys)

    db.set_setting("tech_forecast_last_synced_at", datetime.now().isoformat())
    _capture_snapshot(db)
    return {"synced": len(rows)}


def _capture_snapshot(db):
    """Records today's bucket totals + per-deal state so
    `tech_forecast_report.build_weekly_deltas` has a baseline to diff the
    *next* sync against. Upserts on `snapshot_date` so re-running a sync
    same-day (e.g. a fixup re-ingest) doesn't create a second baseline."""
    with db.conn() as c:
        rows = [
            dict(r) for r in c.execute(
                "SELECT sheet_key, opportunity_name, amount, presales_stage, forecast_status "
                "FROM tech_forecast_deals"
            ).fetchall()
        ]
    deal_states = {r["sheet_key"]: r for r in rows}
    bucket_totals = report.aggregate_buckets(rows)
    with db.conn() as c:
        c.execute("""
            INSERT INTO tech_forecast_snapshots (snapshot_date, bucket_totals_json, deal_states_json)
            VALUES (?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                bucket_totals_json = excluded.bucket_totals_json,
                deal_states_json = excluded.deal_states_json
        """, (date.today().isoformat(), json.dumps(bucket_totals), json.dumps(deal_states)))


def sync_tech_forecast_from_values(db, values: list[list[str]]) -> dict:
    """MCP-assisted path: caller already fetched Sheet4's raw grid — normalize
    and load it, no service account needed."""
    return load_rows(db, _normalize_values(values))
