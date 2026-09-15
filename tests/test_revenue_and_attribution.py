"""The two data-correctness bug classes CLAUDE.md records, pinned in place.

1. `closed_deals` holds BOTH Closed/Won and Closed/Lost rows. Every revenue
   path must filter on '10 - Closed/Won'; a Closed/LOST row that was still a
   technical win stays visible and counted, but contributes zero dollars.
2. The three-step SE precedence (assigned_se_rep_id > case-insensitive
   lead_se_name > opportunity-name fallback) must resolve identically at every
   query site — a rep attributed via step 1 or 2 reported $0 once already.
"""

import pytest
import reviews
import tech_forecast_report as report
import top_items
from attribution import EFFECTIVE_SE_ID_SQL
from conftest import (IN_CURRENT_FQ, add_closed_deal, add_deal, add_rep,
                      add_tf_deal)
from constants import STAGE_CLOSED_WON

WON = STAGE_CLOSED_WON
LOST = "7 - Closed/Lost"


# ═══════════════════════════════════════════════════════════════════════
# build_tech_win_trend
# ═══════════════════════════════════════════════════════════════════════
def test_closed_lost_tech_win_counts_but_earns_no_revenue():
    trend = report.build_tech_win_trend(
        closed_win_rows=[
            {"opportunity_id": "A", "opportunity_name": "Won Deal",
             "amount": 100_000.0, "close_date": "2026-09-15", "sales_stage": WON},
            {"opportunity_id": "B", "opportunity_name": "Lost Deal",
             "amount": 500_000.0, "close_date": "2026-09-20", "sales_stage": LOST},
        ],
        open_win_rows=[],
    )
    assert len(trend) == 1
    quarter = trend[0]
    assert quarter["fiscal_quarter"] == "FY26-Q3"
    assert quarter["count"] == 2, "the technical win happened even though the deal was lost"
    assert quarter["closed_lost_count"] == 1
    assert quarter["amount"] == 100_000.0, "the lost deal's $500k must not be booked as revenue"


def test_a_closed_row_without_a_stage_column_is_still_treated_as_won():
    trend = report.build_tech_win_trend(
        [{"opportunity_id": "A", "amount": 10.0, "close_date": "2026-09-15"}], []
    )
    assert trend[0]["amount"] == 10.0
    assert trend[0]["closed_lost_count"] == 0


def test_tech_win_trend_does_not_double_count_a_deal_in_both_tables_by_id():
    """A won deal lives in closed_deals AND lingers in tech_forecast_deals at
    Technical Win — it used to land in the quarter twice."""
    shared = {"opportunity_id": "006DUPE", "opportunity_name": "Shared Deal",
              "amount": 250_000.0, "close_date": "2026-09-15"}
    trend = report.build_tech_win_trend(
        [dict(shared, sales_stage=WON)],
        [dict(shared, sales_stage="5 - Negotiation", technical_win_date="2026-09-10")],
    )
    assert len(trend) == 1
    assert trend[0]["count"] == 1
    assert trend[0]["amount"] == 250_000.0


def test_tech_win_trend_dedupes_on_name_when_there_is_no_opportunity_id():
    shared = {"opportunity_id": None, "opportunity_name": "Shared Deal",
              "amount": 250_000.0, "close_date": "2026-09-15"}
    trend = report.build_tech_win_trend(
        [dict(shared, sales_stage=WON)], [dict(shared, sales_stage=None)]
    )
    assert trend[0]["count"] == 1


def test_an_open_row_already_marked_closed_won_is_skipped_entirely():
    trend = report.build_tech_win_trend(
        [],
        [{"opportunity_id": "X", "opportunity_name": "Already Closed",
          "amount": 99.0, "close_date": "2026-09-15", "sales_stage": WON}],
    )
    assert trend == []


