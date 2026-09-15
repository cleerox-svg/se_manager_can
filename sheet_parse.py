"""Shared parsing/loading helpers for the three Google Sheets → SQLite syncs.

`sheets_sync`, `closed_deals_sync` and `tech_forecast_sync` all consume the
same *kind* of export from the Team Tracking Sheet: a grouped/hierarchical
grid whose group-header cells carry a suffix, whose amounts and dates are
free text, and whose rows are keyed into SQLite by a synthetic `sheet_key`.
Those helpers were copy-pasted per module and drifted apart — the row-count
suffix regex existed only in two of them, the running-dollar-total suffix
only in the third, and the bare "-" placeholder was handled three different
ways (one of them not at all). Each divergence is resolved here in favour of
the *safest* behaviour, with the reason recorded inline, so a fix lands once
instead of three times (or, as happened, one time out of three).

This module deliberately has no `db`/Flask/gspread imports — it is pure
helpers plus a couple of cursor-level utilities the syncs share, so it stays
importable and testable on its own.
"""

import hashlib
import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------

_AMOUNT_STRIP_RE = re.compile(r"[^0-9.\-]")
_PARENS_WRAPPED_RE = re.compile(r"^\(.*\)$")


def parse_amount(raw) -> float | None:
    """Parse a sheet money cell (" $ 3,064.52 ", "USD 1,099,753.82") to float.

    Accounting-style negatives wrap the number in parentheses — "(1,234.00)"
    means -1234.00. The previous per-module copies stripped the parens along
    with every other non-numeric character and booked the value as POSITIVE,
    silently flipping the sign of every credit/adjustment/clawback row that
    reached a revenue total. Detect the wrapping parens before stripping.

    Returns None for a blank cell *and* for an unparseable one; callers that
    care about the difference use `amount_unparsed` to count the latter.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    negative = bool(_PARENS_WRAPPED_RE.match(text))
    cleaned = _AMOUNT_STRIP_RE.sub("", text)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative and value > 0 else value


def amount_unparsed(raw, parsed) -> bool:
    """True when a non-blank amount cell failed to parse.

    A silently-dropped amount is indistinguishable from a genuinely blank one
    once it's in the DB, so the syncs count these and surface the count in
    their result dict instead of losing money quietly.
    """
    return parsed is None and bool(str(raw or "").strip())


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

# The sheet's own export format drifts between these (and a merely reformatted
# date used to re-key a row — see `build_sheet_key`), which is why composite
# keys must be built from the PARSED value, never the raw cell.
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y")


def parse_date(raw) -> str | None:
    """Parse a sheet date cell to an ISO `YYYY-MM-DD` string, or None."""
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Grouped-layout group-header cells
# ---------------------------------------------------------------------------

# "Nic Da Silva (9)" / "2 - Discovery (3)" — a live row count appended to the
# group name by the sheet's grouping, not part of the name.
_COUNT_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")
# "Sean Keleher (USD 1,099,753.82)" — the closed-deals tab appends a running
# dollar total instead of a row count. Both forms are stripped everywhere now:
# each tab only ever uses one of them, so handling both is free, and the old
# split meant a tab that switched form would have silently kept the suffix as
# part of the rep's name (never matching `se_reps.name`).
_RUNNING_TOTAL_SUFFIX_RE = re.compile(r"\s*\(USD[^)]*\)\s*$")

# Matched against the *exact* stripped cell, never as a substring: a
# substring test drops real opportunities like "TotalEnergies" or "Total
# Rewards Platform".
SKIP_MARKERS = frozenset({"subtotal", "total", "grand total"})

# What a bare "-" group cell means: "no one assigned to this group yet".
UNASSIGNED_GROUP = ""


def _strip_suffixes(raw) -> str:
    return _RUNNING_TOTAL_SUFFIX_RE.sub("", _COUNT_SUFFIX_RE.sub("", str(raw or ""))).strip()


def strip_group_label(raw, *, unassigned: str = UNASSIGNED_GROUP) -> str | None:
    """Normalize a group-header cell into one of THREE distinct signals, which
    callers must not treat as interchangeable:

    - a real name/label, when one was present;
    - `unassigned` for the sheet's bare "-" placeholder ("nobody assigned
      yet") — a genuine, intentional group boundary that should reset the
      forward-fill for this level (and cascade the reset to levels below it).
      Callers that want "-" to behave as a *named* group instead pass
      `unassigned="Unassigned"`, which makes it a normal label;
    - None for a blank cell or a bare "Subtotal"/"Total" marker. A marker is
      a row-shape artifact, not a group boundary — the marker text can land
      one column over from its own level (see sheets_sync.py's per-lead
      subtotal row). Collapsing it to "" would make the caller reset
      `fill`/`pending` on pure noise, permanently orphaning deal rows still
      buffered waiting on a late-arriving group name — the exact bug behind
      NOVA Chemicals / MacEwan University losing their Lead SE (bf03fc7).
      Callers must treat None like a blank cell: inherit the current fill,
      keep buffering pending rows, never reset.

    The None-vs-"" distinction previously existed only in tech_forecast_sync;
    closed_deals_sync collapsed markers to "" and reset on them, and had no
    "-" handling at all (a literal "-" forward-filled into `rep_name` as if
    it were a person). Both now get the safe behaviour.
    """
    stripped = _strip_suffixes(raw)
    if not stripped or stripped.lower() in SKIP_MARKERS:
        return None
    if stripped == "-":
        return unassigned
    return stripped


def is_marker_cell(value) -> bool:
    """True when a cell is exactly a subtotal/total marker (suffix stripped).

    Exact match on the stripped cell, not a substring scan over several
    concatenated fields — that scan dropped any opportunity whose *name*
    merely contained "total".
    """
    return _strip_suffixes(value).lower() in SKIP_MARKERS


# ---------------------------------------------------------------------------
# Header mapping
# ---------------------------------------------------------------------------


def map_header(header, header_map: dict, required, *, label: str) -> list:
    """Map a sheet's header row to column keys, raising if the layout shifted.

    An unmapped header yields None and its column is dropped. That is fine for
    one stray column, but a shifted title row or a renamed export makes EVERY
    entry None: the sync then produces zero rows and reports a cheerful
    `{"synced": 0}`. A *partial* mismatch is worse — losing "Close Date"
    alone silently re-keys every row (see `build_sheet_key`) and, before the
    override carry-forward existed, wiped every manual SE assignment. Fail
    loudly instead, naming what's missing.
    """
    col_keys = [header_map.get(str(h or "").strip()) for h in header]
    resolved = {k for k in col_keys if k}
    missing = [h for h in required if header_map[h] not in resolved]
    if missing:
        raise ValueError(
            f"{label}: sheet header doesn't match the expected layout — missing "
            f"required column(s): {', '.join(missing)} "
            f"({len(resolved)} of {len(header)} columns recognized). "
            "Confirm the tab and range (the grid may start below row 1)."
        )
    return col_keys


# ---------------------------------------------------------------------------
# Row identity
# ---------------------------------------------------------------------------


def build_sheet_key(opportunity_id, *fallback_parts) -> str:
    """Stable per-row key: the Salesforce opportunity ID when the sheet gives
    us one, else a composite of the fallback parts.

    Every sync used to key rows purely on mutable columns (lead SE + stage +
    name, or name + close date). A slipped close date, an advanced stage — or
    merely a REFORMATTED date cell, "5/4/2026" vs "05/04/2026" — changed the
    key, so the old row was hard-deleted and reinserted fresh, dropping
    `assigned_se_rep_id` / `backup_se_rep_id` / `backup_note` on the floor.
    CLAUDE.md's "a sync must never clobber the manual overrides" rule, broken
    by the key itself.

    Callers must pass PARSED ISO dates into `fallback_parts`, never the raw
    cell, so a reformat alone can't re-key a row. The "oid:" prefix keeps the
    two key spaces from ever colliding.
    """
    oid = str(opportunity_id or "").strip()
    if oid:
        return f"oid:{oid}"
    return "|".join(str(p or "") for p in fallback_parts)


def row_fingerprint(row: dict, fields, extra=()) -> str:
    """Content hash used to skip rewriting rows that haven't changed."""
    parts = [str(row.get(f) or "") for f in fields]
    parts += ["" if v is None else str(v) for v in extra]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _match_index(rows: dict, field: str, lower: bool) -> dict:
    """Index key-by-field, dropping any field value that isn't unique — an
    ambiguous match is worse than no match when the payload is a manual
    override we'd be moving onto the wrong deal."""
    index: dict = {}
    for key, row in rows.items():
        value = str(row.get(field) or "").strip()
        if lower:
            value = value.lower()
        if not value:
            continue
        if value in index:
            index[value] = None  # ambiguous — poison it
        else:
            index[value] = key
    return {value: key for value, key in index.items() if key is not None}


