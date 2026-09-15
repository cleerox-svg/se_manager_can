"""Okta's fiscal year starts Feb 1 and is named by its START year:
FY26 = Feb 2026 .. Jan 2027. Every boundary below is spelled out as a literal
because this math feeds five endpoints and an off-by-one month silently
reassigns revenue to the wrong quarter instead of raising.
"""

import pytest

import tech_forecast_report as report


@pytest.mark.parametrize("iso_date,expected", [
    ("2026-02-01", "FY26-Q1"),   # first day of FY26
    ("2026-04-30", "FY26-Q1"),   # last day of Q1
    ("2026-05-01", "FY26-Q2"),   # first day of Q2
    ("2026-08-01", "FY26-Q3"),
    ("2026-11-01", "FY26-Q4"),
    ("2027-01-15", "FY26-Q4"),   # January still belongs to the prior FY
    ("2027-01-31", "FY26-Q4"),   # last day of FY26
    ("2027-02-01", "FY27-Q1"),   # rolls to the next FY
    ("2026-01-31", "FY25-Q4"),   # day before FY26 starts
])
def test_fiscal_quarter_maps_calendar_date_to_okta_fiscal_quarter(iso_date, expected):
    assert report.fiscal_quarter(iso_date) == expected


def test_fiscal_quarter_accepts_a_full_iso_timestamp():
    assert report.fiscal_quarter("2026-09-15T13:45:00") == "FY26-Q3"


@pytest.mark.parametrize("bad", [None, "", "   ", "9/15/2026", "not-a-date", "2026-13-01", 20260915, [], {}])
def test_fiscal_quarter_returns_none_for_bad_input_instead_of_raising(bad):
    assert report.fiscal_quarter(bad) is None


@pytest.mark.parametrize("label,expected", [
    ("FY26-Q1", (26, 1)),
    ("FY26-Q4", (26, 4)),
    ("FY27-Q1", (27, 1)),
])
def test_fiscal_quarter_sort_key_parses_a_well_formed_label(label, expected):
    assert report.fiscal_quarter_sort_key(label) == expected


@pytest.mark.parametrize("bad", [None, "", "FY26", "FY26-Q0", "FY26-Q5", "FY26-Q10", "garbage"])
def test_fiscal_quarter_sort_key_returns_unknown_sentinel_for_bad_label(bad):
    assert report.fiscal_quarter_sort_key(bad) == (-1, -1)


def test_fiscal_quarter_sort_key_orders_quarters_chronologically():
    labels = ["FY27-Q1", "FY25-Q4", "FY26-Q4", "FY26-Q1"]
    assert sorted(labels, key=report.fiscal_quarter_sort_key) == [
        "FY25-Q4", "FY26-Q1", "FY26-Q4", "FY27-Q1",
    ]


def test_unknown_quarter_sort_key_never_formats_as_a_fake_label():
    assert report.quarter_label((-1, -1)) == report.UNDATED_QUARTER_LABEL
    assert report.quarter_label(report.fiscal_quarter_sort_key("nonsense")) == "Undated"
    assert report.quarter_label((26, 3)) == "FY26-Q3"


@pytest.mark.parametrize("key,n,expected", [
    ((26, 3), 1, (26, 4)),
    ((26, 4), 1, (27, 1)),      # wraps forward across the FY boundary
    ((27, 1), -1, (26, 4)),     # wraps backward across the FY boundary
    ((26, 1), -1, (25, 4)),
    ((26, 1), 4, (27, 1)),      # a full year forward
    ((26, 1), -4, (25, 1)),     # a full year backward
    ((26, 2), 0, (26, 2)),
    ((26, 4), 7, (28, 3)),      # multi-year wrap
])
def test_offset_quarter_key_wraps_year_boundaries_in_both_directions(key, n, expected):
    assert report.offset_quarter_key(key, n) == expected


def test_offset_quarter_key_leaves_the_unknown_sentinel_unshifted():
    assert report.offset_quarter_key((-1, -1), 1) == (-1, -1)
    assert report.offset_quarter_key((-1, -1), -3) == (-1, -1)


def test_private_offset_alias_is_the_public_helper():
    # app.py still calls report._offset_quarter_key; it must not drift.
    assert report._offset_quarter_key is report.offset_quarter_key


def test_next_fiscal_quarter_label_wraps_the_fiscal_year():
    assert report.next_fiscal_quarter_label("FY26-Q3") == "FY26-Q4"
    assert report.next_fiscal_quarter_label("FY26-Q4") == "FY27-Q1"


def test_next_fiscal_quarter_label_defaults_to_the_quarter_after_today(frozen_quarter):
    frozen_quarter("FY26-Q4")
    assert report.next_fiscal_quarter_label() == "FY27-Q1"


def test_next_fiscal_quarter_label_of_garbage_is_undated_not_a_crash():
    assert report.next_fiscal_quarter_label("garbage") == "Undated"


@pytest.mark.parametrize("target,expected", [
    ("2026-09-15", "current"),   # inside FY26-Q3
    ("2026-08-01", "current"),   # first day of FY26-Q3
    ("2026-10-31", "current"),   # last day of FY26-Q3
    ("2026-11-01", "next"),      # first day of FY26-Q4
    ("2027-02-10", "later"),
    ("2026-03-10", "overdue"),   # FY26-Q1 already closed
    ("2025-12-01", "overdue"),
])
def test_quarter_bucket_detailed_labels_target_date_against_todays_quarter(
    frozen_quarter, target, expected
):
    frozen_quarter("FY26-Q3")
    assert report.quarter_bucket_detailed(target) == expected


@pytest.mark.parametrize("bad", [None, "", "9/15/2026", "garbage"])
def test_quarter_bucket_detailed_returns_none_for_bad_or_missing_date(frozen_quarter, bad):
    assert report.quarter_bucket_detailed(bad) is None


def test_quarter_bucket_collapses_overdue_into_later(frozen_quarter):
    frozen_quarter("FY26-Q3")
    assert report.quarter_bucket("2026-03-10") == "later"
    assert report.quarter_bucket("2026-09-15") == "current"
    assert report.quarter_bucket("2026-11-01") == "next"
    assert report.quarter_bucket("2027-02-10") == "later"
    assert report.quarter_bucket(None) is None


def test_quarter_bucket_next_wraps_the_fiscal_year_boundary(frozen_quarter):
    frozen_quarter("FY26-Q4")   # Nov 2026 - Jan 2027
    assert report.quarter_bucket_detailed("2027-03-01") == "next"   # FY27-Q1
    assert report.quarter_bucket_detailed("2027-01-15") == "current"


def test_fiscal_quarter_date_range_is_a_three_month_exclusive_window():
    assert report.fiscal_quarter_date_range((26, 1)) == ("2026-02-01", "2026-05-01")
    assert report.fiscal_quarter_date_range((26, 3)) == ("2026-08-01", "2026-11-01")
    # Q4 spans the calendar-year boundary and ends on Feb 1 of the next year.
    assert report.fiscal_quarter_date_range((26, 4)) == ("2026-11-01", "2027-02-01")


def test_fiscal_quarter_date_range_round_trips_through_fiscal_quarter():
    start, end = report.fiscal_quarter_date_range((26, 4))
    assert report.fiscal_quarter(start) == "FY26-Q4"
    assert report.fiscal_quarter(end) == "FY27-Q1"