def test_distinct_deals_are_counted_separately_per_fiscal_quarter():
    trend = report.build_tech_win_trend(
        [{"opportunity_id": "A", "amount": 10.0, "close_date": "2026-09-15", "sales_stage": WON},
         {"opportunity_id": "B", "amount": 20.0, "close_date": "2026-12-01", "sales_stage": WON}],
        [{"opportunity_id": "C", "amount": 30.0, "close_date": "2026-09-20",
          "technical_win_date": "2026-09-18", "sales_stage": "4 - Proposal"}],
    )
    assert [q["fiscal_quarter"] for q in trend] == ["FY26-Q3", "FY26-Q4"]
    assert [q["amount"] for q in trend] == [40.0, 20.0]


def test_undated_wins_are_labelled_and_sorted_last_not_emitted_as_null():
    trend = report.build_tech_win_trend(
        [{"opportunity_id": "A", "amount": 10.0, "close_date": "2026-09-15", "sales_stage": WON},
         {"opportunity_id": "B", "amount": 20.0, "close_date": None, "sales_stage": WON}],
        [],
    )
    assert [q["fiscal_quarter"] for q in trend] == ["FY26-Q3", "Undated"]
    assert None not in [q["fiscal_quarter"] for q in trend]


def test_open_technical_wins_are_dated_by_tech_win_date_before_close_date():
    trend = report.build_tech_win_trend(
        [],
        [{"opportunity_id": "A", "amount": 10.0, "close_date": "2026-12-01",
          "technical_win_date": "2026-09-15", "sales_stage": "4 - Proposal"}],
    )
    assert trend[0]["fiscal_quarter"] == "FY26-Q3"


# ═══════════════════════════════════════════════════════════════════════
# /api/dashboard/tech-win-trend, /api/closed-deals/summary, /api/reps
# ═══════════════════════════════════════════════════════════════════════
def test_tech_win_trend_endpoint_excludes_lost_revenue_but_keeps_the_count(api):
    body = api.get("/api/dashboard/tech-win-trend").get_json()
    q3 = [q for q in body if q["fiscal_quarter"] == "FY26-Q3"]
    assert len(q3) == 1
    # Seeded: won $400k tech win, LOST $650k tech win, open $210k tech win.
    assert q3[0]["count"] == 3
    assert q3[0]["closed_lost_count"] == 1
    assert q3[0]["amount"] == 610_000.0


def test_closed_deals_summary_counts_lost_tech_wins_without_calling_them_won(api):
    body = api.get("/api/closed-deals/summary").get_json()
    team = body["team"]
    # 3 closed deals with an assigned SE: 2 won, 1 lost; 2 of them tech wins.
    assert team["total"] == 3
    assert team["closed_won"] == 2
    assert team["tech_win"] == 2
    assert team["closed_won_pct"] == 0.667
    # The Tech Win Rate denominator is "closed deals with an SE", not wins.
    assert team["tech_win_pct"] == 0.667


def test_closed_deals_summary_rep_rows_split_won_from_tech_win(api):
    body = api.get("/api/closed-deals/summary").get_json()
    amara = next(r for r in body["reps"] if r["rep_name"] == "Amara Osei")
    assert (amara["total"], amara["closed_won"], amara["tech_win"]) == (2, 1, 2)
    assert amara["tech_win_pct"] == 1.0
    assert amara["closed_won_pct"] == 0.5


def test_closed_deals_summary_current_quarter_uses_the_fiscal_quarter_window(api):
    body = api.get("/api/closed-deals/summary").get_json()
    assert body["team_current_quarter"]["fiscal_quarter"] == "FY26-Q3"
    assert body["team_current_quarter"]["total"] == 3


def test_reps_arr_total_counts_only_closed_won_amounts(api):
    reps = {r["name"]: r for r in api.get("/api/reps").get_json()}
    # Amara: $400k won + $650k LOST -> only the won amount is revenue.
    assert reps["Amara Osei"]["arr_total"] == 400_000.0
    # Bo: one won deal with a NULL amount -> zero, not a crash.
    assert reps["Bo Nakamura"]["arr_total"] == 0


