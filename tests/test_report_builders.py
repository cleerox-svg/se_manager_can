"""The rule-based report builders behind the Slack preread and the Actions
page's SFDC Updates card.

Both are deliberately heuristic rather than LLM-generated (no LITELLM_API_KEY
configured), which makes their priority order a spec worth pinning: if the
rules silently reorder, the Monday message asks the wrong question about the
wrong deal and nothing raises.
"""

from datetime import date
import json

import pytest

import tech_forecast_report as report
from conftest import IN_CURRENT_FQ, IN_LATER_FQ, IN_NEXT_FQ, IN_PAST_FQ
from constants import FORECAST_RISK, PRESALES_TECH_WIN, STAGE_CLOSED_WON


def deal(**overrides):
    row = {
        "sheet_key": "tf-1",
        "opportunity_name": "Granite Peak Zero Trust",
        "opportunity_id": "006SYNTH",
        "amount": 100_000.0,
        "presales_stage": "4 - Validate Solution",
        "forecast_status": "Strong",
        "sales_stage": "3 - Proposal",
        "lead_se_name": "Amara Osei",
        "pre_sales_next_steps": "Security review booked",
        "pre_sales_notes": "",
        "se_manager_notes": "",
        "close_date": IN_CURRENT_FQ,
        "technical_win_date": None,
        "notes_stale": 0,
    }
    row.update(overrides)
    return row


# ── discussion question heuristic ────────────────────────────────────────
def test_missing_next_steps_outranks_every_other_signal():
    question = report.build_discussion_question(
        deal(pre_sales_next_steps="", notes_stale=1, forecast_status=FORECAST_RISK)
    )
    assert "Nothing logged for next steps" in question


def test_stale_notes_outrank_an_at_risk_flag():
    question = report.build_discussion_question(
        deal(notes_stale=1, forecast_status=FORECAST_RISK)
    )
    assert "Hasn't moved since last sync" in question


def test_an_at_risk_flag_outranks_the_per_stage_prompt():
    question = report.build_discussion_question(deal(forecast_status=FORECAST_RISK))
    assert "at-risk" in question


def test_a_healthy_deal_gets_its_stage_specific_prompt():
    assert "how we do it better" in report.build_discussion_question(deal())
    assert "decision/paper process" in report.build_discussion_question(
        deal(presales_stage="5 - Final Due Diligence"))


def test_an_unknown_stage_falls_back_to_a_generic_prompt():
    question = report.build_discussion_question(deal(presales_stage="99 - Invented"))
    assert question == "What's needed to move this toward Technical Win?"


# ── SFDC note drafting ───────────────────────────────────────────────────
def test_a_confirmed_technical_win_drafts_a_no_action_note():
    note = report.draft_sfdc_note(deal(presales_stage=PRESALES_TECH_WIN, sales_stage="5 - Negotiation"))
    assert note.startswith("CL ")
    assert "Technical Win is confirmed" in note
    assert "Negotiation" in note, "the numeric stage prefix is stripped for humans"
    assert "5 - " not in note


def test_the_drafted_note_quotes_the_newest_dated_entry_verbatim():
    """Reusing what the SE actually wrote avoids fabricating claims about a
    deal — this text gets pasted straight into Salesforce."""
    note = report.draft_sfdc_note(deal(
        se_manager_notes="CL Sep-14-2026 : Exec sponsor engaged\r\n\r\nCL Sep-01-2026 : Kickoff done",
    ))
    assert "Latest SE Manager note: CL Sep-14-2026 : Exec sponsor engaged" in note
    assert "Sep-01-2026" not in note


def test_note_drafting_falls_back_through_presales_notes_then_next_steps():
    presales_only = report.draft_sfdc_note(deal(pre_sales_notes="RK Sep-10-2026 : POC running"))
    assert "No SE Manager note logged yet" in presales_only
    assert "RK Sep-10-2026 : POC running" in presales_only

    next_steps_only = report.draft_sfdc_note(
        deal(pre_sales_notes="", se_manager_notes="", pre_sales_next_steps="Chase the security review")
    )
    assert "next step on file: Chase the security review" in next_steps_only


