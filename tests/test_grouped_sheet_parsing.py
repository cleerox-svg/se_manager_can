"""The grouped/hierarchical sheet layout, per sync module.

All three tabs export group columns that are populated only on a group's
first row, interspersed with subtotal rows whose marker text can land one
column over from its own level. Getting this wrong does not raise — it
reassigns a deal to the wrong SE, which is how NOVA Chemicals and MacEwan
University lost their Lead SE (commit bf03fc7).

Every grid below is synthetic.
"""

import pytest

import closed_deals_sync
import sheets_sync
import tech_forecast_sync
from conftest import CLOSED_HEADER, DEALS_HEADER, TF_HEADER, grid


def deals_rows(*rows):
    return sheets_sync._normalize_values(grid(DEALS_HEADER, *rows))


def closed_rows(*rows):
    return closed_deals_sync._normalize_values(grid(CLOSED_HEADER, *rows))


def tf_rows(*rows):
    return tech_forecast_sync._normalize_values(grid(TF_HEADER, *rows))


# ═══════════════════════════════════════════════════════════════════════
# deals tab ("Lead SE Pipeline SFDC") — two group levels
# ═══════════════════════════════════════════════════════════════════════
def test_deals_group_columns_forward_fill_onto_following_rows():
    rows = deals_rows(
        {"Lead Sales Engineer": "Amara Osei (2)", "Stage": "3 - Technical Scoping (2)",
         "Opportunity Name": "Alpha Rollout", "Close Date": "5/4/2026", "Amount": "$1,000"},
        {"Opportunity Name": "Beta Rollout", "Close Date": "6/4/2026", "Amount": "$2,000"},
    )
    assert [r["lead_se"] for r in rows] == ["Amara Osei", "Amara Osei"]
    assert [r["stage"] for r in rows] == ["3 - Technical Scoping", "3 - Technical Scoping"]


def test_deals_new_lead_se_does_not_inherit_the_previous_leads_stage():
    """The cascade: changing Lead SE resets the Stage fill. Without it the new
    lead's first (blank-stage) row silently takes the previous lead's stage."""
    rows = deals_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Stage": "4 - Validate Solution (1)",
         "Opportunity Name": "Alpha Rollout"},
        {"Lead Sales Engineer": "Bo Nakamura (1)", "Stage": "",
         "Opportunity Name": "Beta Rollout"},
    )
    assert rows[1]["lead_se"] == "Bo Nakamura"
    assert rows[1]["stage"] == ""


def test_deals_subtotal_marker_row_is_dropped_without_resetting_the_fill():
    """A per-lead Subtotal row puts the marker in the Lead SE column itself.
    It is row-shape noise, not a group boundary."""
    rows = deals_rows(
        {"Lead Sales Engineer": "Amara Osei (2)", "Stage": "4 - Validate Solution (2)",
         "Opportunity Name": "Alpha Rollout"},
        {"Lead Sales Engineer": "Subtotal", "Stage": "", "Opportunity Name": ""},
        {"Opportunity Name": "Gamma Rollout"},
    )
    assert [r["opportunity_name"] for r in rows] == ["Alpha Rollout", "Gamma Rollout"]
    assert rows[1]["lead_se"] == "Amara Osei"
    assert rows[1]["stage"] == "4 - Validate Solution"


def test_deals_bare_dash_lead_reads_as_unassigned_on_this_tab():
    """Unlike the other two tabs, this one maps "-" to a real group name so it
    forward-fills instead of inheriting whichever lead preceded it."""
    rows = deals_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Stage": "2 - Discovery (1)",
         "Opportunity Name": "Alpha Rollout"},
        {"Lead Sales Engineer": "-", "Stage": "2 - Discovery (2)",
         "Opportunity Name": "Orphan Deal"},
        {"Opportunity Name": "Second Orphan Deal"},
    )
    assert rows[1]["lead_se"] == "Unassigned"
    assert rows[2]["lead_se"] == "Unassigned"


def test_deals_account_named_totalenergies_survives_the_skip_row_filter():
    rows = deals_rows(
        {"Lead Sales Engineer": "Amara Osei (2)", "Stage": "2 - Discovery (2)",
         "Opportunity Name": "TotalEnergies Identity Program", "Amount": "$900,000"},
        {"Opportunity Name": "Total Rewards Platform", "Amount": "$5,000"},
        {"Lead Sales Engineer": "Subtotal", "Opportunity Name": ""},
    )
    assert [r["opportunity_name"] for r in rows] == [
        "TotalEnergies Identity Program", "Total Rewards Platform",
    ]


