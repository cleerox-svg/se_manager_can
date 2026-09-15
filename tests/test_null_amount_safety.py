"""A NULL `amount` must never raise.

A blank money cell syncs as SQL NULL, and `f"${None:,.0f}"` raises TypeError —
which is how a single unpriced deal on the board 500'd whole endpoints. Every
builder that formats or sums money gets a NULL-amount row here.
"""

import json
from datetime import date, timedelta

import pytest

import reviews
import tech_forecast_report as report
from conftest import (IN_CURRENT_FQ, IN_NEXT_FQ, IN_PAST_FQ, add_closed_deal,
                      add_deal, add_rep, add_tf_deal)


def unpriced_row(**overrides):
    row = {
        "sheet_key": "tf-unpriced",
        "opportunity_name": "Unpriced Deal",
        "opportunity_id": None,
        "amount": None,
        "presales_stage": "4 - Validate Solution",
        "forecast_status": "Strong",
        "sales_stage": "3 - Proposal",
        "lead_se_name": "Amara Osei",
        "pre_sales_next_steps": "",
        "pre_sales_notes": "",
        "se_manager_notes": "",
        "close_date": IN_CURRENT_FQ,
        "technical_win_date": None,
        "notes_stale": 0,
    }
    row.update(overrides)
    return row


def test_money_formatting_treats_a_null_amount_as_zero():
    assert report._money(None) == "$0"
    assert report._money(0) == "$0"
    assert report._money(1234.5) == "$1,234"


def test_build_top_deals_handles_null_amounts(frozen_quarter):
    deals = report.build_top_deals([
        unpriced_row(),
        unpriced_row(sheet_key="tf-priced", opportunity_name="Priced Deal", amount=100.0),
    ])
    amounts = {d["opportunity_name"]: d["amount"] for d in deals}
    assert amounts == {"Unpriced Deal": 0, "Priced Deal": 100.0}


def test_top_deals_ordering_is_deterministic_when_amounts_tie(frozen_quarter):
    rows = [
        unpriced_row(sheet_key="b", opportunity_name="Bravo"),
        unpriced_row(sheet_key="a", opportunity_name="Alpha"),
        unpriced_row(sheet_key="c", opportunity_name="Charlie"),
    ]
    first = [d["opportunity_name"] for d in report.build_top_deals(rows)]
    second = [d["opportunity_name"] for d in report.build_top_deals(list(reversed(rows)))]
    assert first == second == ["Alpha", "Bravo", "Charlie"]


def test_build_missing_notes_handles_null_amounts():
    listed = report.build_missing_notes([unpriced_row(pre_sales_next_steps="   ")])
    assert listed[0]["amount"] == 0
    assert listed[0]["opportunity_name"] == "Unpriced Deal"


def test_build_sfdc_updates_handles_null_amounts(frozen_quarter):
    updates = report.build_sfdc_updates([unpriced_row()])
    assert len(updates) == 1
    assert updates[0]["amount"] == 0
    assert updates[0]["proposed_note"]


def test_build_needs_lead_se_handles_null_amounts():
    listed = report.build_needs_lead_se([unpriced_row(lead_se_name="")])
    assert listed[0]["amount"] == 0


def test_key_metrics_and_buckets_handle_null_amounts():
    rows = [unpriced_row(), unpriced_row(sheet_key="x", amount=50.0,
                                         presales_stage="6 - Technical Win", confidence="Commit")]
    metrics = report.build_key_metrics(rows)
    assert metrics["total_active_pipeline_amount"] == 50.0
    assert metrics["total_active_pipeline_count"] == 2
    assert metrics["total_tech_won_amount"] == 50.0
    buckets = report.aggregate_buckets(rows)
    assert buckets["Untagged"]["Validate Solution"] == {"amount": 0.0, "count": 1}


def test_executive_takeaway_renders_with_an_entirely_unpriced_pipeline():
    text = report.build_executive_takeaway(report.build_key_metrics([unpriced_row()]))
    assert "$0" in text
    assert "1 active opportunities" in text


def test_weekly_deltas_handle_null_amounts_on_both_sides():
    prior = {
        "gone": {"opportunity_name": "Dropped Deal", "opportunity_id": None, "amount": None,
                 "presales_stage": "3 - Technical Scoping", "forecast_status": "Strong"},
        "tf-unpriced": {"opportunity_name": "Unpriced Deal", "opportunity_id": None, "amount": None,
                        "presales_stage": "3 - Technical Scoping", "forecast_status": "Strong"},
    }
    deltas = report.build_weekly_deltas(
        [unpriced_row(), unpriced_row(sheet_key="brand-new", opportunity_name="New Deal")], prior
    )
    kinds = {d["opportunity_name"]: d["type"] for d in deltas}
    assert kinds == {"Dropped Deal": "dropped", "Unpriced Deal": "advanced", "New Deal": "new"}
    assert all(d["amount"] == 0 for d in deltas)


