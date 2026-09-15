"""Pulls the Team Tracking Sheet's "Canada SE Closed This Fiscal Year" tab
(closed deals export, both Closed/Won and Closed/Lost) into the local
`closed_deals` table.

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

Stage carries both "10 - Closed/Won" and a Closed/Lost value — the tab is
scoped to closed deals, not won deals only. Presales Stage is a separate
flat per-row column (blank, or "6 - Technical Win") that drives the
`tech_win` flag — it is not a group level.

We drop subtotal/total rows and any row with a blank Opportunity Name to get
one clean row per closed opportunity. Group-cell parsing now goes through
`sheet_parse.strip_group_label`, which converges this tab on the *safest* of
the three syncs' previously divergent behaviours: a bare Subtotal/Total marker
is treated as row-shape noise (inherit the fill, keep buffering) rather than a
group boundary, and a bare "-" — previously unhandled here, so it
forward-filled into `rep_name` as if it were a person — now reads as "nobody
assigned" and lands as "Unassigned".
"""

import sheet_parse
from constants import PRESALES_TECH_WIN
from db import utc_now_iso

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

# Headers we cannot do without: losing any one of them either empties the sync
# or silently re-keys every row (see sheet_parse.build_sheet_key). The long
# Region header is not in here — it's grouping-only and never persisted.
_REQUIRED_HEADERS = (
    "Team Member Name",
    "Opportunity Name",
    "Amount (converted)",
    "Close Date",
    "Stage",
    "Presales Stage",
)


def _is_skip_row(cells: dict) -> bool:
    """Drop subtotal/total rows and anything without an opportunity name.

    The marker test is an EXACT match against each cell, not a substring scan
    over the concatenated fields: that scan silently dropped any real
    opportunity whose name merely contained "total" — "TotalEnergies", "Total
    Rewards Platform" — which looks identical to the deal never having been
    in the sheet.
    """
    if not (cells.get("opportunity_name") or "").strip():
        return True
    return any(
        sheet_parse.is_marker_cell(cells.get(field))
        for field in ("opportunity_name", *_GROUP_LEVELS)
    )


def _normalize_values(values: list[list[str]]) -> list[dict]:
    """Turn a raw grid (header row + data rows) into one normalized dict per
    real closed opportunity."""
    if not values:
        return []

    col_keys = sheet_parse.map_header(
        values[0], _HEADER_MAP, _REQUIRED_HEADERS, label="closed deals sync"
    )

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
            label = sheet_parse.strip_group_label(cells.get(level, ""))
            if label is None:
                # Blank cell, or a bare Subtotal/Total marker. Previously a
                # marker reset `fill`/`pending` here; it no longer does. A
                # marker is row-shape noise that can land one column over from
                # its own level, and resetting on it discards deal rows still
                # buffered waiting for a late-arriving group name — the bug
                # bf03fc7 fixed in tech_forecast_sync, which this tab's copy
                # of the loop still had. Inherit the fill and keep buffering.
                cells[level] = fill[level]
                if not fill[level] and cells.get("opportunity_name"):
                    pending[level].append(cells)
                continue

            if label:
                for pending_row in pending[level]:
                    pending_row[level] = label
                cells[level] = label
            else:
                # Bare "-" placeholder: a genuine "nobody assigned" boundary.
                # This tab's stripper used to have no "-" case at all, so a
                # literal "-" forward-filled into `rep_name` as though it were
                # a person's name; load_rows now maps the resulting blank to
                # "Unassigned" like any other unattributed row.
                cells[level] = ""
            pending[level] = []
            fill[level] = cells[level]
            # Cascade the reset downward: a new rep's (or role's) first row
            # must never inherit the group below it from the previous one.
            if level == "rep_name":
                fill["team_role"] = fill["region"] = ""
                pending["team_role"] = []
                pending["region"] = []
            elif level == "team_role":
                fill["region"] = ""
                pending["region"] = []

        if _is_skip_row(cells):
            continue

        cells["tech_win"] = 1 if cells.get("presales_stage") == PRESALES_TECH_WIN else 0
        rows.append(cells)

    return rows


_FINGERPRINT_FIELDS = ("rep_name", "opportunity_name", "opportunity_id", "sales_stage", "tech_win")


def _row_fingerprint(row: dict, close_date, amount) -> str:
    return sheet_parse.row_fingerprint(row, _FINGERPRINT_FIELDS, (close_date, amount))


