"""One-off seed: set FY26 H2 ARR targets for active direct reports. Safe to
re-run — plain UPDATE by name.

Run standalone via `py seed_arr_targets.py`.
"""

import os

from dotenv import load_dotenv

from db import Database

load_dotenv()

_ARR_TARGETS = {
    "Sean Keleher": 2_500_000,
    "Rishika Kondaveeti": 2_500_000,
    "Valentin Bourneuf": 1_500_000,
    "Nic Da Silva": 1_500_000,
}


def seed(db: Database):
    with db.conn() as c:
        for name, target in _ARR_TARGETS.items():
            c.execute("UPDATE se_reps SET arr_target = ? WHERE name = ?", (target, name))


if __name__ == "__main__":
    database_path = os.environ.get("DATABASE_PATH", "se_manager_hub.db")
    db = Database(database_path)
    db.init()
    seed(db)
    print("ARR targets seeded.")
