"""Pulls the Team Tracking Sheet's "Claude This q and next" tab (Technical
Forecast export — Presales Stage, Deal Forecast Status, Technical Win Date)
into the local `tech_forecast_deals` table. The sheet itself auto-refreshes
every 24 hours, so a live MCP fetch of this tab is always considered fresh —
this script does no staleness-of-fetch checking of its own.

Same grouped/hierarchical layout as the other tabs, nested two levels deep:
Lead Sales Engineer > Deal Forecast Status > individual deal rows. Each
level's group-header cell carries a row-count suffix ("Nic Da Silva (9)",
"Strong (8)") and each level has its own Subtotal row where the *next*
column over reads the literal word "Subtotal" instead of a real group name.
Deals with no Lead SE assigned yet group under a bare "-" instead of a name.
We forward-fill both group columns and drop any row with a blank
Opportunity Name (true for every subtotal/total row at every level, so it
alone is a reliable skip check).

As of 2026-09-02, Presales Stage is a flat per-deal column (like Stage or
Account Region), not a group level — each row carries its own value
(genuinely blank for some deals, e.g. brand-new pipeline not yet staged),
read straight through by the normal per-row cell mapping below. It used to
be the middle level of a three-level nesting (Lead SE > Presales Stage >
Deal Forecast Status); the sheet's underlying query was restructured to
expose it per-deal instead, which is strictly more precise for tracking
individual opportunities. Don't add it back to `_GROUP_LEVELS`.

Unlike the old "Satish Technical Forecast Current Q" tab this replaced, the
sheet now carries real Lead SE attribution natively (`lead_se_name`), so
`app.py` prefers a name match against `se_reps` over the old opportunity-
name-join heuristic — the join is kept only as a fallback for rows the name
match misses. `lead_se_name` being blank (the "-" group) is also surfaced
directly as `needs_lead_se` in `tech_forecast_report.py`, independent of
whatever attribution the app manages to resolve.

The sheet splits notes into three distinct columns — Pre-Sales Notes, SE
Manager Notes, and Pre-Sales Next Steps — all kept as separate fields.
Pre-Sales Next Steps is freeform, hand-typed text with no reliable
structured date. To flag "no update this week" we diff each row's
Pre-Sales Next Steps against the value it held as of the *previous* sync
(`notes_prev_sync`) rather than trying to parse dates out of the notes
text. Note that staleness is evaluated on BOTH sides of the fingerprint
gate in `load_rows`: an untouched row matches its fingerprint, and that is
precisely the row the flag exists to catch, so skipping it there meant
`notes_stale` could only ever fire when something *else* about the row had
changed.

Rows are keyed by Salesforce opportunity ID when the sheet carries one,
falling back to opportunity name + *parsed* close date (see
`sheet_parse.build_sheet_key`). The old raw-cell composite re-keyed a row
whenever a close date slipped — or was merely reformatted — which deleted
and reinserted it, taking `assigned_se_rep_id`/`backup_se_rep_id`/
`backup_note` with it. Where a re-key still happens, those overrides are
carried onto the replacement row before the old one is deleted.

The sheet's query isn't scoped to just our team — it also carries deals
whose account-owner manager is Greg Rainbird, a different sales org. We no
longer drop those rows; instead we tag them with a `product`/`segment` pair
(see `_OTHER_ORG_MANAGER_TAGS`) so they stay visible but are clearly marked
as belonging to a different org, even when one of our own Lead SEs is still
attached (e.g. Luis Santos, since gone inactive). Future cross-org managers
found mixed into this sheet's query should be added to the same mapping
rather than special-cased.
"""

import json
from datetime import date

import sheet_parse
import tech_forecast_report as report
from constants import PRESALES_TECH_WIN
from db import utc_now_iso