def test_deals_rows_without_an_opportunity_name_are_dropped():
    rows = deals_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Stage": "2 - Discovery (1)",
         "Opportunity Name": "Alpha Rollout"},
        {"Opportunity Name": "   "},
        {"Lead Sales Engineer": "Total", "Opportunity Name": ""},
    )
    assert len(rows) == 1


def test_deals_empty_grid_normalizes_to_no_rows():
    assert sheets_sync._normalize_values([]) == []


def test_deals_header_mismatch_raises_naming_the_missing_column():
    bad_header = [h for h in DEALS_HEADER if h != "Close Date"]
    with pytest.raises(ValueError) as excinfo:
        sheets_sync._normalize_values(grid(bad_header, {"Opportunity Name": "Alpha"}))
    assert "Close Date" in str(excinfo.value)


# ═══════════════════════════════════════════════════════════════════════
# closed deals tab — three group levels + running-dollar-total suffixes
# ═══════════════════════════════════════════════════════════════════════
def test_closed_deals_three_group_levels_forward_fill():
    rows = closed_rows(
        {"Team Member Name": "Sean Keleher (USD 1,099,753.82)", "Team Role": "Lead SE",
         "Opportunity : Account Name : Account Owner : User Sales Region": "West",
         "Opportunity Name": "Alpha Win", "Amount (converted)": "USD 100,000.00",
         "Close Date": "5/4/2026", "Stage": "10 - Closed/Won",
         "Presales Stage": "6 - Technical Win"},
        {"Opportunity Name": "Beta Win", "Amount (converted)": "USD 50,000.00",
         "Close Date": "5/6/2026", "Stage": "10 - Closed/Won"},
    )
    assert [r["rep_name"] for r in rows] == ["Sean Keleher", "Sean Keleher"]
    assert [r["team_role"] for r in rows] == ["Lead SE", "Lead SE"]
    assert [r["region"] for r in rows] == ["West", "West"]


def test_closed_deals_running_dollar_total_suffix_is_stripped_from_the_rep_name():
    rows = closed_rows(
        {"Team Member Name": "Rishika Kondaveeti (USD 2,538,735.02)", "Team Role": "Lead SE",
         "Opportunity Name": "Alpha Win", "Amount (converted)": "USD 1.00",
         "Close Date": "5/4/2026", "Stage": "10 - Closed/Won", "Presales Stage": ""},
    )
    assert rows[0]["rep_name"] == "Rishika Kondaveeti"


def test_closed_deals_new_rep_does_not_inherit_the_previous_reps_role_or_region():
    rows = closed_rows(
        {"Team Member Name": "Sean Keleher (USD 10.00)", "Team Role": "Lead SE",
         "Opportunity : Account Name : Account Owner : User Sales Region": "West",
         "Opportunity Name": "Alpha Win", "Amount (converted)": "USD 10.00",
         "Close Date": "5/4/2026", "Stage": "10 - Closed/Won", "Presales Stage": ""},
        {"Team Member Name": "Amara Osei (USD 20.00)", "Team Role": "", "Opportunity Name": "Beta Win",
         "Amount (converted)": "USD 20.00", "Close Date": "5/5/2026",
         "Stage": "10 - Closed/Won", "Presales Stage": ""},
    )
    assert rows[1]["rep_name"] == "Amara Osei"
    assert rows[1]["team_role"] == ""
    assert rows[1]["region"] == ""


def test_closed_deals_marker_row_keeps_buffering_a_late_arriving_rep_name():
    """The NOVA Chemicals / MacEwan regression (bf03fc7), on this tab's loop:
    a group whose name only appears on its trailing Subtotal row must still
    backfill onto the deal rows already read, and an intervening marker row
    must not discard that buffer."""
    rows = closed_rows(
        {"Opportunity Name": "NOVA Chemicals Renewal", "Amount (converted)": "USD 10.00",
         "Close Date": "5/4/2026", "Stage": "10 - Closed/Won", "Presales Stage": ""},
        {"Team Member Name": "Subtotal", "Opportunity Name": ""},
        {"Team Member Name": "Rishika Kondaveeti (USD 2,538,735.02)", "Team Role": "Lead SE",
         "Opportunity Name": "MacEwan University Expansion", "Amount (converted)": "USD 20.00",
         "Close Date": "5/5/2026", "Stage": "10 - Closed/Won", "Presales Stage": ""},
    )
    assert [r["rep_name"] for r in rows] == ["Rishika Kondaveeti", "Rishika Kondaveeti"]


def test_closed_deals_bare_dash_rep_reads_as_unassigned_rather_than_a_person():
    rows = closed_rows(
        {"Team Member Name": "Sean Keleher (USD 10.00)", "Team Role": "Lead SE",
         "Opportunity Name": "Alpha Win", "Amount (converted)": "USD 10.00",
         "Close Date": "5/4/2026", "Stage": "10 - Closed/Won", "Presales Stage": ""},
        {"Team Member Name": "-", "Opportunity Name": "Ownerless Win",
         "Amount (converted)": "USD 20.00", "Close Date": "5/5/2026",
         "Stage": "10 - Closed/Won", "Presales Stage": ""},
    )
    assert rows[1]["rep_name"] == ""
    assert rows[1]["rep_name"] != "-"


