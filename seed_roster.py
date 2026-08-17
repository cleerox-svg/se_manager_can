"""One-off seed: pre-populate se_reps with known Slack IDs and mark departed
reps inactive. Safe to re-run — uses INSERT OR IGNORE / UPDATE.

Run once after first `db.init()` (e.g. right after the first `py app.py`
start, or standalone via `py seed_roster.py`).
"""

import os

from dotenv import load_dotenv

from db import Database

load_dotenv()

_KNOWN_SLACK_IDS = {
    "Nic Da Silva": "U09TPQER3AN",
    "Sean Keleher": "U0207R040NQ",
    "Rishika Kondaveeti": "U03DQR1JYBD",
    "Valentin Bourneuf": "U04NB0JRYTE",
}

_INACTIVE = {"Jordan Taylor"}


def seed(db: Database):
    with db.conn() as c:
        for name in set(_KNOWN_SLACK_IDS) | _INACTIVE:
            c.execute("INSERT OR IGNORE INTO se_reps (name) VALUES (?)", (name,))

        for name, slack_id in _KNOWN_SLACK_IDS.items():
            c.execute("UPDATE se_reps SET slack_user_id = ? WHERE name = ?", (slack_id, name))

        for name in _INACTIVE:
            c.execute("UPDATE se_reps SET active = 0 WHERE name = ?", (name,))


if __name__ == "__main__":
    database_path = os.environ.get("DATABASE_PATH", "se_manager_hub.db")
    db = Database(database_path)
    db.init()
    seed(db)
    print("Roster seeded.")
