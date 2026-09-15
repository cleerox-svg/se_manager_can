"""Shared fixtures for the SE Manager Hub suite.

Rules this file exists to enforce:

* every test gets its OWN SQLite file under pytest's ``tmp_path`` — nothing here
  may ever open the project's real ``se_manager_hub.db``;
* all fixture data is synthetic and invented for the tests (CLAUDE.md forbids
  loading real sheet/Slack exports into this repo);
* anything that depends on "today" is injected, never read off the wall clock,
  so a test can't pass only during one fiscal quarter.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tech_forecast_report as report  # noqa: E402  (after sys.path setup)
from db import Database  # noqa: E402

# The fiscal quarter every date-dependent test pretends "today" falls in.
# FY26-Q3 = Aug-Oct 2026 under Okta's Feb-1 fiscal year.
FROZEN_FQ = "FY26-Q3"
IN_CURRENT_FQ = "2026-09-15"   # FY26-Q3
IN_NEXT_FQ = "2026-11-20"      # FY26-Q4
IN_PAST_FQ = "2026-03-10"      # FY26-Q1  (overdue)
IN_LATER_FQ = "2027-05-05"     # FY27-Q2


def _close(database: Database) -> None:
    con = getattr(database._local, "con", None)
    if con is not None:
        con.close()
        database._local.con = None


@pytest.fixture
def db(tmp_path):
    """A migrated, empty database on its own temp file."""
    database = Database(str(tmp_path / "hub.db"))
    database.init()
    yield database
    _close(database)


@pytest.fixture
def frozen_quarter(monkeypatch):
    """Pin `report.current_fiscal_quarter` so bucketing is deterministic.

    Every caller of "today's fiscal quarter" (quarter_bucket_detailed,
    build_top_deals, build_sfdc_updates, build_slack_draft, app.py's
    /api/tech-forecast and /api/closed-deals/summary) goes through this one
    module attribute, so patching it is enough to freeze all of them.
    """
    def _freeze(label=FROZEN_FQ):
        monkeypatch.setattr(report, "current_fiscal_quarter", lambda: label)
        return label

    _freeze()
    return _freeze


# ---------------------------------------------------------------------------
# Synthetic sheet grids
# ---------------------------------------------------------------------------

DEALS_HEADER = [
    "Lead Sales Engineer", "Stage", "Opportunity Name", "Account Owner Geo-Seg",
    "Close Date", "Amount", "SE Manager Notes", "Pre-Sales Notes",
    "Billing State/Province", "POC", "SE Needed", "Opportunity Record Type",
    "Type", "Opportunity ID",
]

CLOSED_HEADER = [
    "Team Member Name", "Team Role",
    "Opportunity : Account Name : Account Owner : User Sales Region",
    "Opportunity Name", "Amount (converted)", "Close Date", "Presales Stage",
    "Opportunity ID", "Stage",
]

TF_HEADER = [
    "Lead Sales Engineer", "Presales Stage", "Deal Forecast Status",
    "Amount (converted)", "Opportunity Name", "Opportunity ID",
    "Opportunity Owner", "Opportunity Owner: Manager", "Stage", "Type",
    "Account Region", "Close Date", "Pre-Sales Notes", "SE Manager Notes",
    "Pre-Sales Next Steps", "Technical Win Date", "Account Owner Geo-Seg",
    "Account Owner Sales Segment", "Account Owner Sales Geography",
    "Pre-Sales confidence for Quarter", "Billing State/Province",
]


def grid(header, *rows):
    """Build a `get_all_values()`-shaped grid from {header: value} dicts."""
    return [list(header)] + [[str(r.get(h, "")) for h in header] for r in rows]


# ---------------------------------------------------------------------------
# Direct-SQL seeding helpers (bypass the syncs so a report/API test can state
# exactly the rows it needs)
# ---------------------------------------------------------------------------

def add_rep(database, name, active=1, **cols):
    with database.conn() as c:
        cur = c.execute(
            "INSERT INTO se_reps (name, active, slack_user_id, email, title, arr_target) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, active, cols.get("slack_user_id"), cols.get("email"),
             cols.get("title"), cols.get("arr_target", 0)),
        )
        return cur.lastrowid


def add_deal(database, **cols):
    cols.setdefault("sheet_key", f"deal-{cols.get('opportunity_name', 'x')}")
    keys = list(cols)
    with database.conn() as c:
        cur = c.execute(
            f"INSERT INTO deals ({', '.join(keys)}) "
            f"VALUES ({', '.join('?' * len(keys))})",
            [cols[k] for k in keys],
        )
        return cur.lastrowid


def add_closed_deal(database, **cols):
    cols.setdefault("sheet_key", f"closed-{cols.get('opportunity_name', 'x')}")
    keys = list(cols)
    with database.conn() as c:
        cur = c.execute(
            f"INSERT INTO closed_deals ({', '.join(keys)}) "
            f"VALUES ({', '.join('?' * len(keys))})",
            [cols[k] for k in keys],
        )
        return cur.lastrowid


def add_tf_deal(database, **cols):
    cols.setdefault("sheet_key", f"tf-{cols.get('opportunity_name', 'x')}")
    keys = list(cols)
    with database.conn() as c:
        cur = c.execute(
            f"INSERT INTO tech_forecast_deals ({', '.join(keys)}) "
            f"VALUES ({', '.join('?' * len(keys))})",
            [cols[k] for k in keys],
        )
        return cur.lastrowid


def add_slack_note(database, **cols):
    keys = list(cols)
    with database.conn() as c:
        c.execute(
            f"INSERT INTO slack_notes ({', '.join(keys)}) "
            f"VALUES ({', '.join('?' * len(keys))})",
            [cols[k] for k in keys],
        )


def seed_reference_data(database):
    """A small, fully synthetic team + pipeline used by the API smoke tests.

    Deliberately includes the shapes that have bitten this codebase before: a
    Closed/Lost row that is still a technical win, a NULL amount, an inactive
    rep with historical deals, and a tech-forecast row attributed by each of
    the three precedence steps.
    """
    ids = {
        "amara": add_rep(database, "Amara Osei", arr_target=2_500_000),
        "bo": add_rep(database, "Bo Nakamura", arr_target=1_500_000),
        "departed": add_rep(database, "Quinn Delacroix", active=0),
    }

    add_deal(database, sheet_key="oid:0061", opportunity_id="0061",
             lead_se="Amara Osei", se_rep_id=ids["amara"], stage="3 - Technical Scoping",
             opportunity_name="Northwind Identity Refresh", close_date="2026-09-30",
             amount=250_000.0, quarter="2026-Q3", poc=1, se_needed=0)
    add_deal(database, sheet_key="oid:0062", opportunity_id="0062",
             lead_se="Bo Nakamura", se_rep_id=ids["bo"], stage="2 - Discovery",
             opportunity_name="Cobblestone Bank SSO", close_date="2026-11-15",
             amount=None, quarter="2026-Q4")
    add_deal(database, sheet_key="oid:0063", opportunity_id="0063",
             lead_se="Quinn Delacroix", se_rep_id=ids["departed"], stage="4 - Validate Solution",
             opportunity_name="Heritage Rail Legacy Deal", close_date="2026-04-01",
             amount=90_000.0, quarter="2026-Q2")

    add_closed_deal(database, sheet_key="oid:0071", opportunity_id="0071",
                    rep_name="Amara Osei", se_rep_id=ids["amara"],
                    opportunity_name="Lakeshore Utilities Platform", amount=400_000.0,
                    close_date=IN_CURRENT_FQ, sales_stage="10 - Closed/Won", tech_win=1)
    add_closed_deal(database, sheet_key="oid:0072", opportunity_id="0072",
                    rep_name="Amara Osei", se_rep_id=ids["amara"],
                    opportunity_name="Fenwick Logistics Expansion", amount=650_000.0,
                    close_date=IN_CURRENT_FQ, sales_stage="7 - Closed/Lost", tech_win=1)
    add_closed_deal(database, sheet_key="oid:0073", opportunity_id="0073",
                    rep_name="Bo Nakamura", se_rep_id=ids["bo"],
                    opportunity_name="Pinecrest Health Records", amount=None,
                    close_date=IN_CURRENT_FQ, sales_stage="10 - Closed/Won", tech_win=0)

    # Step 1: manual override wins over a contradicting sheet name.
    add_tf_deal(database, sheet_key="oid:0081", opportunity_id="0081",
                opportunity_name="Granite Peak Zero Trust", lead_se_name="Somebody Else",
                assigned_se_rep_id=ids["amara"], amount=300_000.0,
                presales_stage="4 - Validate Solution", forecast_status="Strong",
                close_date=IN_CURRENT_FQ, technical_win_date=IN_CURRENT_FQ,
                pre_sales_next_steps="Workshop booked", confidence="Commit")
    # Step 2: case-insensitive sheet Lead SE name match.
    add_tf_deal(database, sheet_key="oid:0082", opportunity_id="0082",
                opportunity_name="Seabright Ferries IAM", lead_se_name="bo nakamura",
                amount=150_000.0, presales_stage="3 - Technical Scoping",
                forecast_status="Forecasted Risk", close_date=IN_NEXT_FQ,
                pre_sales_next_steps="", confidence="Upside")
    # Step 3: opportunity-name join back onto `deals`.
    add_tf_deal(database, sheet_key="oid:0083", opportunity_id="0083",
                opportunity_name="Northwind Identity Refresh", lead_se_name="",
                amount=None, presales_stage="", forecast_status="Pipeline",
                close_date=IN_LATER_FQ, pre_sales_next_steps="Waiting on security review")
    # Technical win still sitting in the open board.
    add_tf_deal(database, sheet_key="oid:0084", opportunity_id="0084",
                opportunity_name="Rivermouth Freight Portal", lead_se_name="Amara Osei",
                amount=210_000.0, presales_stage="6 - Technical Win",
                forecast_status="Strong", close_date=IN_CURRENT_FQ,
                technical_win_date=IN_CURRENT_FQ, sales_stage="5 - Negotiation")

    add_slack_note(database, se_rep_id=ids["amara"], message_ts="1757000000.0001",
                   channel_id="C01", channel_name="se-canada",
                   text="Wrapped the Northwind workshop.", posted_at="2026-09-10T12:00:00")

    with database.conn() as c:
        c.execute(
            "INSERT INTO tech_forecast_snapshots (snapshot_date, bucket_totals_json, deal_states_json) "
            "VALUES ('2026-09-01', ?, ?)",
            ('{"Commit": {"Validate Solution": {"amount": 300000.0, "count": 1}}}',
             '{"oid:0081": {"sheet_key": "oid:0081", "opportunity_name": "Granite Peak Zero Trust",'
             ' "opportunity_id": "0081", "amount": 300000.0,'
             ' "presales_stage": "3 - Technical Scoping", "forecast_status": "Strong",'
             ' "confidence": "Commit"}}'),
        )
        c.execute(
            "INSERT INTO reviews (se_rep_id, period, content, status) VALUES (?, '2026-H2', 'draft text', 'draft')",
            (ids["amara"],),
        )
        c.execute(
            "INSERT INTO top_items_entries (entry_date, content) VALUES ('2026-09-08', 'last week')"
        )
    return ids


@pytest.fixture
def api(tmp_path, monkeypatch, frozen_quarter):
    """Flask test client bound to a throwaway DB, with a seeded dataset.

    `app.py` reads DATABASE_PATH and calls `db.init()` at import time, so the
    module is dropped from sys.modules and re-imported per test — that is what
    guarantees the app never touches the project's real database file.
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("SHEET_ID", "")
    monkeypatch.setenv("SLACK_USER_TOKEN", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    for module in ("app",):
        sys.modules.pop(module, None)

    import app as app_module

    app_module.app.config["TESTING"] = True
    ids = seed_reference_data(app_module.db)
    client = app_module.app.test_client()
    client.rep_ids = ids
    client.db = app_module.db
    yield client
    _close(app_module.db)
    sys.modules.pop("app", None)
