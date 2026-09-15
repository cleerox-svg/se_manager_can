"""`db.init()` runs on every process start, so it has to be safe to repeat and
safe against an older DB file. `prune_snapshots` deletes rows, so its guards
matter more than its happy path.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import TF_HEADER, _close, add_rep, grid
from db import Database

import tech_forecast_sync


def columns(database, table):
    with database.conn() as c:
        return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def tables(database):
    with database.conn() as c:
        return {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ── idempotency ──────────────────────────────────────────────────────────
def test_init_is_idempotent_and_keeps_existing_data(tmp_path):
    database = Database(str(tmp_path / "hub.db"))
    database.init()
    rep_id = add_rep(database, "Amara Osei")

    database.init()
    database.init()

    with database.conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM se_reps").fetchone()["n"] == 1
        assert c.execute("SELECT name FROM se_reps WHERE id = ?", (rep_id,)).fetchone()["name"] == "Amara Osei"
    assert database.get_setting("schema_version") == "1"
    _close(database)


def test_init_creates_every_table_the_app_queries(db):
    expected = {
        "settings", "se_reps", "deals", "slack_notes", "closed_deals",
        "tech_forecast_deals", "tech_forecast_snapshots", "reviews", "top_items_entries",
    }
    assert expected <= tables(db)


def test_init_creates_the_attribution_and_lookup_indexes(db):
    with db.conn() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_deals_opp_name", "idx_se_reps_name_lower", "idx_closed_deals_tech_win"} <= names


def test_a_second_process_opening_the_same_file_does_not_re_run_the_destructive_cleanup(tmp_path):
    path = str(tmp_path / "hub.db")
    first = Database(path)
    first.init()
    with first.conn() as c:
        c.execute("CREATE TABLE clari_ae_snapshots (id INTEGER PRIMARY KEY)")
    _close(first)

    second = Database(path)
    second.init()
    # schema_version is already at 1, so the one-time DROP must not fire again.
    assert "clari_ae_snapshots" in tables(second)
    _close(second)


# ── legacy DB shape ──────────────────────────────────────────────────────
# The real oldest DB shape in the wild: db.py's schema as of commit 0f64aad
# ("Add Technical Forecast page"), i.e. before every column `_migrate` probes
# for was added. Copied verbatim from that revision rather than invented, so
# this fixture tests the upgrade path an actual user's file would take.
_LEGACY_SCHEMA = """
CREATE TABLE settings (
    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE se_reps (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    slack_user_id TEXT, email TEXT, title TEXT, active INTEGER DEFAULT 1,
    notes TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sheet_key TEXT UNIQUE, lead_se TEXT,
    se_rep_id INTEGER REFERENCES se_reps(id) ON DELETE SET NULL, stage TEXT,
    opportunity_name TEXT, geo_seg TEXT, close_date TEXT, amount REAL,
    se_manager_notes TEXT, presales_notes TEXT, billing_state TEXT,
    poc INTEGER DEFAULT 0, se_needed INTEGER DEFAULT 0, record_type TEXT,
    type TEXT, quarter TEXT, last_synced_at TEXT DEFAULT (datetime('now')));
CREATE TABLE slack_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    se_rep_id INTEGER REFERENCES se_reps(id) ON DELETE CASCADE,
    deal_id INTEGER REFERENCES deals(id) ON DELETE SET NULL, message_ts TEXT,
    channel_id TEXT, channel_name TEXT, text TEXT, permalink TEXT,
    posted_at TEXT, fetched_at TEXT DEFAULT (datetime('now')),
    UNIQUE(se_rep_id, message_ts, channel_id));
CREATE TABLE closed_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sheet_key TEXT UNIQUE, rep_name TEXT,
    se_rep_id INTEGER REFERENCES se_reps(id) ON DELETE SET NULL,
    opportunity_name TEXT, amount REAL, close_date TEXT,
    tech_win INTEGER DEFAULT 0, last_synced_at TEXT DEFAULT (datetime('now')));