def test_closed_deals_technical_win_flag_comes_from_the_flat_presales_stage_column():
    rows = closed_rows(
        {"Team Member Name": "Sean Keleher (USD 10.00)", "Opportunity Name": "Tech Win Deal",
         "Amount (converted)": "USD 10.00", "Close Date": "5/4/2026",
         "Stage": "10 - Closed/Won", "Presales Stage": "6 - Technical Win"},
        {"Opportunity Name": "Plain Deal", "Amount (converted)": "USD 20.00",
         "Close Date": "5/5/2026", "Stage": "7 - Closed/Lost", "Presales Stage": ""},
    )
    assert [r["tech_win"] for r in rows] == [1, 0]
    # Presales Stage is flat per-row here: a blank cell must NOT forward-fill.
    assert rows[1]["presales_stage"] == ""


def test_closed_deals_totalenergies_survives_and_subtotals_are_dropped():
    rows = closed_rows(
        {"Team Member Name": "Sean Keleher (USD 10.00)", "Opportunity Name": "TotalEnergies Renewal",
         "Amount (converted)": "USD 10.00", "Close Date": "5/4/2026",
         "Stage": "10 - Closed/Won", "Presales Stage": ""},
        {"Team Member Name": "Subtotal", "Opportunity Name": "Subtotal",
         "Amount (converted)": "USD 10.00"},
        {"Opportunity Name": "", "Amount (converted)": "USD 10.00"},
    )
    assert [r["opportunity_name"] for r in rows] == ["TotalEnergies Renewal"]


def test_closed_deals_header_mismatch_raises_naming_the_missing_columns():
    bad_header = [h for h in CLOSED_HEADER if h not in ("Stage", "Presales Stage")]
    with pytest.raises(ValueError) as excinfo:
        closed_deals_sync._normalize_values(grid(bad_header, {"Opportunity Name": "Alpha"}))
    message = str(excinfo.value)
    assert "Stage" in message and "Presales Stage" in message


# ═══════════════════════════════════════════════════════════════════════
# tech forecast tab — two group levels + flat Presales Stage + org tagging
# ═══════════════════════════════════════════════════════════════════════
def test_tech_forecast_group_levels_forward_fill():
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (2)", "Deal Forecast Status": "Strong (2)",
         "Opportunity Name": "Alpha", "Close Date": "5/4/2026",
         "Amount (converted)": "1,000", "Presales Stage": "4 - Validate Solution"},
        {"Opportunity Name": "Beta", "Close Date": "6/4/2026", "Amount (converted)": "2,000",
         "Presales Stage": "3 - Technical Scoping"},
    )
    assert [r["lead_se_name"] for r in rows] == ["Amara Osei", "Amara Osei"]
    assert [r["forecast_status"] for r in rows] == ["Strong", "Strong"]


def test_tech_forecast_new_lead_se_does_not_inherit_the_previous_ses_forecast_status():
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Forecasted Risk (1)",
         "Opportunity Name": "Alpha", "Close Date": "5/4/2026", "Amount (converted)": "1,000",
         "Presales Stage": "4 - Validate Solution"},
        {"Lead Sales Engineer": "Bo Nakamura (1)", "Deal Forecast Status": "",
         "Opportunity Name": "Beta", "Close Date": "6/4/2026", "Amount (converted)": "2,000",
         "Presales Stage": "3 - Technical Scoping"},
    )
    assert rows[1]["lead_se_name"] == "Bo Nakamura"
    assert rows[1]["forecast_status"] == ""


def test_tech_forecast_presales_stage_is_flat_per_deal_and_never_forward_filled():
    """Presales Stage stopped being a group level on 2026-09-02 — a blank cell
    means "not staged yet", not "same as the row above"."""
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (2)", "Deal Forecast Status": "Strong (2)",
         "Opportunity Name": "Alpha", "Close Date": "5/4/2026", "Amount (converted)": "1,000",
         "Presales Stage": "6 - Technical Win"},
        {"Opportunity Name": "Beta", "Close Date": "6/4/2026", "Amount (converted)": "2,000",
         "Presales Stage": ""},
    )
    assert [r["presales_stage"] for r in rows] == ["6 - Technical Win", ""]
    assert [r["is_tech_win"] for r in rows] == [1, 0]