def test_a_deal_with_no_notes_at_all_drafts_a_prompt_to_sync_with_the_se():
    note = report.draft_sfdc_note(deal(pre_sales_notes="", se_manager_notes="", pre_sales_next_steps=""))
    assert "No notes logged yet for Granite Peak Zero Trust" in note


# ── build_sfdc_updates ───────────────────────────────────────────────────
def test_sfdc_updates_cover_overdue_current_and_next_but_not_later(frozen_quarter):
    rows = [
        deal(sheet_key="a", opportunity_name="Overdue Deal", close_date=IN_PAST_FQ),
        deal(sheet_key="b", opportunity_name="Current Deal", close_date=IN_CURRENT_FQ),
        deal(sheet_key="c", opportunity_name="Next Deal", close_date=IN_NEXT_FQ),
        deal(sheet_key="d", opportunity_name="Later Deal", close_date=IN_LATER_FQ),
        deal(sheet_key="e", opportunity_name="Undated Deal", close_date=None),
    ]
    listed = {u["opportunity_name"]: u["quarter_bucket"] for u in report.build_sfdc_updates(rows)}
    assert listed == {"Overdue Deal": "overdue", "Current Deal": "current", "Next Deal": "next"}


def test_sfdc_updates_skip_deals_that_have_already_closed_won(frozen_quarter):
    rows = [deal(sales_stage=STAGE_CLOSED_WON)]
    assert report.build_sfdc_updates(rows) == []


def test_sfdc_updates_are_capped_and_ordered_by_amount(frozen_quarter):
    rows = [deal(sheet_key=f"k{i}", opportunity_name=f"Deal {i}", amount=float(i))
            for i in range(30)]
    listed = report.build_sfdc_updates(rows)
    assert len(listed) == report.DEFAULT_LIST_LIMIT
    assert listed[0]["opportunity_name"] == "Deal 29"
    assert [u["amount"] for u in listed] == sorted((u["amount"] for u in listed), reverse=True)


# ── build_top_deals ──────────────────────────────────────────────────────
def test_top_deals_exclude_deals_already_past_the_inspection_point(frozen_quarter):
    rows = [
        deal(sheet_key="a", opportunity_name="Won Already", presales_stage=PRESALES_TECH_WIN),
        deal(sheet_key="b", opportunity_name="Final Diligence", presales_stage="5 - Final Due Diligence"),
        deal(sheet_key="c", opportunity_name="Still In Flight"),
    ]
    assert [d["opportunity_name"] for d in report.build_top_deals(rows)] == ["Still In Flight"]


def test_top_deals_cap_each_quarter_separately_so_one_cannot_starve_another(frozen_quarter):
    current = [deal(sheet_key=f"c{i}", opportunity_name=f"Current {i}", amount=1_000_000.0 + i,
                    close_date=IN_CURRENT_FQ) for i in range(3)]
    nxt = [deal(sheet_key=f"n{i}", opportunity_name=f"Next {i}", amount=10.0,
                close_date=IN_NEXT_FQ) for i in range(3)]
    later = [deal(sheet_key=f"l{i}", opportunity_name=f"Later {i}", amount=5.0,
                  close_date=IN_LATER_FQ) for i in range(3)]

    selected = report.build_top_deals(current + nxt + later, limit=1)
    buckets = [d["quarter_bucket"] for d in selected]

    assert buckets.count("current") == 3, "a small limit must not starve the current quarter"
    assert buckets.count("next") == 3
    assert buckets.count("later") == 1, "the flat limit still caps the unscheduled tail"


def test_overdue_deals_lead_the_top_deals_list(frozen_quarter):
    rows = [
        deal(sheet_key="c", opportunity_name="Current Deal", amount=999_999.0, close_date=IN_CURRENT_FQ),
        deal(sheet_key="o", opportunity_name="Overdue Deal", amount=1.0, close_date=IN_PAST_FQ),
    ]
    selected = report.build_top_deals(rows)
    assert selected[0]["opportunity_name"] == "Overdue Deal"
    assert selected[0]["quarter_bucket"] == "overdue"