def test_a_lost_deal_added_later_does_not_inflate_arr_total(api):
    add_closed_deal(api.db, sheet_key="oid:0099", opportunity_id="0099",
                    rep_name="Amara Osei", se_rep_id=api.rep_ids["amara"],
                    opportunity_name="Late Lost Deal", amount=1_000_000.0,
                    close_date=IN_CURRENT_FQ, sales_stage=LOST, tech_win=1)
    reps = {r["name"]: r for r in api.get("/api/reps").get_json()}
    assert reps["Amara Osei"]["arr_total"] == 400_000.0


def test_recent_wins_report_lost_technical_wins_with_zero_revenue_amount(api):
    body = api.get("/api/tech-forecast").get_json()
    wins = {w["opportunity_name"]: w for w in body["recent_wins"]}
    lost = wins["Fenwick Logistics Expansion"]
    assert lost["win_status"] == "closed_lost"
    assert lost["counts_as_revenue"] is False
    assert lost["revenue_amount"] == 0
    assert lost["amount"] == 650_000.0, "still displayed, just not booked"

    won = wins["Lakeshore Utilities Platform"]
    assert won["win_status"] == "closed_won"
    assert won["revenue_amount"] == 400_000.0

    still_open = wins["Rivermouth Freight Portal"]
    assert still_open["win_status"] == "open"
    assert still_open["revenue_amount"] == 0


# ═══════════════════════════════════════════════════════════════════════
# reviews._build_context
# ═══════════════════════════════════════════════════════════════════════
def test_review_context_keeps_lost_deal_amounts_out_of_the_revenue_line(api):
    context = reviews._build_context(api.db, api.rep_ids["amara"])
    assert "$400,000.00 total revenue" in context
    assert "$1,050,000.00" not in context, "won + lost must never be summed together"
    assert "Closed-LOST deals this period (1, 1 of them still technical wins)" in context
    assert "Fenwick Logistics Expansion" in context
    assert "[TECHNICAL WIN]" in context


def test_review_context_for_a_rep_with_only_null_amounts_does_not_raise(api):
    context = reviews._build_context(api.db, api.rep_ids["bo"])
    assert "$0.00 total revenue" in context
    assert "Cobblestone Bank SSO" in context


def test_top_items_scaffold_lists_only_closed_won_deals(db):
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=2)).isoformat()
    rep = add_rep(db, "Amara Osei")
    add_closed_deal(db, sheet_key="w", opportunity_name="Won This Week", se_rep_id=rep,
                    amount=120_000.0, close_date=recent, sales_stage=WON, tech_win=1)
    add_closed_deal(db, sheet_key="l", opportunity_name="Lost This Week", se_rep_id=rep,
                    amount=900_000.0, close_date=recent, sales_stage=LOST, tech_win=1)
    scaffold = top_items.build_scaffold(db)
    assert "Won This Week" in scaffold
    assert "Lost This Week" not in scaffold


# ═══════════════════════════════════════════════════════════════════════
# Three-step SE attribution precedence
# ═══════════════════════════════════════════════════════════════════════
def test_each_attribution_step_resolves_a_rep_rather_than_reporting_zero(api):
    reps = {r["name"]: r for r in api.get("/api/reps").get_json()}
    # Amara: $300k via the manual override (step 1) + $210k via her sheet name
    # (step 2); Bo: $150k via a lowercase sheet name (step 2).
    assert reps["Amara Osei"]["tech_forecast_arr"] == 510_000.0
    assert reps["Bo Nakamura"]["tech_forecast_arr"] == 150_000.0
    assert reps["Amara Osei"]["tech_forecast_arr"] > 0
    assert reps["Bo Nakamura"]["tech_forecast_arr"] > 0