def load_rows(db, rows: list[dict], allow_shrink: bool = False) -> dict:
    """Upsert already-normalized rows into the `closed_deals` table, skipping
    any row whose fingerprint matches what's already stored so an unchanged
    row is never rewritten."""
    se_rep_ids: dict[str, int] = {}
    with db.conn() as c:
        for row in c.execute("SELECT id, name FROM se_reps"):
            se_rep_ids[row["name"]] = row["id"]

    existing_fingerprints: dict[str, str] = {}
    with db.conn() as c:
        for r in c.execute("SELECT sheet_key, row_fingerprint FROM closed_deals"):
            existing_fingerprints[r["sheet_key"]] = r["row_fingerprint"]

    # A truncated fetch looks exactly like a shrunken sheet; refuse before we
    # write anything rather than after we've deleted the missing rows.
    sheet_parse.guard_row_shrink(
        "closed deals sync", len(existing_fingerprints), len(rows), allow_shrink
    )

    seen_keys: set = set()
    changed_count = 0
    unchanged_count = 0
    unparsed_amounts = 0
    synced_at = utc_now_iso()

    with db.conn() as c:
        for row in rows:
            rep_name = row.get("rep_name") or "Unassigned"
            se_rep_id = se_rep_ids.get(rep_name)
            close_date = sheet_parse.parse_date(row.get("close_date", ""))
            amount = sheet_parse.parse_amount(row.get("amount", ""))
            if sheet_parse.amount_unparsed(row.get("amount", ""), amount):
                unparsed_amounts += 1
            # Opportunity ID first, and the PARSED date in the fallback: a
            # close date that merely slipped or got reformatted must not
            # delete-and-reinsert the row. `closed_deals` carries no manual
            # override columns, so nothing is lost when it does re-key — but
            # the churn shows up as phantom synced/deleted counts.
            sheet_key = sheet_parse.build_sheet_key(
                row.get("opportunity_id"), rep_name, row.get("opportunity_name", ""), close_date or ""
            )
            seen_keys.add(sheet_key)

            fingerprint_row = dict(row, rep_name=rep_name)
            new_fingerprint = _row_fingerprint(fingerprint_row, close_date, amount)

            if existing_fingerprints.get(sheet_key) == new_fingerprint:
                unchanged_count += 1
                continue

            changed_count += 1
            c.execute("""
                INSERT INTO closed_deals (
                    sheet_key, rep_name, se_rep_id, opportunity_name, opportunity_id, amount,
                    close_date, sales_stage, tech_win, row_fingerprint, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sheet_key) DO UPDATE SET
                    rep_name = excluded.rep_name, se_rep_id = excluded.se_rep_id,
                    -- Updatable now that the key can be the opportunity ID:
                    -- a renamed deal keeps its row instead of becoming one.
                    opportunity_name = excluded.opportunity_name,
                    opportunity_id = excluded.opportunity_id, amount = excluded.amount,
                    close_date = excluded.close_date, sales_stage = excluded.sales_stage,
                    tech_win = excluded.tech_win, row_fingerprint = excluded.row_fingerprint,
                    last_synced_at = excluded.last_synced_at
            """, (
                sheet_key, rep_name, se_rep_id, row.get("opportunity_name"), row.get("opportunity_id"),
                amount, close_date, row.get("sales_stage"), row.get("tech_win", 0), new_fingerprint,
                synced_at,
            ))

        deleted_count = 0
        if seen_keys:
            deleted_count = sheet_parse.delete_keys(
                c, "closed_deals", set(existing_fingerprints) - seen_keys
            )

        # Same transaction as the rows it describes — a failure after the data
        # write must not leave the timestamp disagreeing with the data.
        sheet_parse.write_setting(c, "closed_deals_last_synced_at", synced_at, synced_at)

    return {
        "synced": changed_count,
        "unchanged": unchanged_count,
        "deleted": deleted_count,
        "unparsed_amounts": unparsed_amounts,
    }


def sync_closed_deals_from_values(db, values: list[list[str]], allow_shrink: bool = False) -> dict:
    """MCP-assisted path: caller already fetched the tab's raw grid —
    normalize and load it, no service account needed. `allow_shrink` waives
    the truncated-fetch guard for a tab that really did shrink (e.g. a fiscal
    year rollover emptying it)."""
    return load_rows(db, _normalize_values(values), allow_shrink)