_HEADER_MAP = {
    "Lead Sales Engineer": "lead_se_name",
    "Presales Stage": "presales_stage",
    "Deal Forecast Status": "forecast_status",
    "Amount (converted)": "amount",
    "Opportunity Name": "opportunity_name",
    "Opportunity ID": "opportunity_id",
    "Opportunity Owner": "opportunity_owner",
    "Opportunity Owner: Manager": "opportunity_owner_manager",
    "Stage": "sales_stage",
    "Type": "deal_type",
    "Account Region": "account_region",
    "Close Date": "close_date",
    "Pre-Sales Notes": "pre_sales_notes",
    "SE Manager Notes": "se_manager_notes",
    "Pre-Sales Next Steps": "pre_sales_next_steps",
    "Technical Win Date": "technical_win_date",
    "Account Owner Geo-Seg": "geo_seg",
    "Account Owner Sales Segment": "sales_segment",
    "Account Owner Sales Geography": "sales_geo",
    "Pre-Sales confidence for Quarter": "confidence",
    "Billing State/Province": "billing_state_province",
}

_GROUP_LEVELS = ("lead_se_name", "forecast_status")

# Headers we cannot do without: losing any one of them either empties the sync
# or silently re-keys every row. A header that isn't here may go missing
# without failing the sync (its column is simply dropped).
_REQUIRED_HEADERS = (
    "Lead Sales Engineer",
    "Deal Forecast Status",
    "Opportunity Name",
    "Close Date",
    "Amount (converted)",
    "Presales Stage",
)

# Greg Rainbird's org is a different sales team — the sheet's underlying
# query pulls in deals across account-owner managers beyond ours, and his
# team's deals (even ones with one of our Lead SEs still attached from
# before they went inactive) aren't ours to track as if they were our own.
# Rather than dropping them, we tag them by Opportunity Owner: Manager
# (that's the field that actually identifies "whose org is this," not Lead
# SE) with a (product, segment) pair so they stay visible but distinguishable.
# Add future cross-org managers to this same mapping.
_OTHER_ORG_MANAGER_TAGS = {"greg rainbird": ("Auth0", "Enterprise/Strategic")}


def _org_tag(cells: dict) -> tuple:
    """(product, segment) for a cross-org row, or (None, None).

    Kept as its own helper because these two fields are re-derived on EVERY
    sync — deliberately outside `_FINGERPRINT_FIELDS` (a tag change is not a
    sheet change) — so both the insert path and the unchanged-row path below
    have to apply it. When only the insert path did, adding a manager to
    `_OTHER_ORG_MANAGER_TAGS` had no effect on rows already stored: they
    matched their fingerprint, skipped the upsert, and stayed untagged until
    something unrelated about them happened to change.
    """
    tag = _OTHER_ORG_MANAGER_TAGS.get(str(cells.get("opportunity_owner_manager") or "").strip().lower())
    return tag if tag else (None, None)


