"""Money/date/group-header parsing shared by the three sheet syncs.

These helpers sit directly in front of every revenue number in the product: a
sign flip, a dropped thousands separator or a group label that keeps its
"(9)" suffix corrupts totals quietly rather than raising.
"""

import pytest

import sheet_parse


# ── Amounts ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("1234", 1234.0),
    ("1,234", 1234.0),
    ("1,099,753.82", 1099753.82),
    (" $ 3,064.52 ", 3064.52),
    ("USD 1,099,753.82", 1099753.82),
    ("$1,234.00", 1234.0),
    ("CAD 500", 500.0),
    (0, 0.0),
    (1234.5, 1234.5),
    ("-500", -500.0),
])
def test_parse_amount_strips_currency_symbols_and_thousands_separators(raw, expected):
    assert sheet_parse.parse_amount(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw,expected", [
    ("(1,234.00)", -1234.0),
    ("($1,234.00)", -1234.0),
    ("(USD 2,500.50)", -2500.50),
    ("(500)", -500.0),
])
def test_accounting_parentheses_parse_as_a_negative_amount(raw, expected):
    """"(1,234.00)" is accounting notation for -1234.00; booking it positive
    flips the sign of every clawback/credit row that reaches a revenue total."""
    assert sheet_parse.parse_amount(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "   ", "\n"])
def test_blank_amount_cell_parses_as_none(raw):
    assert sheet_parse.parse_amount(raw) is None


@pytest.mark.parametrize("raw", ["n/a", "N/A", "TBD", "-", ".", "unknown", "1.2.3", "$--"])
def test_garbage_amount_parses_as_none_rather_than_zero(raw):
    assert sheet_parse.parse_amount(raw) is None


def test_unparseable_amount_is_counted_not_silently_dropped():
    """A dropped amount is indistinguishable from a blank one once stored, so
    the syncs count them via amount_unparsed and surface the count."""
    assert sheet_parse.amount_unparsed("n/a", sheet_parse.parse_amount("n/a")) is True
    assert sheet_parse.amount_unparsed("TBD", None) is True
    # Genuinely blank cells are not "unparsed" — nothing was lost.
    assert sheet_parse.amount_unparsed("", None) is False
    assert sheet_parse.amount_unparsed(None, None) is False
    assert sheet_parse.amount_unparsed("   ", None) is False
    # A parsed value is never flagged, including a legitimate zero.
    assert sheet_parse.amount_unparsed("0", 0.0) is False
    assert sheet_parse.amount_unparsed("1,234", 1234.0) is False


# ── Dates ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("05/04/2026", "2026-05-04"),
    ("5/4/2026", "2026-05-04"),      # same day, merely reformatted
    ("2026-05-04", "2026-05-04"),
    ("5/4/26", "2026-05-04"),
    ("12/31/2026", "2026-12-31"),
    ("  2026-05-04  ", "2026-05-04"),
])
def test_parse_date_normalizes_every_export_format_to_iso(raw, expected):
    assert sheet_parse.parse_date(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "Sept 4 2026", "2026/05/04", "04-05-2026", "garbage", "2026-13-45"])
def test_parse_date_returns_none_for_blank_or_unparseable_cells(bad):
    assert sheet_parse.parse_date(bad) is None


def test_reformatted_date_cells_parse_to_an_identical_value():
    """The whole point of keying on the PARSED date: a cosmetic reformat must
    not look like a different deal."""
    assert sheet_parse.parse_date("5/4/2026") == sheet_parse.parse_date("05/04/2026")


# ── Group-header cells ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("Nic Da Silva (9)", "Nic Da Silva"),                    # row-count suffix
    ("2 - Discovery (3)", "2 - Discovery"),
    ("Strong (18)", "Strong"),
    ("Sean Keleher (USD 1,099,753.82)", "Sean Keleher"),     # running-total suffix
    ("Rishika Kondaveeti (USD 2,538,735.02)", "Rishika Kondaveeti"),
    ("  Plain Name  ", "Plain Name"),
])
def test_group_header_suffixes_are_stripped_for_both_sheet_forms(raw, expected):
    assert sheet_parse.strip_group_label(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "Subtotal", "subtotal", "Total", "GRAND TOTAL", "Subtotal (4)"])
def test_marker_and_blank_cells_return_none_so_callers_inherit_rather_than_reset(raw):
    """None means "row-shape noise": keep the current fill and keep buffering.
    Collapsing a marker to "" would orphan deal rows still waiting on a
    late-arriving group name (the NOVA Chemicals / MacEwan bug)."""
    assert sheet_parse.strip_group_label(raw) is None


def test_bare_dash_is_a_real_group_boundary_not_a_name():
    assert sheet_parse.strip_group_label("-") == ""
    assert sheet_parse.strip_group_label("-", unassigned="Unassigned") == "Unassigned"


@pytest.mark.parametrize("name", ["TotalEnergies", "Total Rewards Platform", "Subtotal Systems Inc"])
def test_account_named_like_a_marker_is_not_treated_as_one(name):
    """Exact match on the stripped cell, never a substring scan — "TotalEnergies"
    is a real customer."""
    assert sheet_parse.is_marker_cell(name) is False
    assert sheet_parse.strip_group_label(name) == name


