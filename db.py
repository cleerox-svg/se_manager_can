import sqlite3
import threading
from contextlib import contextmanager

_PRAGMAS = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA cache_size=-32000;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
"""


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
        con = self._get_con()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise

    def _migrate(self, c: sqlite3.Connection):
        cols = {row["name"] for row in c.execute("PRAGMA table_info(se_reps)")}
        if "arr_target" not in cols:
            c.execute("ALTER TABLE se_reps ADD COLUMN arr_target REAL DEFAULT 0")

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
        if "opportunity_id" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN opportunity_id TEXT")
        if "row_fingerprint" not in cols:
            c.execute("ALTER TABLE tech_forecast_deals ADD COLUMN row_fingerprint TEXT")

        cols = {row["name"] for row in c.execute("PRAGMA table_info(closed_deals)")}
        if "opportunity_id" not in cols:
            c.execute("ALTER TABLE closed_deals ADD COLUMN opportunity_id TEXT")
        if "sales_stage" not in cols:
            c.execute("ALTER TABLE closed_deals ADD COLUMN sales_stage TEXT")

        c.execute("DROP TABLE IF EXISTS clari_ae_snapshots")

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
                    assigned_se_rep_id       INTEGER REFERENCES se_reps(id),
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

                CREATE INDEX IF NOT EXISTS idx_deals_se_rep ON deals(se_rep_id);
                CREATE INDEX IF NOT EXISTS idx_deals_quarter ON deals(quarter);
                CREATE INDEX IF NOT EXISTS idx_slack_notes_se_rep ON slack_notes(se_rep_id);
                CREATE INDEX IF NOT EXISTS idx_closed_deals_se_rep ON closed_deals(se_rep_id);
            """)
            self._migrate(c)

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