def test_lead_se_name_matching_is_case_insensitive(api):
    body = api.get("/api/tech-forecast").get_json()
    deal = next(d for d in body["deals"] if d["opportunity_name"] == "Seabright Ferries IAM")
    assert deal["lead_se_name"] == "bo nakamura"
    assert deal["effective_se_rep_id"] == api.rep_ids["bo"]
    assert deal["effective_se_name"] == "Bo Nakamura"


def test_manual_assignment_outranks_the_sheets_lead_se_name(api):
    add_tf_deal(api.db, sheet_key="oid:0090", opportunity_id="0090",
                opportunity_name="Override Wins Deal", lead_se_name="Bo Nakamura",
                assigned_se_rep_id=api.rep_ids["amara"], amount=75_000.0,
                presales_stage="4 - Validate Solution", close_date=IN_CURRENT_FQ)
    body = api.get("/api/tech-forecast").get_json()
    deal = next(d for d in body["deals"] if d["opportunity_name"] == "Override Wins Deal")
    assert deal["effective_se_rep_id"] == api.rep_ids["amara"]

    reps = {r["name"]: r for r in api.get("/api/reps").get_json()}
    assert reps["Amara Osei"]["tech_forecast_arr"] == 585_000.0
    assert reps["Bo Nakamura"]["tech_forecast_arr"] == 150_000.0


def test_opportunity_name_join_is_the_last_resort_not_the_only_rule(api):
    body = api.get("/api/tech-forecast").get_json()
    fallback = next(d for d in body["deals"] if d["opportunity_name"] == "Northwind Identity Refresh")
    assert fallback["lead_se_name"] == ""
    assert fallback["attributed_se_id"] == api.rep_ids["amara"]
    assert fallback["effective_se_rep_id"] == api.rep_ids["amara"]


def test_a_deal_nobody_resolves_is_reported_as_needing_a_lead_se(api):
    add_tf_deal(api.db, sheet_key="oid:0091", opportunity_id="0091",
                opportunity_name="Nobody's Deal", lead_se_name="", amount=1.0,
                presales_stage="", close_date=IN_CURRENT_FQ)
    body = api.get("/api/tech-forecast").get_json()
    deal = next(d for d in body["deals"] if d["opportunity_name"] == "Nobody's Deal")
    assert deal["effective_se_rep_id"] is None
    assert deal["needs_lead_se"] is True
    assert deal["effective_se_name"] == "Unassigned"


def test_every_query_site_agrees_on_who_owns_which_arr(api):
    """/api/reps' tech_forecast_arr column and /api/tech-forecast's per-deal
    attribution are two hand-written copies of the same precedence — the bug
    fixed on 2026-09-11 was exactly them disagreeing."""
    reps = {r["id"]: r for r in api.get("/api/reps").get_json()}
    deals = api.get("/api/tech-forecast").get_json()["deals"]

    per_rep = {}
    for d in deals:
        if d["effective_se_rep_id"]:
            per_rep[d["effective_se_rep_id"]] = per_rep.get(d["effective_se_rep_id"], 0) + (d["amount"] or 0)

    for rep_id, rep in reps.items():
        assert rep["tech_forecast_arr"] == per_rep.get(rep_id, 0), rep["name"]


def test_the_slack_preread_attributes_deals_the_same_way_the_pages_do(api, frozen_quarter):
    preread = report.build_preread(api.db)
    by_name = {d["opportunity_name"]: d for d in preread["top_deals"]}
    # Step 1 (manual override) — the sheet says someone else entirely.
    assert by_name["Granite Peak Zero Trust"]["effective_se_name"] == "Amara Osei"
    # Step 2 (case-insensitive sheet name).
    assert by_name["Seabright Ferries IAM"]["effective_se_name"] == "Bo Nakamura"
    # Step 3 (opportunity-name join).
    assert by_name["Northwind Identity Refresh"]["effective_se_name"] == "Amara Osei"


