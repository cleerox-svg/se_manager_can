"""One-off refactor of the 2026-H2 mid-year review drafts' "High-impact wins"
section, grounding it in the closed-won/technical-win data pulled from the
Team Tracking Sheet's "Sheet3" tab (see closed_deals_sync.py). Inserts a
lead bullet with concrete deal names/amounts/win counts ahead of the
existing qualitative bullets; leaves the other two sections untouched.
Safe to re-run.
"""

import os
from db import Database

PERIOD = "2026-H2"

# Ordered by amount desc, already loaded via closed_deals_sync.
LEAD_BULLETS = {
    "Sean Keleher": (
        "- Closed 17 deals this period totaling $1,095,169.27, with 14 confirmed technical "
        "wins — the largest closed book on the team. Headline deals: Gildan Full Suite + "
        "ISPM for Hanes Acquisition ($263,269.25, technical win), #PF Lumine Group New "
        "Business WIC Project ($183,689.46, technical win), Enbridge Inc. Upsell - USUI "
        "Project Part 1 ($166,748.32, technical win), His Majesty The King in Right of "
        "Ontario CIS renewal ($127,896.16, technical win), and lululemon global expansion "
        "uplift ($103,054.88, technical win)."
    ),
    "Rishika Kondaveeti": (
        "- Closed 25 deals this period totaling $804,334.84, with 11 confirmed technical "
        "wins — the most deals closed on the team, on top of carrying Bell as the single "
        "largest active pursuit. Headline deals: 17667884 Canada Inc. - SSENSE Takeover "
        "($134,310.05, technical win), Wealthsimple Upsell ($104,128.33, technical win), "
        "Scene+ WIC Upsell ($93,088.00, technical win), and Open Text Inc. WIC renewal "
        "($76,273.25, technical win)."
    ),
    "Nic Da Silva": (
        "- Closed 10 deals this period totaling $301,196.65, with 7 confirmed technical "
        "wins, spread across a genuinely diverse book. Headline deals: Beacon Software New "
        "Business ($118,799.99, technical win), Constellation Software WIC - Onboarding "
        "Apps ($67,472.99), and Volaris Group Q1 True Up ($56,278.55, technical win)."
    ),
    "Valentin Bourneuf": (
        "- Closed 10 deals this period totaling $130,727.35, with 8 confirmed technical "
        "wins — the highest technical-win rate on the team (80% of closed deals). Headline "
        "deals: Wrapbook CIC+WIC renewal ($67,975.49), Stay22 New Business - WIC "
        "($21,999.98, technical win), and eStruxture Data Centers WIC renewal ($12,353.40, "
        "technical win)."
    ),
}


def main():
    # Honour DATABASE_PATH like every other entry point: with it set, the
    # hardcoded name silently created and seeded a SECOND, empty database
    # while the app kept reading the real one.
    db = Database(os.environ.get("DATABASE_PATH", "se_manager_hub.db"))
    db.init()
    with db.conn() as c:
        reps = {row["name"]: row["id"] for row in c.execute("SELECT id, name FROM se_reps")}
        for name, bullet in LEAD_BULLETS.items():
            rep_id = reps.get(name)
            if not rep_id:
                print(f"Skipping {name} — not found in se_reps")
                continue

            row = c.execute(
                "SELECT content FROM reviews WHERE se_rep_id = ? AND period = ?",
                (rep_id, PERIOD),
            ).fetchone()
            if not row:
                print(f"Skipping {name} — no {PERIOD} draft found")
                continue

            content = row["content"]
            marker = "High-impact wins\n"
            idx = content.find(marker)
            if idx == -1:
                print(f"Skipping {name} — 'High-impact wins' heading not found")
                continue
            insert_at = idx + len(marker)

            # Idempotent: replace a previously-inserted lead bullet rather than duplicating it.
            existing_end = content.find("\n- ", insert_at)
            first_bullet_start = content.find("- Closed ", insert_at)
            if first_bullet_start == insert_at:
                next_bullet = content.find("\n- ", insert_at)
                content = content[:insert_at] + bullet + content[next_bullet:]
            else:
                content = content[:insert_at] + bullet + "\n" + content[insert_at:]

            c.execute(
                "UPDATE reviews SET content = ?, updated_at = datetime('now') "
                "WHERE se_rep_id = ? AND period = ?",
                (content, rep_id, PERIOD),
            )
            print(f"Updated {PERIOD} High-impact wins for {name} (rep_id={rep_id})")


if __name__ == "__main__":
    main()