@pytest.mark.parametrize("cell", ["Subtotal", "Total", "grand total", "Total (12)", "Total (USD 5,000.00)"])
def test_is_marker_cell_matches_markers_with_or_without_a_suffix(cell):
    assert sheet_parse.is_marker_cell(cell) is True


# ── Header mapping ───────────────────────────────────────────────────────
_HEADER_MAP = {"Opportunity Name": "opportunity_name", "Close Date": "close_date", "Amount": "amount"}
_REQUIRED = ("Opportunity Name", "Close Date", "Amount")


def test_map_header_resolves_a_matching_layout():
    keys = sheet_parse.map_header(
        ["Opportunity Name", "Stray", "Close Date", "Amount"],
        _HEADER_MAP, _REQUIRED, label="test sync",
    )
    assert keys == ["opportunity_name", None, "close_date", "amount"]


def test_missing_required_header_raises_naming_the_column_not_a_silent_zero_row_sync():
    with pytest.raises(ValueError) as excinfo:
        sheet_parse.map_header(
            ["Opportunity Name", "Amount"], _HEADER_MAP, _REQUIRED, label="test sync"
        )
    message = str(excinfo.value)
    assert "Close Date" in message
    assert "test sync" in message


def test_completely_shifted_header_row_raises_instead_of_reporting_zero_rows():
    with pytest.raises(ValueError) as excinfo:
        sheet_parse.map_header(["", "", ""], _HEADER_MAP, _REQUIRED, label="test sync")
    for column in _REQUIRED:
        assert column in str(excinfo.value)


# ── Row identity ─────────────────────────────────────────────────────────
def test_sheet_key_prefers_the_opportunity_id():
    assert sheet_parse.build_sheet_key("006ABC", "Name", "2026-05-04") == "oid:006ABC"
    assert sheet_parse.build_sheet_key("  006ABC  ", "Name") == "oid:006ABC"


def test_sheet_key_falls_back_to_a_composite_of_the_parsed_parts():
    assert sheet_parse.build_sheet_key("", "Acme", "2026-05-04") == "Acme|2026-05-04"
    assert sheet_parse.build_sheet_key(None, "Acme", None) == "Acme|"


def test_id_keyed_and_composite_keyed_rows_cannot_collide():
    assert sheet_parse.build_sheet_key("Acme", "x") != sheet_parse.build_sheet_key("", "Acme", "x")


def test_row_fingerprint_is_stable_and_change_sensitive():
    row = {"a": "1", "b": "2"}
    assert sheet_parse.row_fingerprint(row, ("a", "b")) == sheet_parse.row_fingerprint(dict(row), ("a", "b"))
    assert sheet_parse.row_fingerprint(row, ("a", "b")) != sheet_parse.row_fingerprint({"a": "1", "b": "3"}, ("a", "b"))
    # None and "" are the same absent value as far as the hash is concerned.
    assert sheet_parse.row_fingerprint({"a": None}, ("a",)) == sheet_parse.row_fingerprint({"a": ""}, ("a",))


def test_rekeyed_rows_match_on_opportunity_id_first():
    departing = {"old": {"opportunity_id": "006X", "opportunity_name": "Renamed Away"}}
    incoming = {"new": {"opportunity_id": "006X", "opportunity_name": "Renamed To"}}
    assert sheet_parse.match_rekeyed_rows(departing, incoming) == {"old": "new"}


def test_rekeyed_rows_fall_back_to_a_case_insensitive_unique_name():
    departing = {"old": {"opportunity_id": "", "opportunity_name": "Acme Rollout"}}
    incoming = {"new": {"opportunity_id": "", "opportunity_name": "ACME ROLLOUT"}}
    assert sheet_parse.match_rekeyed_rows(departing, incoming) == {"old": "new"}


def test_ambiguous_duplicate_names_are_skipped_rather_than_guessed():
    """Two deals sharing a name must never swap manual overrides."""
    departing = {
        "old1": {"opportunity_id": "", "opportunity_name": "Acme Rollout"},
        "old2": {"opportunity_id": "", "opportunity_name": "Acme Rollout"},
    }
    incoming = {"new": {"opportunity_id": "", "opportunity_name": "Acme Rollout"}}
    assert sheet_parse.match_rekeyed_rows(departing, incoming) == {}


# ── Write-side guards ────────────────────────────────────────────────────
def test_shrink_guard_refuses_a_payload_far_below_what_is_stored():
    with pytest.raises(RuntimeError) as excinfo:
        sheet_parse.guard_row_shrink("test sync", stored_count=100, incoming_count=40)
    assert "test sync" in str(excinfo.value)


def test_shrink_guard_allows_a_payload_inside_the_retention_ratio():
    sheet_parse.guard_row_shrink("test sync", stored_count=100, incoming_count=85)
    sheet_parse.guard_row_shrink("test sync", stored_count=100, incoming_count=120)


def test_shrink_guard_is_waived_explicitly_or_on_an_empty_table():
    sheet_parse.guard_row_shrink("test sync", 100, 1, allow_shrink=True)
    sheet_parse.guard_row_shrink("test sync", 0, 0)


def test_chunked_never_exceeds_the_sqlite_host_parameter_limit():
    chunks = list(sheet_parse.chunked(range(1000)))
    assert sum(len(chunk) for chunk in chunks) == 1000
    assert max(len(chunk) for chunk in chunks) <= 999