def test_needs_lead_se_reads_the_raw_sheet_column_not_the_resolved_name(db):
    """Resolving attribution here would hide exactly the rows the list exists
    to surface."""
    rep = add_rep(db, "Amara Osei")
    add_deal(db, sheet_key="d1", opportunity_name="Joined Deal", se_rep_id=rep)
    rows = [
        {"opportunity_name": "Joined Deal", "lead_se_name": "", "amount": 10.0,
         "effective_se_name": "Amara Osei"},
        {"opportunity_name": "Named Deal", "lead_se_name": "Amara Osei", "amount": 20.0},
    ]
    listed = [r["opportunity_name"] for r in report.build_needs_lead_se(rows)]
    assert listed == ["Joined Deal"]


def test_effective_se_display_name_falls_back_to_the_raw_sheet_name(db):
    """Names that are not se_reps rows at all (Mary Greenlee, departed reps)
    still display, and only a genuinely empty result means "no Lead SE"."""
    assert report.effective_se_display_name(
        {"effective_se_name": "Amara Osei", "lead_se_name": "stale"}) == "Amara Osei"
    assert report.effective_se_display_name(
        {"effective_se_name": None, "lead_se_name": "Mary Greenlee"}) == "Mary Greenlee"
    assert report.effective_se_display_name({}) == ""


# ── whitespace tolerance in the Lead SE name match ───────────────────────────
# The sheet is hand-maintained. A trailing space on a Lead SE cell used to drop
# the match, which surfaced as the deal reporting "Unassigned" and its ARR
# vanishing from that rep's total — no error, no warning.

@pytest.mark.parametrize("sheet_spelling", [
    "Nic Da Silva",     # exact
    "nic da silva",     # case only
    "Nic Da Silva ",    # trailing space
    " Nic Da Silva",    # leading space
])
def test_lead_se_name_matches_despite_surrounding_whitespace(db, sheet_spelling):
    rep_id = add_rep(db, "Nic Da Silva")
    add_tf_deal(db, sheet_key="k1", opportunity_name="Acme",
                lead_se_name=sheet_spelling, amount=100000)
    with db.conn() as c:
        got = c.execute(
            f"SELECT {EFFECTIVE_SE_ID_SQL} AS eff FROM tech_forecast_deals tf"
        ).fetchone()["eff"]
    assert got == rep_id


@pytest.mark.parametrize("sheet_spelling", ["NicDaSilva", "Da Silva, Nic", "Nic Da Silva Jr"])
def test_a_genuinely_different_spelling_is_not_guessed_at(db, sheet_spelling):
    """Attributing revenue to the wrong person is worse than not attributing
    it. These surface through lead_se_unmatched instead."""
    add_rep(db, "Nic Da Silva")
    add_tf_deal(db, sheet_key="k1", opportunity_name="Acme",
                lead_se_name=sheet_spelling, amount=100000)
    with db.conn() as c:
        got = c.execute(
            f"SELECT {EFFECTIVE_SE_ID_SQL} AS eff FROM tech_forecast_deals tf"
        ).fetchone()["eff"]
    assert got is None


def test_unmatched_name_is_reported_separately_from_no_name(api):
    """They rendered as the same "No Lead SE" chip while the Needs Lead SE card,
    which keys off the raw name, listed only one of them."""
    add_rep(api.db, "Nic Da Silva")
    add_tf_deal(api.db, sheet_key="a", opportunity_name="Unmatched",
                lead_se_name="NicDaSilva", amount=100000, close_date="2026-10-31")
    add_tf_deal(api.db, sheet_key="b", opportunity_name="NoName",
                lead_se_name="", amount=100000, close_date="2026-10-31")
    body = api.get("/api/tech-forecast").get_json()
    deals = {d["opportunity_name"]: d for d in body["deals"]}
    assert deals["Unmatched"]["lead_se_unmatched"] is True
    assert deals["NoName"]["lead_se_unmatched"] is False
    assert deals["NoName"]["needs_lead_se"] is True