def match_rekeyed_rows(departing: dict, incoming: dict) -> dict:
    """Map {old sheet_key: new sheet_key} for rows that were merely re-keyed.

    `departing` is the stored rows about to be deleted (present in the DB,
    absent from this payload) and `incoming` the payload rows that are new to
    the DB; both are {sheet_key: {"opportunity_id", "opportunity_name"}}.

    This is the belt to `build_sheet_key`'s braces: it carries manual
    overrides across a key change even when the sheet gives us no opportunity
    ID to key on. Opportunity ID is preferred; opportunity name is the
    fallback, and any name that isn't unique on both sides is skipped rather
    than guessed at.
    """
    by_id = _match_index(incoming, "opportunity_id", lower=False)
    by_name = _match_index(incoming, "opportunity_name", lower=True)
    departing_by_name = _match_index(departing, "opportunity_name", lower=True)

    matches: dict = {}
    for old_key, row in departing.items():
        oid = str(row.get("opportunity_id") or "").strip()
        new_key = by_id.get(oid) if oid else None
        if new_key is None:
            name = str(row.get("opportunity_name") or "").strip().lower()
            # Only match on name when it identifies exactly one row on BOTH
            # sides — two deals sharing a name must not swap overrides.
            if name and departing_by_name.get(name) == old_key:
                new_key = by_name.get(name)
        if new_key is not None:
            matches[old_key] = new_key
    return matches


