"""One-off seed: apply the new Auth0/Okta coverage-rules tagging to se_reps.
Safe to re-run — updates are plain UPDATE by id/name, inserts are guarded by
a name-existence check.

Run standalone via `py seed_coverage_rules.py`.
"""

import os

from dotenv import load_dotenv

from db import Database

load_dotenv()

# Luis Santos (id=7): reactivate as Auth0 co-primary TMR.
_REACTIVATE_ID = 7
_REACTIVATE_NAME = "Luis Santos"
_REACTIVATE_FIELDS = {
    "active": 1,
    "product": "Auth0",
    "segment": "Enterprise/Strategic",
    "coverage_role": "TMR",
    "region": "Canada",
}

# Andrew Whitman: new row, co-primary alongside Luis, same tags, no
# Secondary distinction.
_NEW_COPRIMARY = {
    "name": "Andrew Whitman",
    "product": "Auth0",
    "segment": "Enterprise/Strategic",
    "coverage_role": "TMR",
    "region": "Canada",
    "active": 1,
}

# Ryan Morren, Pratul Agarwal: new rows at full parity with the existing
# active team (Sean/Rishika/Nic/Valentin) — no coverage_role/product tagging
# beyond the Okta backfill below.
_NEW_FULL_PARITY = ["Ryan Morren", "Pratul Agarwal"]

# Optional backfill: tag existing + newly-added full-parity reps with
# product='Okta' for consistency with the new schema.
_OKTA_BACKFILL_NAMES = [
    "Sean Keleher",
    "Rishika Kondaveeti",
    "Nic Da Silva",
    "Valentin Bourneuf",
    "Ryan Morren",
    "Pratul Agarwal",
]


def seed(db: Database):
    summary = []

    with db.conn() as c:
        row = c.execute("SELECT id, name FROM se_reps WHERE id = ?", (_REACTIVATE_ID,)).fetchone()
        if row is None or row["name"] != _REACTIVATE_NAME:
            raise RuntimeError(
                f"Expected id={_REACTIVATE_ID} to be '{_REACTIVATE_NAME}', "
                f"found {dict(row) if row else None}"
            )
        c.execute(
            "UPDATE se_reps SET active = ?, product = ?, segment = ?, "
            "coverage_role = ?, region = ? WHERE id = ?",
            (
                _REACTIVATE_FIELDS["active"],
                _REACTIVATE_FIELDS["product"],
                _REACTIVATE_FIELDS["segment"],
                _REACTIVATE_FIELDS["coverage_role"],
                _REACTIVATE_FIELDS["region"],
                _REACTIVATE_ID,
            ),
        )
        summary.append(f"Reactivated {_REACTIVATE_NAME} (id={_REACTIVATE_ID}) as Auth0/TMR co-primary.")

        existing = c.execute(
            "SELECT id FROM se_reps WHERE name = ?", (_NEW_COPRIMARY["name"],)
        ).fetchone()
        if existing is None:
            c.execute(
                "INSERT INTO se_reps (name, active, product, segment, coverage_role, region) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _NEW_COPRIMARY["name"],
                    _NEW_COPRIMARY["active"],
                    _NEW_COPRIMARY["product"],
                    _NEW_COPRIMARY["segment"],
                    _NEW_COPRIMARY["coverage_role"],
                    _NEW_COPRIMARY["region"],
                ),
            )
            summary.append(f"Inserted {_NEW_COPRIMARY['name']} as Auth0/TMR co-primary.")
        else:
            summary.append(f"Skipped insert: {_NEW_COPRIMARY['name']} already exists (id={existing['id']}).")

        for name in _NEW_FULL_PARITY:
            existing = c.execute("SELECT id FROM se_reps WHERE name = ?", (name,)).fetchone()
            if existing is None:
                c.execute("INSERT INTO se_reps (name, active) VALUES (?, 1)", (name,))
                summary.append(f"Inserted {name} at full parity with the existing active team.")
            else:
                summary.append(f"Skipped insert: {name} already exists (id={existing['id']}).")

        for name in _OKTA_BACKFILL_NAMES:
            row = c.execute("SELECT id, product FROM se_reps WHERE name = ?", (name,)).fetchone()
            if row is None:
                summary.append(f"Skipped Okta backfill: {name} not found.")
                continue
            c.execute("UPDATE se_reps SET product = ? WHERE id = ?", ("Okta", row["id"]))
            summary.append(f"Backfilled product='Okta' on {name} (id={row['id']}).")

    return summary


if __name__ == "__main__":
    database_path = os.environ.get("DATABASE_PATH", "se_manager_hub.db")
    db = Database(database_path)
    db.init()
    for line in seed(db):
        print(line)
    print("Coverage rules seeded.")