def test_top_deals_prefer_the_tech_win_date_over_the_close_date(frozen_quarter):
    row = deal(close_date=IN_LATER_FQ, technical_win_date=IN_CURRENT_FQ)
    selected = report.build_top_deals([row])
    assert selected[0]["target_tw_date"] == IN_CURRENT_FQ
    assert selected[0]["quarter_bucket"] == "current"
    assert selected[0]["target_fiscal_quarter"] == "FY26-Q3"


# ── stage bucketing / metrics ────────────────────────────────────────────
@pytest.mark.parametrize("stage,bucket", [
    ("2 - Discovery & Technical Qualification", "Early Tech"),
    ("3 - Technical Scoping", "Early Tech"),
    ("4 - Validate Solution", "Validate Solution"),
    ("5 - Final Due Diligence", "Final Due Diligence"),
    (PRESALES_TECH_WIN, "Technical Win"),
    ("", "Untagged"),
    (None, "Untagged"),
    ("99 - Invented", "Untagged"),
])
def test_stage_bucket_mapping(stage, bucket):
    assert report.stage_bucket(stage) == bucket


def test_metric_class_only_claims_the_three_classes_it_reports():
    assert report.metric_class("Technical Win") == "won"
    assert report.metric_class("Validate Solution") == "in_flight"
    assert report.metric_class("Final Due Diligence") == "in_flight"
    assert report.metric_class("Untagged") == "untagged"
    assert report.metric_class("Early Tech") is None


def test_key_metrics_percentages_are_shares_of_total_pipeline():
    rows = [
        deal(sheet_key="a", amount=750_000.0, presales_stage=PRESALES_TECH_WIN),
        deal(sheet_key="b", amount=250_000.0, presales_stage="4 - Validate Solution"),
    ]
    metrics = report.build_key_metrics(rows)
    assert metrics["total_active_pipeline_amount"] == 1_000_000.0
    assert metrics["total_tech_won_pct"] == 0.75
    assert metrics["in_flight_amount"] == 250_000.0


def test_key_metrics_of_an_empty_board_do_not_divide_by_zero():
    metrics = report.build_key_metrics([])
    assert metrics["total_tech_won_pct"] == 0.0
    assert metrics["total_active_pipeline_count"] == 0


def test_breakdown_orders_stages_from_won_backwards():
    rows = [
        deal(sheet_key="a", confidence="Commit", presales_stage="3 - Technical Scoping"),
        deal(sheet_key="b", confidence="Commit", presales_stage=PRESALES_TECH_WIN),
    ]
    breakdown = report.build_breakdown(rows)
    assert [s["bucket"] for s in breakdown[0]["stages"]] == ["Technical Win", "Early Tech"]


def test_arr_trend_reclassifies_stored_snapshot_totals(db):
    rows = [{
        "snapshot_date": "2026-09-01",
        "bucket_totals_json": json.dumps({
            "Commit": {"Technical Win": {"amount": 100.0, "count": 1},
                       "Validate Solution": {"amount": 50.0, "count": 1}},
            "Upside": {"Untagged": {"amount": 25.0, "count": 2}},
        }),
    }]
    trend = report.build_arr_trend(rows)
    assert trend[0]["total_amount"] == 175.0
    assert trend[0]["total_count"] == 4
    assert trend[0]["tech_won_amount"] == 100.0
    assert trend[0]["in_flight_amount"] == 50.0
    assert trend[0]["untagged_count"] == 2


def test_weekly_deltas_report_nothing_when_there_is_no_prior_snapshot():
    assert report.build_weekly_deltas([deal()], None) == []
    assert report.build_weekly_deltas([deal()], {}) == []