# ---------------------------------------------------------------------------
# Write-side guards / utilities
# ---------------------------------------------------------------------------

# A sync deletes every stored row the payload didn't mention. That is correct
# for a genuinely shrinking sheet and catastrophic for a truncated fetch: the
# MCP read tool paginates and reads a bounded `A1:Z1000` range, so a tab that
# outgrows the range returns a VALID but short grid and the remainder — manual
# overrides included — is destroyed. Abort the delete when the payload is more
# than this far below what's stored, and make the caller pass allow_shrink for
# a legitimate big shrink (a fiscal-year rollover emptying the closed tab).
MIN_ROW_RETENTION_RATIO = 0.8

# SQLite's default host-parameter limit is 999 on older builds; chunk every
# key list rather than assuming the payload is small.
_PARAM_CHUNK = 400


def guard_row_shrink(label: str, stored_count: int, incoming_count: int, allow_shrink: bool = False) -> None:
    if allow_shrink or stored_count <= 0:
        return
    if incoming_count < stored_count * MIN_ROW_RETENTION_RATIO:
        raise RuntimeError(
            f"{label}: refusing to sync — payload has {incoming_count} rows but "
            f"{stored_count} are stored, a drop of "
            f"{(1 - incoming_count / stored_count) * 100:.0f}% (limit "
            f"{(1 - MIN_ROW_RETENTION_RATIO) * 100:.0f}%). This usually means a "
            "truncated fetch (the read range or a pagination cursor cut the grid "
            "short), not a real shrink. Re-fetch with a wider range, or pass "
            "allow_shrink=True if the sheet really did shrink this much."
        )


def chunked(seq, size: int = _PARAM_CHUNK):
    seq = list(seq)
    for start in range(0, len(seq), size):
        yield seq[start:start + size]


def delete_keys(c, table: str, keys) -> int:
    """Delete rows by explicit sheet_key.

    Deleting by the keys we mean to remove (rather than `NOT IN (every key we
    saw)`) keeps the parameter count proportional to the deletions and makes
    a truncated payload unable to blow past the host-parameter limit. `table`
    is always a module-level literal from the calling sync, never user input.
    """
    keys = list(keys)
    for chunk in chunked(keys):
        placeholders = ",".join("?" * len(chunk))
        c.execute(f"DELETE FROM {table} WHERE sheet_key IN ({placeholders})", chunk)
    return len(keys)


def write_setting(c, key: str, value: str, updated_at: str) -> None:
    """Write a `settings` row on the caller's cursor.

    Deliberately not `db.set_setting`: that opens its own `db.conn()` block,
    which — sharing the thread-local connection — commits the sync's data
    write early and leaves a window where rows are committed with a stale
    "last synced" timestamp (or vice versa). Writing it here puts the
    timestamp in the same transaction as the data it describes.
    """
    c.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, updated_at),
    )
