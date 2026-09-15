import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

_PRAGMAS = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA cache_size=-32000;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
"""

# Bumped when a one-time cleanup is added to `_one_time_cleanups`. Everything
# else in `_migrate` is idempotent CREATE/ALTER probing and stays unversioned.
_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    """Timestamp for columns whose schema default is `datetime('now')` (UTC).

    Callers writing those columns explicitly must not use
    `datetime.now().isoformat()` — that's local time, so a written value and a
    defaulted `updated_at` in the same row end up disagreeing by the UTC offset
    (e.g. `settings.value` vs `settings.updated_at`).
    """
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()

    def _get_con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
            con.row_factory = sqlite3.Row
            con.executescript(_PRAGMAS)
            self._local.con = con
        return con

    @contextmanager
    def conn(self):
        """Transaction scope on this thread's connection.

        Re-entrant on purpose. The connection is shared per thread, so a nested
        `with db.conn()` used to commit the OUTER transaction the moment the
        inner block exited, and an inner failure rolled the outer's work back
        with it — a caller could not safely call a helper that opens its own
        scope (`get_setting`, `set_setting`, a report builder) from inside one.
        Only the outermost scope commits; inner scopes get a SAVEPOINT, so an
        inner failure undoes only its own writes and the outer block decides
        what happens to the rest.
        """
        con = self._get_con()
        depth = getattr(self._local, "depth", 0)

        if depth:
            name = f"_nested_{depth}"
            con.execute(f"SAVEPOINT {name}")
            self._local.depth = depth + 1
            try:
                yield con
            except Exception:
                con.execute(f"ROLLBACK TO {name}")
                con.execute(f"RELEASE {name}")
                raise
            else:
                con.execute(f"RELEASE {name}")
            finally:
                self._local.depth = depth
            return

        self._local.depth = 1
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            self._local.depth = 0

    def _migrate(self, c: sqlite3.Connection):
        cols = {row["name"] for row in c.execute("PRAGMA table_info(se_reps)")}
        if "arr_target" not in cols:
            c.execute("ALTER TABLE se_reps ADD COLUMN arr_target REAL DEFAULT 0")
        if "product" not in cols:
            c.execute("ALTER TABLE se_reps ADD COLUMN product TEXT")
        if "segment" not in cols:
            c.execute("ALTER TABLE se_reps ADD COLUMN segment TEXT")
        if "coverage_role" not in cols:
            c.execute("ALTER TABLE se_reps ADD COLUMN coverage_role TEXT")
        if "region" not in cols:
            c.execute("ALTER TABLE se_reps ADD COLUMN region TEXT")

        cols = {row["name"] for row in c.execute("PRAGMA table_info(deals)")}
        if "backup_se_rep_id" not in cols:
            c.execute(
                "ALTER TABLE deals "
                "ADD COLUMN backup_se_rep_id INTEGER REFERENCES se_reps(id) ON DELETE SET NULL"
            )
        if "backup_note" not in cols:
            c.execute("ALTER TABLE deals ADD COLUMN backup_note TEXT")
        if "backup_assigned_at" not in cols:
            c.execute("ALTER TABLE deals ADD COLUMN backup_assigned_at TEXT")
        # `closed_deals` and `tech_forecast_deals` already carry the SFDC record
        # id; `deals` didn't, so the sync layer could only key rows by the
        # composite sheet_key, which churns whenever a sheet cell is edited.
        if "opportunity_id" not in cols:
            c.execute("ALTER TABLE deals ADD COLUMN opportunity_id TEXT")

        cols = {row["name"] for row in c.execute("PRAGMA table_info(tech_forecast_deals)")}
        if "assigned_se_rep_id" not in cols:
            c.execute(
                "ALTER TABLE tech_forecast_deals "
                "ADD COLUMN assigned_se_rep_id INTEGER REFERENCES se_reps(id)"
            )
        if "lead_se_name" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN lead_se_name TEXT")
        if "pre_sales_next_steps" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN pre_sales_next_steps TEXT")
        # Both staleness columns shipped in CREATE TABLE only, with no ALTER
        # probe, so a database predating them never gained them and every sync
        # died on `no such column: notes_stale`. Fresh DBs were fine, which is
        # why it stayed hidden.
        if "notes_prev_sync" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN notes_prev_sync TEXT")
        if "notes_stale" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN notes_stale INTEGER DEFAULT 0")
        # When the Pre-Sales Next Steps text last actually changed. `notes_stale`
        # only says "unchanged since the previous sync", which can't answer the
        # question that decides whether a deal gets raised on the Monday call —
        # unchanged for a week or unchanged for a month. Stays NULL on rows that
        # predate this column: we genuinely don't know when they last moved, and
        # stamping them now would claim they just did.
        if "notes_last_changed_at" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN notes_last_changed_at TEXT")
        if "opportunity_id" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN opportunity_id TEXT")
        if "row_fingerprint" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN row_fingerprint TEXT")
        if "confidence" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN confidence TEXT")
        if "billing_state_province" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN billing_state_province TEXT")
        if "backup_se_rep_id" not in cols:
            c.execute(
                "ALTER TABLE tech_forecast_deals "
                "ADD COLUMN backup_se_rep_id INTEGER REFERENCES se_reps(id) ON DELETE SET NULL"
            )
        if "backup_note" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN backup_note TEXT")
        if "backup_assigned_at" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN backup_assigned_at TEXT")
        if "product" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN product TEXT")
        if "segment" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN segment TEXT")

        cols = {row["name"] for row in c.execute("PRAGMA table_info(closed_deals)")}
        if "opportunity_id" not in cols:
            c.execute("ALTER TABLE closed_deals ADD COLUMN opportunity_id TEXT")
        if "sales_stage" not in cols:
            c.execute("ALTER TABLE closed_deals ADD COLUMN sales_stage TEXT")
        if "row_fingerprint" not in cols:
            c.execute("ALTER TABLE closed_deals ADD COLUMN row_fingerprint TEXT")

        self._one_time_cleanups(c)

    def _one_time_cleanups(self, c: sqlite3.Connection):
        """Destructive migrations that must not re-run on every process start.

        The CREATE/ALTER probing above is cheap and safe to repeat; a DROP is
        neither, so it's gated on a stored version instead.
        """
        row = c.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
        version = int(row["value"]) if row and str(row["value"]).isdigit() else 0
        if version >= _SCHEMA_VERSION:
            return

        if version < 1:
            # Abandoned Clari import experiment — the table was never read back.
            c.execute("DROP TABLE IF EXISTS clari_ae_snapshots")

        c.execute(
            "INSERT INTO settings (key, value, updated_at) "
            "VALUES ('schema_version', ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (str(_SCHEMA_VERSION),),
        )

    def init(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS se_reps (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    name           TEXT NOT NULL UNIQUE,
                    slack_user_id  TEXT,
                    email          TEXT,
                    title          TEXT,
                    active         INTEGER DEFAULT 1,
                    notes          TEXT,
                    created_at     TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS deals (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    sheet_key        TEXT UNIQUE,
                    lead_se          TEXT,
                    se_rep_id        INTEGER REFERENCES se_reps(id) ON DELETE SET NULL,
                    stage            TEXT,
                    opportunity_name TEXT,
                    geo_seg          TEXT,
                    close_date       TEXT,
                    amount           REAL,
                    se_manager_notes TEXT,
                    presales_notes   TEXT,
                    billing_state    TEXT,
                    poc              INTEGER DEFAULT 0,
                    se_needed        INTEGER DEFAULT 0,
                    record_type      TEXT,
                    type             TEXT,
                    quarter          TEXT,
                    last_synced_at   TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS slack_notes (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    se_rep_id    INTEGER REFERENCES se_reps(id) ON DELETE CASCADE,
                    -- deal_id is unpopulated: nothing writes or reads it. Kept
                    -- rather than dropped so no existing DB loses a column.
                    deal_id      INTEGER REFERENCES deals(id) ON DELETE SET NULL,
                    message_ts   TEXT,
                    channel_id   TEXT,
                    channel_name TEXT,
                    text         TEXT,
                    permalink    TEXT,
                    posted_at    TEXT,
                    fetched_at   TEXT DEFAULT (datetime('now')),
                    UNIQUE(se_rep_id, message_ts, channel_id)
                );

                CREATE TABLE IF NOT EXISTS closed_deals (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    sheet_key        TEXT UNIQUE,
                    rep_name         TEXT,
                    se_rep_id        INTEGER REFERENCES se_reps(id) ON DELETE SET NULL,
                    opportunity_name TEXT,
                    opportunity_id   TEXT,
                    amount           REAL,
                    close_date       TEXT,
                    sales_stage      TEXT,
                    tech_win         INTEGER DEFAULT 0,
                    row_fingerprint  TEXT,
                    last_synced_at   TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS tech_forecast_deals (
                    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                    sheet_key                TEXT UNIQUE,
                    lead_se_name             TEXT,
                    opportunity_name         TEXT,
                    opportunity_id           TEXT,
                    amount                   REAL,
                    presales_stage           TEXT,
                    forecast_status          TEXT,
                    sales_stage              TEXT,
                    deal_type                TEXT,
                    account_region           TEXT,
                    geo_seg                  TEXT,
                    sales_segment            TEXT,
                    sales_geo                TEXT,
                    close_date               TEXT,
                    technical_win_date       TEXT,
                    opportunity_owner        TEXT,
                    opportunity_owner_manager TEXT,
                    se_manager_notes         TEXT,
                    pre_sales_notes          TEXT,
                    pre_sales_next_steps     TEXT,
                    notes_prev_sync          TEXT,
                    notes_stale              INTEGER DEFAULT 0,
                    row_fingerprint          TEXT,
                    -- No ON DELETE action, so this FK is RESTRICT while every
                    -- other rep reference is SET NULL/CASCADE: deleting an
                    -- se_reps row fails while any deal here points at it.
                    -- Fixing it needs a full table rebuild (SQLite can't alter
                    -- an FK in place), which isn't worth it for a column only
                    -- set by hand from the Tech Forecast page. Any future
                    -- delete-rep path must NULL this column first.
                    assigned_se_rep_id       INTEGER REFERENCES se_reps(id),
                    confidence               TEXT,
                    billing_state_province   TEXT,
                    last_synced_at           TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS tech_forecast_snapshots (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date      TEXT UNIQUE,
                    bucket_totals_json TEXT,
                    deal_states_json   TEXT,
                    created_at         TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    se_rep_id  INTEGER REFERENCES se_reps(id) ON DELETE CASCADE,
                    period     TEXT NOT NULL,
                    content    TEXT,
                    status     TEXT DEFAULT 'draft',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(se_rep_id, period)
                );

                CREATE TABLE IF NOT EXISTS top_items_entries (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_date TEXT UNIQUE,
                    content    TEXT,
                    status     TEXT DEFAULT 'draft',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_deals_se_rep ON deals(se_rep_id);
                CREATE INDEX IF NOT EXISTS idx_deals_quarter ON deals(quarter);
                CREATE INDEX IF NOT EXISTS idx_slack_notes_se_rep ON slack_notes(se_rep_id);
                CREATE INDEX IF NOT EXISTS idx_closed_deals_se_rep ON closed_deals(se_rep_id);

                -- Covering index for step 3 of the SE-attribution precedence
                -- (attribution.ATTRIBUTED_SE_ID_SQL): the id/se_rep_id columns
                -- let the ORDER BY d.id LIMIT 1 resolve without touching the
                -- table. Turns a per-row SCAN of deals into a SEARCH.
                CREATE INDEX IF NOT EXISTS idx_deals_opp_name
                    ON deals(opportunity_name, id, se_rep_id);

                -- Step 2 of the same precedence matches on lower(name), which
                -- the UNIQUE index on se_reps.name can't serve; without this
                -- expression index every tech_forecast row re-scans se_reps.
                CREATE INDEX IF NOT EXISTS idx_se_reps_name_lower
                    ON se_reps(lower(name));

                -- Matches /api/reps/<id>/slack's ORDER BY posted_at DESC, so
                -- the 200-row page comes off the index with no temp B-tree.
                CREATE INDEX IF NOT EXISTS idx_slack_notes_rep_posted
                    ON slack_notes(se_rep_id, posted_at DESC);

                -- Partial: technical wins are a small slice of closed_deals,
                -- so the index is a fraction of the table the tech-win queries
                -- would otherwise scan in full.
                CREATE INDEX IF NOT EXISTS idx_closed_deals_tech_win
                    ON closed_deals(tech_win) WHERE tech_win = 1;

                CREATE INDEX IF NOT EXISTS idx_tech_forecast_presales_stage
                    ON tech_forecast_deals(presales_stage);
            """)
            self._migrate(c)

    def prune_snapshots(self, keep_days: int = 400, keep_min: int = 8) -> int:
        """Drop tech_forecast snapshots older than `keep_days`.

        `deal_states_json` is a full per-deal blob written daily (~30MB/yr) but
        `build_weekly_deltas` only ever reads the single most recent prior row,
        so anything past a year of history is dead weight. `keep_min` guards the
        recent window regardless of age, so a DB that goes stale for a while
        still has a baseline to diff against.

        Not called from `init()` — pruning on every process start would make an
        app restart destructive. Invoke it from `tech_forecast_sync` right after
        the daily snapshot is captured, where a write is already expected.
        """
        with self.conn() as c:
            cur = c.execute(
                "DELETE FROM tech_forecast_snapshots "
                "WHERE snapshot_date < date('now', ?) "
                "AND id NOT IN ("
                "    SELECT id FROM tech_forecast_snapshots "
                "    ORDER BY snapshot_date DESC LIMIT ?"
                ")",
                (f"-{int(keep_days)} days", int(keep_min)),
            )
            return cur.rowcount

    def get_setting(self, key: str, default=None):
        with self.conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.conn() as c:
            c.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
                (key, value),
            )
