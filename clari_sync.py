"""Parses the weekly Clari AE-level CSV exports Claude Leroux drops in the
Clari Reporting folder (This Quarter / Next Quarter) into `clari_ae_snapshots`.

Clari has no MCP/API surface reachable from this app, so unlike
`tech_forecast_sync.py`/`closed_deals_sync.py` there's no fetch-vs-load
split — this script reads the local file directly. The export is a long/
tidy weekly time series per AE (Field, Data Type, Week, Start Day, End Day,
Data Value), not deal-level data, and carries zero opportunity- or SE-level
identifiers (confirmed: no SE names/initials anywhere, even in freeform
notes columns). The one clean join key is `User`, which is an exact string
match for `tech_forecast_deals.opportunity_owner`.

Each Field has its own valid Data Type sub-rows — most combinations aren't
meaningful (freeform Notes/Adjustment Notes, "Forecast Updated" Yes/No,
etc.) — so only the pairs in `tech_forecast_report.CLARI_ALLOWED_PAIRS` are
kept. Clari also exports a monthly breakdown for Forecast/Forecast[Auth]/
Forecast[Okta] under Timeframe values like "August FY 2027" alongside the
quarterly rollup ("Q3"/"Q4" — the label shifts by fiscal quarter, so this
matches the bare "Q<n>" pattern rather than hardcoding one); only that
rollup row is kept, so this always reports the AE's whole-quarter numbers,
matching how Quota/Gap/Coverage are scoped natively (they have no monthly
breakdown at all).

Week index isn't trustworthy on its own (it resets/shifts across exports) —
rows are matched against *today's* date falling within Start Day/End Day.
"""

import csv
import glob
import os
import re
from datetime import date, datetime

import tech_forecast_report as report

CLARI_EXPORT_DIR = os.environ.get(
    "CLARI_EXPORT_DIR",
    r"C:\Users\ClaudeLeroux\Desktop\Claude Code Projects\Clari Reporting",
)

_QUARTER_ROLLUP_RE = re.compile(r"^Q\d+$")


def _find_export_file(source_label: str) -> str:
    candidates = glob.glob(os.path.join(CLARI_EXPORT_DIR, "*.csv"))
    needle = "this quarter" if source_label == "this_quarter" else "next quarter"
    matches = [
        f for f in candidates
        if needle in os.path.basename(f).lower().replace("_", " ")
    ]
    if not matches:
        raise FileNotFoundError(f"No Clari export matching '{needle}' found in {CLARI_EXPORT_DIR}")
    return max(matches, key=os.path.getmtime)


def _parse_date(raw: str):
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_rows(f, today=None) -> list[dict]:
    """Reads an already-open Clari CSV file object, returns normalized rows
    for today's week, restricted to the allow-listed (Field, Data Type)
    pairs and the quarterly-rollup Timeframe."""
    today = today or date.today()
    reader = csv.DictReader(f)
    out = []
    for row in reader:
        pair = (row.get("Field", "").strip(), row.get("Data Type", "").strip())
        if pair not in report.CLARI_ALLOWED_PAIRS:
            continue
        if not _QUARTER_ROLLUP_RE.match((row.get("Timeframe") or "").strip()):
            continue
        start = _parse_date(row.get("Start Day", ""))
        end = _parse_date(row.get("End Day", ""))
        if not start or not end or not (start <= today <= end):
            continue

        raw_value = row.get("Data Value", "")
        numeric, kind = report.parse_clari_value(raw_value)
        out.append({
            "ae_name": row.get("User", "").strip(),
            "ae_email": row.get("Email", "").strip(),
            "role": row.get("Role", "").strip(),
            "parent_role": row.get("Parent Role", "").strip(),
            "field": pair[0],
            "data_type": pair[1],
            "data_value": raw_value,
            "data_value_numeric": numeric,
            "data_value_kind": kind,
            "start_day": start.isoformat(),
            "end_day": end.isoformat(),
        })
    return out


def load_rows(db, source_label: str, rows: list[dict]) -> dict:
    """Upserts normalized rows into `clari_ae_snapshots`, scoped to
    `source_label` so a this_quarter sync never deletes next_quarter's rows
    (and vice versa) since both files share one table."""
    seen_keys = []
    with db.conn() as c:
        for row in rows:
            sync_key = "|".join([source_label, row["ae_name"], row["field"], row["data_type"]])
            seen_keys.append(sync_key)
            c.execute("""
                INSERT INTO clari_ae_snapshots (
                    sync_key, source_label, ae_name, ae_email, role, parent_role,
                    field, data_type, data_value, data_value_numeric, data_value_kind,
                    start_day, end_day, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(sync_key) DO UPDATE SET
                    ae_email = excluded.ae_email, role = excluded.role,
                    parent_role = excluded.parent_role, data_value = excluded.data_value,
                    data_value_numeric = excluded.data_value_numeric,
                    data_value_kind = excluded.data_value_kind, start_day = excluded.start_day,
                    end_day = excluded.end_day, last_synced_at = datetime('now')
            """, (
                sync_key, source_label, row["ae_name"], row["ae_email"], row["role"],
                row["parent_role"], row["field"], row["data_type"], row["data_value"],
                row["data_value_numeric"], row["data_value_kind"], row["start_day"], row["end_day"],
            ))

        # Scoped to source_label: both files share this table, and a sync run
        # on a day outside any week's date window legitimately yields zero
        # rows, so skip the delete entirely rather than zeroing that label's data.
        if seen_keys:
            placeholders = ",".join("?" * len(seen_keys))
            c.execute(
                f"DELETE FROM clari_ae_snapshots WHERE source_label = ? "
                f"AND sync_key NOT IN ({placeholders})",
                (source_label, *seen_keys),
            )

    db.set_setting(f"clari_{source_label}_last_synced_at", datetime.now().isoformat())
    return {"synced": len(rows), "source_label": source_label}


def sync_from_file(db, source_label: str, path: str = None) -> dict:
    path = path or _find_export_file(source_label)
    with open(path, encoding="utf-8-sig") as f:
        rows = parse_rows(f)
    return load_rows(db, source_label, rows)


if __name__ == "__main__":
    import sys

    from db import Database

    if len(sys.argv) < 2 or sys.argv[1] not in ("this_quarter", "next_quarter"):
        print("Usage: clari_sync.py <this_quarter|next_quarter> [path]")
        sys.exit(1)

    label = sys.argv[1]
    override_path = sys.argv[2] if len(sys.argv) > 2 else None

    database_path = os.environ.get("DATABASE_PATH", "se_manager_hub.db")
    db = Database(database_path)
    db.init()

    print(sync_from_file(db, label, override_path))