def test_tech_forecast_marker_row_keeps_buffering_a_late_arriving_lead_se():
    """The bf03fc7 regression, on the tab it was found on: NOVA Chemicals is
    read before its group's name appears, an artifact Subtotal row sits in
    between, and the name finally arrives on the group's own trailing row."""
    rows = tf_rows(
        {"Opportunity Name": "NOVA Chemicals Renewal", "Close Date": "5/4/2026",
         "Amount (converted)": "1,000", "Presales Stage": "4 - Validate Solution"},
        {"Lead Sales Engineer": "Subtotal", "Opportunity Name": ""},
        {"Lead Sales Engineer": "Rishika Kondaveeti (2)", "Deal Forecast Status": "Strong (1)",
         "Opportunity Name": "MacEwan University Expansion", "Close Date": "5/5/2026",
         "Amount (converted)": "2,000", "Presales Stage": "5 - Final Due Diligence"},
    )
    assert [r["lead_se_name"] for r in rows] == ["Rishika Kondaveeti", "Rishika Kondaveeti"]


def test_tech_forecast_bare_dash_lead_se_resets_instead_of_filling_a_real_name():
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
         "Opportunity Name": "Alpha", "Close Date": "5/4/2026", "Amount (converted)": "1,000",
         "Presales Stage": "4 - Validate Solution"},
        {"Lead Sales Engineer": "-", "Deal Forecast Status": "Pipeline (2)",
         "Opportunity Name": "Unclaimed One", "Close Date": "5/5/2026",
         "Amount (converted)": "2,000", "Presales Stage": ""},
        {"Opportunity Name": "Unclaimed Two", "Close Date": "5/6/2026",
         "Amount (converted)": "3,000", "Presales Stage": ""},
    )
    assert rows[1]["lead_se_name"] == ""
    assert rows[2]["lead_se_name"] == ""
    assert rows[1]["forecast_status"] == "Pipeline"


def test_tech_forecast_dash_group_also_resets_the_forecast_status_cascade():
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Forecasted Risk (1)",
         "Opportunity Name": "Alpha", "Close Date": "5/4/2026", "Amount (converted)": "1,000",
         "Presales Stage": "4 - Validate Solution"},
        {"Lead Sales Engineer": "-", "Deal Forecast Status": "",
         "Opportunity Name": "Unclaimed One", "Close Date": "5/5/2026",
         "Amount (converted)": "2,000", "Presales Stage": ""},
    )
    assert rows[1]["lead_se_name"] == ""
    assert rows[1]["forecast_status"] == ""


def test_tech_forecast_tags_another_orgs_deals_instead_of_dropping_them():
    rows = tf_rows(
        {"Lead Sales Engineer": "Luis Santos (1)", "Deal Forecast Status": "Strong (1)",
         "Opportunity Name": "Other Org Deal", "Close Date": "5/4/2026",
         "Amount (converted)": "1,000", "Presales Stage": "4 - Validate Solution",
         "Opportunity Owner: Manager": "Greg Rainbird"},
        {"Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
         "Opportunity Name": "Our Deal", "Close Date": "5/5/2026",
         "Amount (converted)": "2,000", "Presales Stage": "4 - Validate Solution",
         "Opportunity Owner: Manager": "Our Manager"},
    )
    assert len(rows) == 2, "cross-org rows stay visible, they are tagged not dropped"
    assert (rows[0]["product"], rows[0]["segment"]) == ("Auth0", "Enterprise/Strategic")
    assert (rows[1]["product"], rows[1]["segment"]) == (None, None)


def test_tech_forecast_org_tag_matching_is_case_and_whitespace_insensitive():
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
         "Opportunity Name": "Other Org Deal", "Close Date": "5/4/2026",
         "Amount (converted)": "1,000", "Presales Stage": "",
         "Opportunity Owner: Manager": "  GREG RAINBIRD  "},
    )
    assert rows[0]["product"] == "Auth0"


def test_tech_forecast_rows_without_an_opportunity_name_are_dropped():
    rows = tf_rows(
        {"Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
         "Opportunity Name": "Alpha", "Close Date": "5/4/2026", "Amount (converted)": "1,000",
         "Presales Stage": ""},
        {"Lead Sales Engineer": "", "Deal Forecast Status": "", "Opportunity Name": ""},
    )
    assert len(rows) == 1


def test_tech_forecast_empty_grid_normalizes_to_no_rows():
    assert tech_forecast_sync._normalize_values([]) == []


def test_tech_forecast_header_mismatch_raises_naming_the_missing_column():
    bad_header = [h for h in TF_HEADER if h != "Presales Stage"]
    with pytest.raises(ValueError) as excinfo:
        tech_forecast_sync._normalize_values(grid(bad_header, {"Opportunity Name": "Alpha"}))
    assert "Presales Stage" in str(excinfo.value)
