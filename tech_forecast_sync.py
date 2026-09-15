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
text.

The sheet's query isn't scoped to just our team — it also carries deals
whose account-owner manager is Greg Rainbird, a different sales org. We no
longer drop those rows; instead we tag them with a `product`/`segment` pair
(see `_OTHER_ORG_MANAGER_TAGS`) so they stay visible but are clearly marked
as belonging to a different org, even when one of our own Lead SEs is still
attached (e.g. Luis Santos, since gone inactive). Future cross-org managers
found mixed into this sheet's query should be added to the same mapping
rather than special-cased.
"""

import hashlib
import json
import re
from datetime import date, datetime

import tech_forecast_report as report

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

_SKIP_MARKERS = ("subtotal", "total")

# Greg Rainbird's org is a different sales team — the sheet's underlying
# query pulls in deals across account-owner managers beyond ours, and his
# team's deals (even ones with one of our Lead SEs still attached from
# before they went inactive) aren't ours to track as if they were our own.
# Rather than dropping them, we tag them by Opportunity Owner: Manager
# (that's the field that actually identifies "whose org is this," not Lead
# SE) with a (product, segment) pair so they stay visible but distinguishable.
# Add future cross-org managers to this same mapping.
_OTHER_ORG_MANAGER_TAGS = {"greg rainbird": ("Auth0", "Enterprise/Strategic")}

_GROUP_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")


def _strip_group_suffix(raw: str) -> str | None:
    """Strip the trailing row-count, e.g. 'Nic Da Silva (11)' -> 'Nic Da
    Silva'. Returns one of three distinct signals, which the caller must
    NOT treat as interchangeable:

    - a real name/label, when one was present;
    - '' for the sheet's bare '-' placeholder ("no Lead SE assigned yet") —
      a genuine, intentional group boundary that should reset the
      forward-fill for this level (and cascade down for lead_se_name);
    - None for a bare 'Subtotal'/'Total' marker cell. This is a row-shape
      artifact, not a real group boundary — the same merged/bled-through
      header-cell text documented in sheets_sync.py's per-lead subtotal
      row, where the marker can land one column over from its own level.
      Collapsing this to '' (as '-' does) would make the caller reset
      `fill`/`pending` on pure noise, silently and permanently orphaning
      any deal rows still buffered waiting for a late-arriving group name
      (see `_normalize_values`) — the exact bug behind Nova/MacEwan/etc.
      showing up with a blank lead_se_name despite a real Lead SE in the
      sheet. Callers must treat None like a blank cell: inherit the
      current fill, keep buffering pending rows, never reset.
    """
    stripped = _GROUP_SUFFIX_RE.sub("", raw).strip()
    if stripped.lower() in _SKIP_MARKERS:
        return None
    if stripped == "-":
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
            raw_val = cells.get(level, "")
            if raw_val:
                stripped = _strip_group_suffix(raw_val)
                if stripped is None:
                    # Bare "Subtotal"/"Total" marker artifact — not a real
                    # group boundary, just row-shape noise (the marker can
                    # bleed into a column that isn't even its own level).
                    # Treat exactly like a blank cell: keep whatever fill
                    # is active and keep buffering, so a still-unresolved
                    # pending group isn't discarded by this row.
                    cells[level] = fill[level]
                    if not fill[level] and cells.get("opportunity_name"):
                        pending[level].append(cells)
                elif stripped:
                    # A real name rode along on this cell — either a normal
                    # leading label, or a late name arriving on this group's
                    # own trailing Subtotal row. Either way, resolve whatever
                    # deals are still waiting on a name at this level.
                    for pending_row in pending[level]:
                        pending_row[level] = stripped
                    pending[level] = []
                    fill[level] = stripped
                    cells[level] = stripped
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
            else:
                cells[level] = fill[level]
                if not fill[level] and cells.get("opportunity_name"):
                    pending[level].append(cells)

        if not cells.get("opportunity_name"):
            continue

        tag = _OTHER_ORG_MANAGER_TAGS.get(cells.get("opportunity_owner_manager", "").strip().lower())
        if tag:
            cells["product"], cells["segment"] = tag

        cells["is_tech_win"] = 1 if cells.get("presales_stage") == "6 - Technical Win" else 0
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
    parts = [row.get(f) or "" for f in _FINGERPRINT_FIELDS]
    parts += [close_date or "", technical_win_date or "", "" if amount is None else str(amount)]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def load_rows(db, rows: list[dict]) -> dict:
    """Upsert already-normalized rows into the `tech_forecast_deals` table.
    Skips rows whose content hash matches the stored fingerprint (unchanged rows).
    Returns counts of synced (changed+new), unchanged, and deleted rows."""
    existing_rows: dict[str, dict] = {}
    with db.conn() as c:
        for r in c.execute(
            "SELECT sheet_key, row_fingerprint, pre_sales_next_steps FROM tech_forecast_deals"
        ):
            existing_rows[r["sheet_key"]] = {
                "fingerprint": r["row_fingerprint"],
                "pre_sales_next_steps": r["pre_sales_next_steps"],
            }

    seen_keys: list[str] = []
    changed_count = 0
    unchanged_count = 0

    with db.conn() as c:
        for row in rows:
            close_date = _parse_date(row.get("close_date", ""))
            technical_win_date = _parse_date(row.get("technical_win_date", ""))
            amount = _parse_amount(row.get("amount", ""))
            sheet_key = "|".join([row.get("opportunity_name", ""), row.get("close_date", "")])
            seen_keys.append(sheet_key)

            new_fingerprint = _row_fingerprint(row, close_date, technical_win_date, amount)
            existing = existing_rows.get(sheet_key)

            if existing is not None and existing["fingerprint"] == new_fingerprint:
                unchanged_count += 1
                continue

            new_next_steps = row.get("pre_sales_next_steps", "")
            prior_next_steps = existing["pre_sales_next_steps"] if existing else None
            notes_stale = 1 if existing is not None and prior_next_steps == new_next_steps else 0
            changed_count += 1

            c.execute("""
                INSERT INTO tech_forecast_deals (
                    sheet_key, lead_se_name, opportunity_name, opportunity_id, amount, presales_stage,
                    forecast_status, sales_stage, deal_type, account_region, geo_seg, sales_segment,
                    sales_geo, close_date, technical_win_date, opportunity_owner, opportunity_owner_manager,
                    se_manager_notes, pre_sales_notes, pre_sales_next_steps, notes_prev_sync,
                    notes_stale, confidence, billing_state_province, product, segment,
                    row_fingerprint, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(sheet_key) DO UPDATE SET
                    lead_se_name = excluded.lead_se_name, opportunity_id = excluded.opportunity_id,
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
                    last_synced_at = datetime('now')
            """, (
                sheet_key, row.get("lead_se_name"), row.get("opportunity_name"), row.get("opportunity_id"),
                amount,
                row.get("presales_stage"), row.get("forecast_status"), row.get("sales_stage"),
                row.get("deal_type"), row.get("account_region"), row.get("geo_seg"),
                row.get("sales_segment"), row.get("sales_geo"), close_date, technical_win_date,
                row.get("opportunity_owner"), row.get("opportunity_owner_manager"),
                row.get("se_manager_notes"), row.get("pre_sales_notes", ""), new_next_steps,
                prior_next_steps, notes_stale, row.get("confidence"), row.get("billing_state_province"),
                row.get("product"), row.get("segment"),
                new_fingerprint,
            ))

        deleted_count = 0
        if seen_keys:
            to_delete = set(existing_rows) - set(seen_keys)
            deleted_count = len(to_delete)
            placeholders = ",".join("?" * len(seen_keys))
            c.execute(f"DELETE FROM tech_forecast_deals WHERE sheet_key NOT IN ({placeholders})", seen_keys)

    db.set_setting("tech_forecast_last_synced_at", datetime.now().isoformat())
    if changed_count or deleted_count:
        _capture_snapshot(db)
    return {"synced": changed_count, "unchanged": unchanged_count, "deleted": deleted_count}


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
