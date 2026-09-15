"""Pulls the Team Tracking Sheet (Google Sheets) into the local `deals` table.

The sheet is exported in a grouped/hierarchical layout: the "Lead Sales
Engineer" and "Stage" columns are only populated on the first row of each
group and left blank on the rows that follow, and each group is interspersed
with "Subtotal" / "Total" rows. We forward-fill the group columns and drop
the subtotal rows to get one clean row per opportunity. Changing Lead SE
cascades a reset down to Stage, so a new lead's first (blank-stage) row can't
inherit the previous lead's stage — the same cascade closed_deals_sync and
tech_forecast_sync already had.

Shared grid parsing (amounts, dates, group-header cells, sheet keys, the
truncated-fetch guard) lives in `sheet_parse`; this module keeps only what is
specific to the open-pipeline tab and the `deals` table.
"""

from datetime import datetime

import sheet_parse
from db import utc_now_iso

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
    # Present in the SFDC export on some layouts and absent on others. When
    # it's there it becomes the row's key (see sheet_parse.build_sheet_key),
    # which is what makes a stage change or a slipped close date stop
    # delete-and-reinserting the row; when it isn't, the composite key plus
    # the override carry-forward in `load_rows` cover the same ground.
    "Opportunity ID": "opportunity_id",
}

# Headers we cannot do without: losing any one of them either empties the sync
# or silently re-keys every row.
_REQUIRED_HEADERS = (
    "Lead Sales Engineer",
    "Stage",
    "Opportunity Name",
    "Close Date",
    "Amount",
)

_GROUP_COLUMNS = ("lead_se", "stage")

# This tab's bare "-" group cell means "no lead assigned yet". Unlike the
# other two tabs (where it maps to "", a reset boundary), it's mapped to a
# real, truthy group name so it forward-fills like any other lead instead of
# silently inheriting whichever lead happened to precede it — the behaviour
# `load_rows`'s "Unassigned" fallback and the Team page already assume.
_UNASSIGNED_LEAD = "Unassigned"