CREATE TABLE tech_forecast_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sheet_key TEXT UNIQUE,
    opportunity_name TEXT, amount REAL, presales_stage TEXT,
    forecast_status TEXT, sales_stage TEXT, deal_type TEXT, account_region TEXT,
    geo_seg TEXT, sales_segment TEXT, sales_geo TEXT, close_date TEXT,
    technical_win_date TEXT, opportunity_owner TEXT,
    opportunity_owner_manager TEXT, se_manager_notes TEXT, pre_sales_notes TEXT,
    notes_prev_sync TEXT, notes_stale INTEGER DEFAULT 0,
    last_synced_at TEXT DEFAULT (datetime('now')));
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    se_rep_id INTEGER REFERENCES se_reps(id) ON DELETE CASCADE,
    period TEXT NOT NULL, content TEXT, status TEXT DEFAULT 'draft',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')), UNIQUE(se_rep_id, period));
CREATE TABLE clari_ae_snapshots (id INTEGER PRIMARY KEY, payload TEXT);
INSERT INTO se_reps (name) VALUES ('Legacy Rep');
INSERT INTO deals (sheet_key, lead_se, opportunity_name) VALUES ('legacy-1', 'Legacy Rep', 'Legacy Deal');
"""


@pytest.fixture
def legacy_db(tmp_path):
    path = str(tmp_path / "legacy.db")
    con = sqlite3.connect(path)
    con.executescript(_LEGACY_SCHEMA)
    con.commit()
    con.close()
    database = Database(path)
    yield database
    _close(database)


@pytest.mark.parametrize("table,expected", [
    ("se_reps", {"arr_target", "product", "segment", "coverage_role", "region"}),
    ("deals", {"backup_se_rep_id", "backup_note", "backup_assigned_at", "opportunity_id"}),
    ("closed_deals", {"opportunity_id", "sales_stage", "row_fingerprint"}),
    ("tech_forecast_deals", {"assigned_se_rep_id", "lead_se_name", "pre_sales_next_steps",
                             "opportunity_id", "row_fingerprint", "confidence",
                             "billing_state_province", "backup_se_rep_id", "backup_note",
                             "backup_assigned_at", "product", "segment"}),
])
def test_init_adds_the_newer_columns_to_a_legacy_database(legacy_db, table, expected):
    legacy_db.init()
    assert expected <= columns(legacy_db, table)


def test_migrating_a_legacy_database_preserves_its_rows(legacy_db):
    legacy_db.init()
    with legacy_db.conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM deals").fetchone()["n"] == 1
        assert c.execute("SELECT name FROM se_reps").fetchone()["name"] == "Legacy Rep"


def test_the_abandoned_clari_table_is_dropped_once_on_upgrade(legacy_db):
    legacy_db.init()
    assert "clari_ae_snapshots" not in tables(legacy_db)
    assert legacy_db.get_setting("schema_version") == "1"


def test_a_migrated_legacy_database_can_run_a_real_sync(legacy_db):
    legacy_db.init()
    result = tech_forecast_sync.sync_tech_forecast_from_values(legacy_db, grid(TF_HEADER, {
        "Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
        "Opportunity Name": "Post Migration Deal", "Close Date": "5/4/2026",
        "Amount (converted)": "1,000", "Presales Stage": "4 - Validate Solution",
    }))
    assert result["synced"] == 1


# ── snapshot pruning ─────────────────────────────────────────────────────
def insert_snapshots(database, days_ago_list):
    with database.conn() as c:
        for days in days_ago_list:
            c.execute(
                "INSERT INTO tech_forecast_snapshots (snapshot_date, bucket_totals_json, deal_states_json) "
                "VALUES (?, '{}', '{}')",
                ((date.today() - timedelta(days=days)).isoformat(),),
            )


def snapshot_count(database):
    with database.conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM tech_forecast_snapshots").fetchone()["n"]


def test_prune_snapshots_keeps_the_minimum_recent_window_however_old_it_is(db):
    insert_snapshots(db, [500 + i for i in range(12)])
    deleted = db.prune_snapshots(keep_days=400, keep_min=8)
    assert deleted == 4
    assert snapshot_count(db) == 8


def test_prune_snapshots_never_drops_anything_inside_the_retention_window(db):
    insert_snapshots(db, [1, 30, 200, 399])
    assert db.prune_snapshots(keep_days=400, keep_min=2) == 0
    assert snapshot_count(db) == 4


def test_prune_snapshots_counts_recent_rows_toward_the_keep_minimum(db):
    insert_snapshots(db, [1, 2, 3, 4, 5])             # inside the window
    insert_snapshots(db, [500 + i for i in range(10)])  # outside it
    deleted = db.prune_snapshots(keep_days=400, keep_min=8)
    assert deleted == 7
    assert snapshot_count(db) == 8


def test_prune_snapshots_on_an_empty_table_is_a_no_op(db):
    assert db.prune_snapshots() == 0


def test_prune_snapshots_keeps_the_newest_rows_not_an_arbitrary_eight(db):
    insert_snapshots(db, [500 + i for i in range(12)])
    db.prune_snapshots(keep_days=400, keep_min=8)
    with db.conn() as c:
        kept = [r["snapshot_date"] for r in c.execute(
            "SELECT snapshot_date FROM tech_forecast_snapshots ORDER BY snapshot_date DESC"
        )]
    expected = [(date.today() - timedelta(days=500 + i)).isoformat() for i in range(8)]
    assert kept == expected


# ── settings + timestamps ────────────────────────────────────────────────
def test_settings_round_trip_with_a_default(db):
    assert db.get_setting("nope") is None
    assert db.get_setting("nope", "fallback") == "fallback"
    db.set_setting("deals_last_synced_at", "2026-09-15T00:00:00+00:00")
    assert db.get_setting("deals_last_synced_at") == "2026-09-15T00:00:00+00:00"
    db.set_setting("deals_last_synced_at", "later")
    assert db.get_setting("deals_last_synced_at") == "later"


def test_utc_now_iso_is_timezone_aware_utc():
    from db import utc_now_iso
    parsed = datetime.fromisoformat(utc_now_iso())
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_a_failed_transaction_rolls_back_rather_than_half_committing(db):
    add_rep(db, "Amara Osei")
    with pytest.raises(sqlite3.IntegrityError):
        with db.conn() as c:
            c.execute("INSERT INTO se_reps (name) VALUES ('Bo Nakamura')")
            c.execute("INSERT INTO se_reps (name) VALUES ('Amara Osei')")  # UNIQUE violation
    with db.conn() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM se_reps")}
    assert names == {"Amara Osei"}


# ── db.conn() re-entrancy ────────────────────────────────────────────────────
# The connection is shared per thread, so before the depth guard a nested
# `with db.conn()` committed the OUTER transaction as soon as the inner block
# exited, and an inner failure rolled the outer's writes back with it. That made
# it unsafe to call any helper opening its own scope from inside a transaction.

def test_nested_conn_commits_once_at_the_outermost_scope(db):
    with db.conn() as c:
        c.execute("INSERT INTO se_reps (name, active) VALUES ('Outer', 1)")
        with db.conn() as inner:
            inner.execute("INSERT INTO se_reps (name, active) VALUES ('Inner', 1)")
    with db.conn() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM se_reps")}
    assert {"Outer", "Inner"} <= names


def test_inner_failure_rolls_back_only_the_inner_scope(db):
    with db.conn() as c:
        c.execute("INSERT INTO se_reps (name, active) VALUES ('Keep', 1)")
        with pytest.raises(ValueError):
            with db.conn() as inner:
                inner.execute("INSERT INTO se_reps (name, active) VALUES ('Drop', 1)")
                raise ValueError("inner blew up")
    with db.conn() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM se_reps")}
    assert "Keep" in names, "the outer scope's work was lost with the inner failure"
    assert "Drop" not in names, "the failed inner scope's write survived"


def test_outer_failure_rolls_back_nested_work_too(db):
    with pytest.raises(RuntimeError):
        with db.conn() as c:
            c.execute("INSERT INTO se_reps (name, active) VALUES ('X', 1)")
            with db.conn() as inner:
                inner.execute("INSERT INTO se_reps (name, active) VALUES ('Y', 1)")
            raise RuntimeError("outer blew up")
    with db.conn() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM se_reps")}
    assert not ({"X", "Y"} & names)


def test_a_helper_opening_its_own_scope_is_safe_inside_a_transaction(db):
    """The concrete case the guard exists for: a sync writing rows and calling
    set_setting, which opens its own scope, in the same logical transaction."""
    with db.conn() as c:
        c.execute("INSERT INTO se_reps (name, active) VALUES ('Rep', 1)")
        db.set_setting("last_synced_at", "2026-09-15T00:00:00+00:00")
    with db.conn() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM se_reps")}
    assert "Rep" in names
    assert db.get_setting("last_synced_at") == "2026-09-15T00:00:00+00:00"