def test_build_slack_draft_renders_a_board_where_nothing_has_an_amount(db, frozen_quarter):
    """End-to-end through build_preread: the draft used to crash on the first
    unpriced deal in any of its three deal-bullet sections."""
    add_rep(db, "Amara Osei")
    add_tf_deal(db, sheet_key="tf-1", opportunity_name="Unpriced Current", amount=None,
                lead_se_name="Amara Osei", presales_stage="4 - Validate Solution",
                forecast_status="Forecasted Risk", close_date=IN_CURRENT_FQ,
                pre_sales_next_steps="")
    add_tf_deal(db, sheet_key="tf-2", opportunity_name="Unpriced Next", amount=None,
                lead_se_name="", presales_stage="3 - Technical Scoping",
                forecast_status="Strong", close_date=IN_NEXT_FQ)
    add_tf_deal(db, sheet_key="tf-3", opportunity_name="Unpriced Overdue", amount=None,
                lead_se_name="Mary Greenlee", presales_stage="2 - Discovery & Technical Qualification",
                close_date=IN_PAST_FQ)
    add_tf_deal(db, sheet_key="tf-4", opportunity_name="Unpriced Undated", amount=None,
                lead_se_name="Amara Osei", presales_stage="", close_date=None)
    with db.conn() as c:
        c.execute(
            "INSERT INTO tech_forecast_snapshots (snapshot_date, bucket_totals_json, deal_states_json) "
            "VALUES (?, '{}', ?)",
            ((date.today() - timedelta(days=7)).isoformat(),
             json.dumps({"tf-1": {"opportunity_name": "Unpriced Current", "opportunity_id": None,
                                  "amount": None, "presales_stage": "2 - Discovery & Technical Qualification",
                                  "forecast_status": "Strong"}})),
        )

    preread = report.build_preread(db)
    draft = report.build_slack_draft(preread)

    assert "$0" in draft
    assert "Unpriced Current" in draft
    assert "Unpriced Overdue" in draft
    assert "No Lead SE on file" in draft
    assert "Mary Greenlee" in draft, "a name that isn't an se_reps row still displays"
    assert "None" not in draft.replace("no Lead SE on file", "")


def test_review_context_survives_null_amounts_in_every_section(db):
    rep = add_rep(db, "Amara Osei")
    add_closed_deal(db, sheet_key="c1", opportunity_name="Unpriced Won", se_rep_id=rep,
                    amount=None, close_date=IN_CURRENT_FQ, sales_stage="10 - Closed/Won", tech_win=1)
    add_closed_deal(db, sheet_key="c2", opportunity_name="Unpriced Lost", se_rep_id=rep,
                    amount=None, close_date=IN_CURRENT_FQ, sales_stage="7 - Closed/Lost", tech_win=1)
    add_deal(db, sheet_key="d1", opportunity_name="Unpriced Open", se_rep_id=rep, amount=None)

    context = reviews._build_context(db, rep)

    assert "$0.00 total revenue" in context
    assert "Unpriced Won" in context and "Unpriced Lost" in context and "Unpriced Open" in context


@pytest.mark.parametrize("path", [
    "/api/tech-forecast",
    "/api/tech-forecast/preread",
    "/api/tech-forecast/sfdc-updates",
    "/api/dashboard/funnel",
    "/api/dashboard/tech-win-trend",
    "/api/closed-deals/summary",
    "/api/reps",
])
def test_endpoints_do_not_500_on_a_board_full_of_null_amounts(api, path):
    with api.db.conn() as c:
        c.execute("UPDATE tech_forecast_deals SET amount = NULL")
        c.execute("UPDATE closed_deals SET amount = NULL")
        c.execute("UPDATE deals SET amount = NULL")
    assert api.get(path).status_code == 200


def test_slack_draft_endpoint_does_not_500_on_null_amounts(api):
    with api.db.conn() as c:
        c.execute("UPDATE tech_forecast_deals SET amount = NULL")
    response = api.post("/api/tech-forecast/preread/draft")
    assert response.status_code == 200
    assert response.get_json()["draft"]