def _normalize_values(values: list[list[str]]) -> list[dict]:
    """Turn a raw Sheet4 grid (header row + data rows) into one normalized
    dict per real open technical-forecast deal."""
    if not values:
        return []

    col_keys = sheet_parse.map_header(
        values[0], _HEADER_MAP, _REQUIRED_HEADERS, label="tech forecast sync"
    )

    rows: list[dict] = []
    fill = {level: "" for level in _GROUP_LEVELS}
    # Most groups show their name+count label on the first deal row (normal
    # leading label, forward-filled below). But some groups' label never
    # appears on any deal row at all — it only shows up on that group's own
    # trailing Subtotal row, after every one of its deals has already been
    # read (confirmed against the live grid for Rishika Kondaveeti's and
    # Valentin Bourneuf's sections, 2026-09-03). `pending` buffers deal rows
    # since the last resolved boundary at each level so a late-arriving name
    # can be backfilled retroactively onto rows already appended to `rows`
    # (the buffered dicts are the same objects, mutated in place).
    pending: dict[str, list[dict]] = {level: [] for level in _GROUP_LEVELS}

    for raw_row in values[1:]:
        cells = {}
        for key, val in zip(col_keys, raw_row):
            if key:
                cells[key] = (val or "").strip()

        for level in _GROUP_LEVELS:
            label = sheet_parse.strip_group_label(cells.get(level, ""))
            if label is None:
                # Blank cell, or a bare "Subtotal"/"Total" marker artifact —
                # not a real group boundary, just row-shape noise (the marker
                # can bleed into a column that isn't even its own level).
                # Either way: keep whatever fill is active and keep buffering,
                # so a still-unresolved pending group isn't discarded here.
                cells[level] = fill[level]
                if not fill[level] and cells.get("opportunity_name"):
                    pending[level].append(cells)
            elif label:
                # A real name rode along on this cell — either a normal
                # leading label, or a late name arriving on this group's
                # own trailing Subtotal row. Either way, resolve whatever
                # deals are still waiting on a name at this level.
                for pending_row in pending[level]:
                    pending_row[level] = label
                pending[level] = []
                fill[level] = label
                cells[level] = label
                if level == "lead_se_name":
                    fill["forecast_status"] = ""
                    pending["forecast_status"] = []
            else:
                # Genuine "-" boundary (no Lead SE assigned yet) — this
                # level's group is really done; don't let it bleed into
                # whatever group comes next.
                fill[level] = ""
                pending[level] = []
                cells[level] = ""
                if level == "lead_se_name":
                    fill["forecast_status"] = ""
                    pending["forecast_status"] = []

        if not cells.get("opportunity_name"):
            continue

        cells["product"], cells["segment"] = _org_tag(cells)
        cells["is_tech_win"] = 1 if cells.get("presales_stage") == PRESALES_TECH_WIN else 0
        rows.append(cells)

    return rows


_FINGERPRINT_FIELDS = (
    "lead_se_name", "opportunity_name", "opportunity_id",
    "presales_stage", "forecast_status", "sales_stage", "deal_type",
    "account_region", "geo_seg", "sales_segment", "sales_geo",
    "opportunity_owner", "opportunity_owner_manager",
    "se_manager_notes", "pre_sales_notes", "pre_sales_next_steps",
    "confidence", "billing_state_province",
)


def _row_fingerprint(row: dict, close_date, technical_win_date, amount) -> str:
    return sheet_parse.row_fingerprint(
        row, _FINGERPRINT_FIELDS, (close_date, technical_win_date, amount)
    )


# Columns a human sets in the app, never the sheet. A sync must never clobber
# these (CLAUDE.md), which includes losing them to a delete/reinsert when a
# row's key changes — see `sheet_parse.build_sheet_key` / `match_rekeyed_rows`.
_MANUAL_OVERRIDE_COLUMNS = (
    "assigned_se_rep_id", "backup_se_rep_id", "backup_note", "backup_assigned_at",
)