def _client(service_account_json_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(service_account_json_path, scopes=_SCOPES)
    return gspread.authorize(creds)


def _parse_bool(raw: str) -> int:
    return 1 if str(raw).strip().upper() in ("TRUE", "YES", "Y", "1") else 0


def _quarter(iso_date: str | None) -> str | None:
    if not iso_date:
        return None
    d = datetime.strptime(iso_date, "%Y-%m-%d")
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _is_skip_row(cells: dict) -> bool:
    """Drop subtotal/total rows and anything without an opportunity name.

    The marker test is an EXACT match against each cell, not a substring scan
    over `lead_se` and `opportunity_name` joined together: that scan silently
    dropped any real opportunity whose name merely contained "total" —
    "TotalEnergies", "Total Rewards Platform" — which is indistinguishable
    from the deal never having been in the sheet at all.
    """
    if not (cells.get("opportunity_name") or "").strip():
        return True
    return any(
        sheet_parse.is_marker_cell(cells.get(field))
        for field in ("opportunity_name", *_GROUP_COLUMNS)
    )


def _normalize_values(values: list[list[str]]) -> list[dict]:
    """Turn a raw sheet grid (header row + data rows, e.g. `get_all_values()`
    or an MCP-fetched equivalent) into one normalized dict per real
    opportunity row."""
    if not values:
        return []

    col_keys = sheet_parse.map_header(
        values[0], _HEADER_MAP, _REQUIRED_HEADERS, label="deals sync"
    )

    rows: list[dict] = []
    fill = {col: "" for col in _GROUP_COLUMNS}

    for raw_row in values[1:]:
        cells = {}
        for key, val in zip(col_keys, raw_row):
            if key:
                cells[key] = (val or "").strip()

        for group_col in _GROUP_COLUMNS:
            # "-" reads as the real group name "Unassigned" here (see
            # _UNASSIGNED_LEAD); None means "blank cell or a bare
            # Subtotal/Total marker" — row-shape noise that must inherit the
            # current fill rather than reset it, since the per-lead subtotal
            # row puts the marker in the Lead SE column itself.
            label = sheet_parse.strip_group_label(
                cells.get(group_col, ""), unassigned=_UNASSIGNED_LEAD
            )
            if label is None:
                cells[group_col] = fill[group_col]
                continue
            fill[group_col] = cells[group_col] = label
            if group_col == "lead_se":
                # Cascade the reset downward: the next lead's first row is
                # usually blank in the Stage column, and without this it
                # inherited the *previous* lead's last stage — a silent
                # mis-stage, not a visible error. closed_deals_sync and
                # tech_forecast_sync have had this cascade; this one didn't.
                fill["stage"] = ""

        if _is_skip_row(cells):
            # A populated Lead SE on an otherwise-empty row still updates
            # the forward-fill value even though we don't keep the row.
            continue

        rows.append(cells)

    return rows


def fetch_rows(service_account_json_path: str, sheet_id: str, worksheet_index: int = 0) -> list[dict]:
    """Read the sheet via a service account and return normalized rows."""
    ws = _client(service_account_json_path).open_by_key(sheet_id).get_worksheet(worksheet_index)
    return _normalize_values(ws.get_all_values())


# Columns a human sets in the app, never the sheet. A sync must never clobber
# these (CLAUDE.md) — including by deleting and reinserting the row when its
# key changes, which is what `sheet_parse.match_rekeyed_rows` guards against.
_MANUAL_OVERRIDE_COLUMNS = ("backup_se_rep_id", "backup_note", "backup_assigned_at")


def load_rows(db, rows: list[dict], allow_shrink: bool = False) -> dict:
    """Upsert already-normalized rows into the `deals` table. Returns the
    documented synced/unchanged/deleted contract (this tab has no per-row
    fingerprint, so every payload row counts as synced and `unchanged` is
    always 0)."""
    synced_at = utc_now_iso()
    unparsed_amounts = 0
    carried_count = 0
    payload_rows: dict[str, dict] = {}

    # One connection block for the whole sync: reads, writes, the delete and
    # the "last synced" timestamp all land in a single transaction, so a
    # failure can't commit rows with a timestamp that disagrees with them.
    with db.conn() as c:
        # `deals.opportunity_id` is newer than this sync; probe for it rather
        # than assuming, so an older DB (or one mid-migration) still loads.
        has_opportunity_id = any(
            r["name"] == "opportunity_id" for r in c.execute("PRAGMA table_info(deals)")
        )

        se_rep_ids: dict[str, int] = {}
        for row in c.execute("SELECT id, name FROM se_reps"):
            se_rep_ids[row["name"]] = row["id"]

        existing_rows: dict[str, dict] = {}
        for r in c.execute(
            "SELECT sheet_key, opportunity_name, "
            + ("opportunity_id, " if has_opportunity_id else "'' AS opportunity_id, ")
            + ", ".join(_MANUAL_OVERRIDE_COLUMNS)
            + " FROM deals"
        ):
            existing_rows[r["sheet_key"]] = dict(r)

        # A truncated fetch looks exactly like a shrunken sheet; refuse before
        # we write anything rather than after we've deleted the missing rows.
        sheet_parse.guard_row_shrink("deals sync", len(existing_rows), len(rows), allow_shrink)

        for row in rows:
            lead_se = row.get("lead_se") or "Unassigned"
            if lead_se not in se_rep_ids and lead_se != "Unassigned":
                # New names arrive here from the sheet with no email, title or
                # review history. Inserting them active would make a stranger
                # (or a typo'd name) an immediate "current direct report" —
                # exactly what CLAUDE.md's departed-rep rule forbids. Land
                # them inactive; the Team page activates them after review.
                cur = c.execute(
                    "INSERT INTO se_reps (name, active) VALUES (?, 0)", (lead_se,)
                )
                se_rep_ids[lead_se] = cur.lastrowid

            se_rep_id = se_rep_ids.get(lead_se)
            close_date = sheet_parse.parse_date(row.get("close_date", ""))
            amount = sheet_parse.parse_amount(row.get("amount", ""))
            if sheet_parse.amount_unparsed(row.get("amount", ""), amount):
                unparsed_amounts += 1

            # Keyed on the opportunity ID when the sheet carries one. The old
            # lead|stage|name composite changed whenever a deal advanced a
            # stage or was reassigned, which hard-deleted the row and dropped
            # its backup-SE assignment.
            sheet_key = sheet_parse.build_sheet_key(
                row.get("opportunity_id"), lead_se, row.get("stage", ""),
                row.get("opportunity_name", ""),
            )
            payload_rows[sheet_key] = {
                "opportunity_id": row.get("opportunity_id"),
                "opportunity_name": row.get("opportunity_name"),
            }

            c.execute("""
                INSERT INTO deals (
                    sheet_key, lead_se, se_rep_id, stage, opportunity_name, geo_seg,
                    close_date, amount, se_manager_notes, presales_notes, billing_state,
                    poc, se_needed, record_type, type, quarter, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sheet_key) DO UPDATE SET
                    lead_se = excluded.lead_se, se_rep_id = excluded.se_rep_id,
                    -- Updatable now that the key can be the opportunity ID:
                    -- a renamed deal keeps its row instead of becoming one.
                    opportunity_name = excluded.opportunity_name,
                    stage = excluded.stage, geo_seg = excluded.geo_seg,
                    close_date = excluded.close_date, amount = excluded.amount,
                    se_manager_notes = excluded.se_manager_notes,
                    presales_notes = excluded.presales_notes,
                    billing_state = excluded.billing_state, poc = excluded.poc,
                    se_needed = excluded.se_needed, record_type = excluded.record_type,
                    type = excluded.type, quarter = excluded.quarter,
                    last_synced_at = excluded.last_synced_at
            """, (
                sheet_key, lead_se, se_rep_id, row.get("stage"), row.get("opportunity_name"),
                row.get("geo_seg"), close_date, amount,
                row.get("se_manager_notes"), row.get("presales_notes"), row.get("billing_state"),
                _parse_bool(row.get("poc", "")), _parse_bool(row.get("se_needed", "")),
                row.get("record_type"), row.get("type"), _quarter(close_date), synced_at,
            ))

            # Written separately rather than inlined into the INSERT above:
            # the column only exists on migrated DBs, and the sheet only
            # sometimes carries the header, so a conditional statement beats
            # building the INSERT's column list dynamically. No-ops entirely
            # when either side is absent.
            if has_opportunity_id and row.get("opportunity_id"):
                c.execute(
                    "UPDATE deals SET opportunity_id = ? WHERE sheet_key = ?",
                    (row.get("opportunity_id"), sheet_key),
                )

        deleted_count = 0
        if payload_rows:
            departing = {k: v for k, v in existing_rows.items() if k not in payload_rows}
            arriving = {k: v for k, v in payload_rows.items() if k not in existing_rows}
            # Second line of defence behind the opportunity-ID-first key: when
            # a row's key still changes (the sheet has no ID column, or a deal
            # was renamed), move the manual overrides onto its replacement
            # before the old row is deleted.
            for old_key, new_key in sheet_parse.match_rekeyed_rows(departing, arriving).items():
                carried = [departing[old_key][col] for col in _MANUAL_OVERRIDE_COLUMNS]
                if not any(v is not None for v in carried):
                    continue
                # COALESCE so a value already set on the new row wins — we are
                # restoring what the re-key dropped, never overwriting.
                c.execute(f"""
                    UPDATE deals SET
                        {", ".join(f"{col} = COALESCE({col}, ?)" for col in _MANUAL_OVERRIDE_COLUMNS)}
                    WHERE sheet_key = ?
                """, (*carried, new_key))
                carried_count += 1

            deleted_count = sheet_parse.delete_keys(c, "deals", departing)

        sheet_parse.write_setting(c, "deals_last_synced_at", synced_at, synced_at)

    return {
        "synced": len(payload_rows),
        "unchanged": 0,
        "deleted": deleted_count,
        "overrides_carried": carried_count,
        "unparsed_amounts": unparsed_amounts,
    }


def sync_deals(db, service_account_json_path: str, sheet_id: str, worksheet_index: int = 0,
               allow_shrink: bool = False) -> dict:
    """Credential-based path: read the sheet with a service account, then load."""
    return load_rows(db, fetch_rows(service_account_json_path, sheet_id, worksheet_index), allow_shrink)


def sync_deals_from_values(db, values: list[list[str]], allow_shrink: bool = False) -> dict:
    """MCP-assisted path: caller already fetched the raw grid (e.g. via the
    Google Sheets MCP tool) — normalize and load it, no service account needed.
    `allow_shrink` waives the truncated-fetch guard for a real big shrink."""
    return load_rows(db, _normalize_values(values), allow_shrink)