def test_weekly_deltas_label_a_stage_move_as_advanced_or_regressed():
    prior = {"tf-1": {"opportunity_name": "Granite Peak Zero Trust", "opportunity_id": "006SYNTH",
                      "amount": 100_000.0, "presales_stage": "3 - Technical Scoping",
                      "forecast_status": "Strong"}}
    advanced = report.build_weekly_deltas([deal(presales_stage="5 - Final Due Diligence")], prior)
    assert advanced[0]["type"] == "advanced"

    regressed = report.build_weekly_deltas(
        [deal(presales_stage="2 - Discovery & Technical Qualification")], prior
    )
    assert regressed[0]["type"] == "regressed"


def test_weekly_deltas_report_a_forecast_status_change_when_the_stage_holds():
    prior = {"tf-1": {"opportunity_name": "Granite Peak Zero Trust", "opportunity_id": "006SYNTH",
                      "amount": 100_000.0, "presales_stage": "4 - Validate Solution",
                      "forecast_status": "Strong"}}
    deltas = report.build_weekly_deltas([deal(forecast_status=FORECAST_RISK)], prior)
    assert deltas[0]["type"] == "status_change"
    assert "Strong -> Forecasted Risk" in deltas[0]["detail"]


# ── quarter ARR history (stat-tile trend) ────────────────────────────────────

def _snap(day, rows):
    return (day, json.dumps({f"k{i}": r for i, r in enumerate(rows)}))


def test_history_measures_every_point_against_todays_quarter(frozen_quarter):
    """Each point must use the SAME quarter, otherwise the series rebases at
    each boundary and the trend means nothing."""
    hist = report.build_quarter_arr_history([
        _snap("2026-09-01", [{"amount": 100000, "close_date": "2026-10-31"}]),
        _snap("2026-09-08", [{"amount": 140000, "close_date": "2026-10-31"}]),
    ])
    assert [h["current_arr"] for h in hist] == [100000, 140000]


def test_history_prefers_the_technical_win_date_over_close_date(frozen_quarter):
    hist = report.build_quarter_arr_history([
        _snap("2026-09-01", [
            {"amount": 180000, "technical_win_date": "2026-09-30", "close_date": "2027-05-01"},
        ]),
    ])
    assert hist[0]["current_arr"] == 180000


def test_history_skips_snapshots_with_no_target_dates(frozen_quarter):
    """Snapshots predating the recorded dates contribute nothing — reporting
    them as $0 would read as a collapsed pipeline rather than missing data."""
    hist = report.build_quarter_arr_history([
        _snap("2026-08-01", [{"amount": 90000}]),                       # no dates
        _snap("2026-09-01", [{"amount": 100000, "close_date": "2026-10-31"}]),
    ])
    assert [h["snapshot_date"] for h in hist] == ["2026-09-01"]


def test_history_is_capped_and_oldest_first(frozen_quarter):
    snaps = [_snap(f"2026-09-{d:02d}", [{"amount": d, "close_date": "2026-10-31"}])
             for d in range(1, 13)]
    hist = report.build_quarter_arr_history(snaps, limit=4)
    assert len(hist) == 4
    assert [h["snapshot_date"] for h in hist] == [
        "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"]


def test_delta_is_none_rather_than_zero_when_there_is_no_history():
    """Unknown and unchanged both render as 0 but mean opposite things, so the
    caller has to be able to tell them apart."""
    assert report.quarter_arr_delta([], 250000) is None
    assert report.quarter_arr_delta([{"current_arr": 200000}], 250000) == 50000


def test_delta_ignores_a_snapshot_written_by_todays_own_sync():
    """The snapshot is captured after the sync writes its rows and upserts on
    today's date, so on a sync day the newest entry already holds the post-sync
    state. Comparing against it reports ~0 forever."""
    today = date.today().isoformat()
    history = [
        {"snapshot_date": "2026-09-08", "current_arr": 900000},
        {"snapshot_date": today, "current_arr": 1180000},
    ]
    assert report.quarter_arr_delta(history, 1180000) == 280000


def test_delta_is_none_when_only_todays_snapshot_exists():
    today = date.today().isoformat()
    history = [{"snapshot_date": today, "current_arr": 1180000}]
    assert report.quarter_arr_delta(history, 1180000) is None