def load_rows(db, rows: list[dict], allow_shrink: bool = False) -> dict:
    """Upsert already-normalized rows into the `tech_forecast_deals` table.
    Skips rewriting rows whose content hash matches the stored fingerprint,
    but still re-evaluates their staleness and org tags (both are derived from
    a comparison, not from the row's own content, so the fingerprint gate
    can't stand in for them). Returns counts of synced (changed+new),
    unchanged, and deleted rows."""
    existing_rows: dict[str, dict] = {}
    with db.conn() as c:
        for r in c.execute(
            "SELECT sheet_key, row_fingerprint, pre_sales_next_steps, opportunity_id, "
            "opportunity_name, notes_stale, product, segment, "
            "assigned_se_rep_id, backup_se_rep_id, backup_note, backup_assigned_at "
            "FROM tech_forecast_deals"
        ):
            existing_rows[r["sheet_key"]] = dict(r)

    # A truncated fetch looks exactly like a shrunken sheet; refuse before we
    # write anything rather than after we've deleted the missing rows.
    sheet_parse.guard_row_shrink(
        "tech forecast sync", len(existing_rows), len(rows), allow_shrink
    )

    payload_rows: dict[str, dict] = {}
    changed_count = 0
    unchanged_count = 0
    unparsed_amounts = 0
    synced_at = utc_now_iso()

    with db.conn() as c:
        for row in rows:
            close_date = sheet_parse.parse_date(row.get("close_date", ""))
            technical_win_date = sheet_parse.parse_date(row.get("technical_win_date", ""))
            amount = sheet_parse.parse_amount(row.get("amount", ""))
            if sheet_parse.amount_unparsed(row.get("amount", ""), amount):
                unparsed_amounts += 1
            # Parsed date, not the raw cell: a cell merely reformatted from
            # 5/4/2026 to 05/04/2026 must not look like a different deal.
            sheet_key = sheet_parse.build_sheet_key(
                row.get("opportunity_id"), row.get("opportunity_name", ""), close_date or ""
            )
            payload_rows[sheet_key] = {
                "opportunity_id": row.get("opportunity_id"),
                "opportunity_name": row.get("opportunity_name"),
            }

            new_fingerprint = _row_fingerprint(row, close_date, technical_win_date, amount)
            existing = existing_rows.get(sheet_key)

            new_next_steps = row.get("pre_sales_next_steps", "")
            prior_next_steps = existing["pre_sales_next_steps"] if existing else None
            # Stale = the Pre-Sales Next Steps text is byte-identical to what
            # the previous sync stored. That is precisely the case where
            # nothing else about the row changed either, so it must be
            # evaluated on BOTH sides of the fingerprint gate — computing it
            # only on the changed path meant the "nobody has touched this deal
            # in three weeks" row, the one the flag exists for, could never be
            # flagged at all.
            notes_stale = 1 if existing is not None and prior_next_steps == new_next_steps else 0
            product, segment = row.get("product"), row.get("segment")

            if existing is not None and existing["row_fingerprint"] == new_fingerprint:
                unchanged_count += 1
                c.execute("""
                    UPDATE tech_forecast_deals SET
                        notes_stale = ?, notes_prev_sync = ?, product = ?, segment = ?,
                        last_synced_at = ?
                    WHERE sheet_key = ?
                """, (notes_stale, prior_next_steps, product, segment, synced_at, sheet_key))
                continue

            changed_count += 1

            c.execute("""
                INSERT INTO tech_forecast_deals (
                    sheet_key, lead_se_name, opportunity_name, opportunity_id, amount, presales_stage,
                    forecast_status, sales_stage, deal_type, account_region, geo_seg, sales_segment,
                    sales_geo, close_date, technical_win_date, opportunity_owner, opportunity_owner_manager,
                    se_manager_notes, pre_sales_notes, pre_sales_next_steps, notes_prev_sync,
                    notes_stale, confidence, billing_state_province, product, segment,
                    row_fingerprint, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sheet_key) DO UPDATE SET
                    lead_se_name = excluded.lead_se_name,
                    -- Updatable now that the key can be the opportunity ID:
                    -- a renamed deal keeps its row instead of becoming one.
                    opportunity_name = excluded.opportunity_name,
                    opportunity_id = excluded.opportunity_id,
                    amount = excluded.amount,
                    presales_stage = excluded.presales_stage,
                    forecast_status = excluded.forecast_status, sales_stage = excluded.sales_stage,
                    deal_type = excluded.deal_type, account_region = excluded.account_region,
                    geo_seg = excluded.geo_seg, sales_segment = excluded.sales_segment,
                    sales_geo = excluded.sales_geo, close_date = excluded.close_date,
                    technical_win_date = excluded.technical_win_date,
                    opportunity_owner = excluded.opportunity_owner,
                    opportunity_owner_manager = excluded.opportunity_owner_manager,
                    se_manager_notes = excluded.se_manager_notes,
                    pre_sales_notes = excluded.pre_sales_notes,
                    pre_sales_next_steps = excluded.pre_sales_next_steps,
                    notes_prev_sync = excluded.notes_prev_sync,
                    notes_stale = excluded.notes_stale,
                    confidence = excluded.confidence,
                    billing_state_province = excluded.billing_state_province,
                    product = excluded.product,
                    segment = excluded.segment,
                    row_fingerprint = excluded.row_fingerprint,
                    last_synced_at = excluded.last_synced_at
            """, (
                sheet_key, row.get("lead_se_name"), row.get("opportunity_name"), row.get("opportunity_id"),
                amount,
                row.get("presales_stage"), row.get("forecast_status"), row.get("sales_stage"),
                row.get("deal_type"), row.get("account_region"), row.get("geo_seg"),
                row.get("sales_segment"), row.get("sales_geo"), close_date, technical_win_date,
                row.get("opportunity_owner"), row.get("opportunity_owner_manager"),
                row.get("se_manager_notes"), row.get("pre_sales_notes", ""), new_next_steps,
                prior_next_steps, notes_stale, row.get("confidence"), row.get("billing_state_province"),
                product, segment,
                new_fingerprint, synced_at,
            ))

        deleted_count = 0
        carried_count = 0
        if payload_rows:
            departing = {k: v for k, v in existing_rows.items() if k not in payload_rows}
            arriving = {k: v for k, v in payload_rows.items() if k not in existing_rows}
            # Second line of defence behind the opportunity-ID-first key: when
            # a row's key still changes (no ID in the sheet, or a renamed
            # deal), move the manual overrides onto its replacement before the
            # old row is deleted, so a slipped close date can't quietly wipe an
            # SE assignment.
            for old_key, new_key in sheet_parse.match_rekeyed_rows(departing, arriving).items():
                carried = [departing[old_key][col] for col in _MANUAL_OVERRIDE_COLUMNS]
                if not any(v is not None for v in carried):
                    continue
                # COALESCE so a value already set on the new row wins — we are
                # restoring what the re-key dropped, never overwriting.
                c.execute(f"""
                    UPDATE tech_forecast_deals SET
                        {", ".join(f"{col} = COALESCE({col}, ?)" for col in _MANUAL_OVERRIDE_COLUMNS)}
                    WHERE sheet_key = ?
                """, (*carried, new_key))
                carried_count += 1

            deleted_count = sheet_parse.delete_keys(c, "tech_forecast_deals", departing)

        # Same transaction as the rows it describes — a failure after the data
        # write must not leave the timestamp disagreeing with the data.
        sheet_parse.write_setting(c, "tech_forecast_last_synced_at", synced_at, synced_at)

    if changed_count or deleted_count:
        _capture_snapshot(db)
        # Snapshots carry a full per-deal state blob each day, so they grow
        # without bound; pruning here keeps it to the one place that adds a
        # row. build_weekly_deltas only ever reads the most recent prior
        # snapshot, and keep_min guards the delta baseline regardless of age.
        db.prune_snapshots()
    return {
        "synced": changed_count,
        "unchanged": unchanged_count,
        "deleted": deleted_count,
        "overrides_carried": carried_count,
        "unparsed_amounts": unparsed_amounts,
    }


def _capture_snapshot(db):
    """Records today's bucket totals + per-deal state so
    `tech_forecast_report.build_weekly_deltas` has a baseline to diff the
    *next* sync against. Upserts on `snapshot_date` so re-running a sync
    same-day (e.g. a fixup re-ingest) doesn't create a second baseline."""
    with db.conn() as c:
        rows = [
            dict(r) for r in c.execute(
                # `confidence` and `opportunity_id` are not decoration here:
                # aggregate_buckets keys on confidence (without it every
                # snapshot recorded a single degenerate "Untagged" bucket
                # forever), and build_weekly_deltas reads opportunity_id off
                # the prior snapshot to build the Salesforce link for a
                # dropped deal (without it, every dropped deal linked to null).
                "SELECT sheet_key, opportunity_name, opportunity_id, amount, presales_stage, "
                "forecast_status, confidence FROM tech_forecast_deals"
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


def sync_tech_forecast_from_values(db, values: list[list[str]], allow_shrink: bool = False) -> dict:
    """MCP-assisted path: caller already fetched Sheet4's raw grid — normalize
    and load it, no service account needed. `allow_shrink` waives the
    truncated-fetch guard for a sheet that really did shrink."""
    return load_rows(db, _normalize_values(values), allow_shrink)
