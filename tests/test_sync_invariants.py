"""Sync-time invariants: what a re-sync is allowed to change, and what it must
never touch.

Each test runs a real sync against its own temp SQLite file. The rules under
test all correspond to bugs this repo has actually shipped: manual SE
assignments wiped by a re-key, `notes_stale` that could never fire, a
truncated fetch deleting rows, a shifted header reporting a cheerful
`{"synced": 0}`.
"""

import pytest

import closed_deals_sync
import sheets_sync
import tech_forecast_sync
from conftest import (CLOSED_HEADER, DEALS_HEADER, TF_HEADER, add_rep, grid)


# ── helpers ──────────────────────────────────────────────────────────────
def tf_sync(db, *rows, allow_shrink=False):
    return tech_forecast_sync.sync_tech_forecast_from_values(
        db, grid(TF_HEADER, *rows), allow_shrink
    )


def deals_sync(db, *rows, allow_shrink=False):
    return sheets_sync.sync_deals_from_values(db, grid(DEALS_HEADER, *rows), allow_shrink)


def closed_sync(db, *rows, allow_shrink=False):
    return closed_deals_sync.sync_closed_deals_from_values(
        db, grid(CLOSED_HEADER, *rows), allow_shrink
    )


def tf_row(**overrides):
    row = {
        "Lead Sales Engineer": "Amara Osei (1)",
        "Deal Forecast Status": "Strong (1)",
        "Opportunity Name": "Granite Peak Zero Trust",
        "Close Date": "5/4/2026",
        "Amount (converted)": "300,000",
        "Presales Stage": "4 - Validate Solution",
        "Pre-Sales Next Steps": "Security review booked for next week",
    }
    row.update(overrides)
    return row


def deal_row(**overrides):
    row = {
        "Lead Sales Engineer": "Amara Osei (1)",
        "Stage": "3 - Technical Scoping (1)",
        "Opportunity Name": "Granite Peak Zero Trust",
        "Close Date": "5/4/2026",
        "Amount": "$300,000",
    }
    row.update(overrides)
    return row


def closed_row(**overrides):
    row = {
        "Team Member Name": "Amara Osei (USD 300,000.00)",
        "Opportunity Name": "Granite Peak Zero Trust",
        "Amount (converted)": "USD 300,000.00",
        "Close Date": "5/4/2026",
        "Stage": "10 - Closed/Won",
        "Presales Stage": "6 - Technical Win",
    }
    row.update(overrides)
    return row


def fetch_one(db, sql, params=()):
    with db.conn() as c:
        row = c.execute(sql, params).fetchone()
    return dict(row) if row else None


def count(db, table):
    with db.conn() as c:
        return c.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def set_tf_overrides(db, rep_id, note="Covering while Amara is on PTO"):
    with db.conn() as c:
        c.execute(
            "UPDATE tech_forecast_deals SET assigned_se_rep_id = ?, backup_se_rep_id = ?, "
            "backup_note = ?, backup_assigned_at = '2026-09-01T00:00:00'",
            (rep_id, rep_id, note),
        )


# ═══════════════════════════════════════════════════════════════════════
# Manual overrides survive a re-key
# ═══════════════════════════════════════════════════════════════════════
def test_manual_overrides_survive_a_close_date_slip_that_rekeys_the_row(db):
    """No Opportunity ID in the sheet, so the key is name+close-date. A slipped
    date re-keys the row; the override must ride across to the new key."""
    rep = add_rep(db, "Bo Nakamura")
    tf_sync(db, tf_row())
    set_tf_overrides(db, rep)

    result = tf_sync(db, tf_row(**{"Close Date": "7/15/2026"}))

    assert result["overrides_carried"] == 1
    assert count(db, "tech_forecast_deals") == 1
    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert row["close_date"] == "2026-07-15"
    assert row["assigned_se_rep_id"] == rep
    assert row["backup_se_rep_id"] == rep
    assert row["backup_note"] == "Covering while Amara is on PTO"


def test_manual_overrides_survive_a_stage_advance_that_rekeys_a_deal_row(db):
    """`deals` keys on lead|stage|name when the sheet carries no Opportunity
    ID, so advancing a stage re-keys the row."""
    rep = add_rep(db, "Bo Nakamura")
    deals_sync(db, deal_row())
    with db.conn() as c:
        c.execute(
            "UPDATE deals SET backup_se_rep_id = ?, backup_note = 'covering', "
            "backup_assigned_at = '2026-09-01T00:00:00'",
            (rep,),
        )

    result = deals_sync(db, deal_row(**{"Stage": "5 - Final Due Diligence (1)"}))

    assert result["overrides_carried"] == 1
    assert count(db, "deals") == 1
    row = fetch_one(db, "SELECT * FROM deals")
    assert row["stage"] == "5 - Final Due Diligence"
    assert row["backup_se_rep_id"] == rep
    assert row["backup_note"] == "covering"


def test_a_date_reformat_alone_does_not_rekey_or_count_as_a_change(db):
    """5/4/2026 -> 05/04/2026 is the same day. Keys are built from the PARSED
    date, so nothing is deleted, reinserted, or reported as synced."""
    rep = add_rep(db, "Bo Nakamura")
    tf_sync(db, tf_row())
    set_tf_overrides(db, rep)
    key_before = fetch_one(db, "SELECT sheet_key FROM tech_forecast_deals")["sheet_key"]

    result = tf_sync(db, tf_row(**{"Close Date": "05/04/2026"}))

    assert result["synced"] == 0
    assert result["unchanged"] == 1
    assert result["deleted"] == 0
    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert row["sheet_key"] == key_before
    assert row["assigned_se_rep_id"] == rep


def test_a_date_reformat_is_not_a_change_for_the_closed_deals_sync_either(db):
    closed_sync(db, closed_row())
    result = closed_sync(db, closed_row(**{"Close Date": "05/04/2026"}))
    assert (result["synced"], result["unchanged"], result["deleted"]) == (0, 1, 0)


def test_an_opportunity_id_keeps_the_key_stable_through_slip_and_stage_change(db):
    """With an ID in the sheet nothing re-keys at all — the carry-forward is
    only the second line of defence."""
    rep = add_rep(db, "Bo Nakamura")
    tf_sync(db, tf_row(**{"Opportunity ID": "006SYNTH001"}))
    set_tf_overrides(db, rep)

    result = tf_sync(db, tf_row(**{
        "Opportunity ID": "006SYNTH001",
        "Close Date": "9/30/2026",
        "Presales Stage": "5 - Final Due Diligence",
        "Opportunity Name": "Granite Peak Zero Trust (renamed)",
    }))

    assert result["deleted"] == 0
    assert result["overrides_carried"] == 0
    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert row["sheet_key"] == "oid:006SYNTH001"
    assert row["opportunity_name"] == "Granite Peak Zero Trust (renamed)"
    assert row["assigned_se_rep_id"] == rep
    assert row["backup_note"] == "Covering while Amara is on PTO"


def test_a_rename_carries_overrides_when_the_opportunity_id_matches(db):
    rep = add_rep(db, "Bo Nakamura")
    # Stored without an ID (old sheet layout), re-synced with one: the key
    # changes shape entirely, and the ID match is what saves the override.
    tf_sync(db, tf_row())
    set_tf_overrides(db, rep)
    result = tf_sync(db, tf_row(**{"Opportunity ID": "006SYNTH002"}))
    assert result["overrides_carried"] == 1
    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert row["sheet_key"] == "oid:006SYNTH002"
    assert row["assigned_se_rep_id"] == rep


# ═══════════════════════════════════════════════════════════════════════
# notes_stale
# ═══════════════════════════════════════════════════════════════════════
def test_notes_stale_fires_for_a_frozen_deal_whose_next_steps_never_change(db):
    """The row nothing else changed about is exactly the row this flag exists
    for, so staleness must be evaluated on the fingerprint-unchanged path too."""
    tf_sync(db, tf_row())
    assert fetch_one(db, "SELECT notes_stale FROM tech_forecast_deals")["notes_stale"] == 0

    result = tf_sync(db, tf_row())

    assert result["unchanged"] == 1, "nothing else about the row changed"
    assert fetch_one(db, "SELECT notes_stale FROM tech_forecast_deals")["notes_stale"] == 1


def test_notes_stale_stays_set_across_several_untouched_syncs(db):
    tf_sync(db, tf_row())
    for _ in range(3):
        tf_sync(db, tf_row())
    assert fetch_one(db, "SELECT notes_stale FROM tech_forecast_deals")["notes_stale"] == 1


def test_notes_stale_clears_as_soon_as_the_next_steps_text_changes(db):
    tf_sync(db, tf_row())
    tf_sync(db, tf_row())
    assert fetch_one(db, "SELECT notes_stale FROM tech_forecast_deals")["notes_stale"] == 1

    tf_sync(db, tf_row(**{"Pre-Sales Next Steps": "RK Sep-15-2026 : POC kicked off"}))

    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert row["notes_stale"] == 0
    assert row["pre_sales_next_steps"] == "RK Sep-15-2026 : POC kicked off"


def test_a_change_elsewhere_on_the_row_still_leaves_unchanged_next_steps_stale(db):
    tf_sync(db, tf_row())
    tf_sync(db, tf_row(**{"Amount (converted)": "400,000"}))
    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert row["amount"] == 400000.0
    assert row["notes_stale"] == 1


def test_org_tags_are_reapplied_to_rows_that_did_not_otherwise_change(db):
    """product/segment are re-derived every sync and sit outside the
    fingerprint, so the unchanged path has to apply them too."""
    tf_sync(db, tf_row())
    result = tf_sync(db, tf_row(**{"Opportunity Owner: Manager": "Greg Rainbird"}))
    row = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    assert (row["product"], row["segment"]) == ("Auth0", "Enterprise/Strategic")
    assert result["synced"] == 1  # the manager column is part of the fingerprint


# ═══════════════════════════════════════════════════════════════════════
# Truncated-fetch (shrink) guard
# ═══════════════════════════════════════════════════════════════════════
def _many_tf_rows(n, start=1):
    return [tf_row(**{"Opportunity ID": f"006BULK{i:03d}", "Opportunity Name": f"Bulk Deal {i:03d}"})
            for i in range(start, start + n)]


def test_shrink_guard_aborts_a_truncated_payload_before_deleting_anything(db):
    tf_sync(db, *_many_tf_rows(10))
    assert count(db, "tech_forecast_deals") == 10

    with pytest.raises(RuntimeError) as excinfo:
        tf_sync(db, *_many_tf_rows(5))

    assert "truncated" in str(excinfo.value).lower()
    assert count(db, "tech_forecast_deals") == 10, "nothing may be deleted before the guard fires"


def test_allow_shrink_overrides_the_guard_for_a_sheet_that_really_shrank(db):
    tf_sync(db, *_many_tf_rows(10))
    result = tf_sync(db, *_many_tf_rows(5), allow_shrink=True)
    assert result["deleted"] == 5
    assert count(db, "tech_forecast_deals") == 5


def test_shrink_guard_protects_the_deals_sync_too(db):
    rows = [deal_row(**{"Opportunity ID": f"006D{i:03d}", "Opportunity Name": f"Deal {i:03d}"})
            for i in range(10)]
    deals_sync(db, *rows)
    with pytest.raises(RuntimeError):
        deals_sync(db, *rows[:4])
    assert count(db, "deals") == 10


def test_shrink_guard_protects_the_closed_deals_sync_too(db):
    rows = [closed_row(**{"Opportunity ID": f"006C{i:03d}", "Opportunity Name": f"Closed {i:03d}"})
            for i in range(10)]
    closed_sync(db, *rows)
    with pytest.raises(RuntimeError):
        closed_sync(db, *rows[:4])
    assert count(db, "closed_deals") == 10


def test_a_modest_shrink_inside_the_retention_ratio_is_allowed(db):
    tf_sync(db, *_many_tf_rows(10))
    result = tf_sync(db, *_many_tf_rows(9))
    assert result["deleted"] == 1


def test_the_guard_does_not_block_the_very_first_sync_into_an_empty_table(db):
    result = tf_sync(db, tf_row())
    assert result["synced"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Header validation
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sync,header,missing", [
    (tech_forecast_sync.sync_tech_forecast_from_values, TF_HEADER, "Close Date"),
    (sheets_sync.sync_deals_from_values, DEALS_HEADER, "Amount"),
    (closed_deals_sync.sync_closed_deals_from_values, CLOSED_HEADER, "Opportunity Name"),
])
def test_a_shifted_header_raises_instead_of_silently_syncing_zero_rows(db, sync, header, missing):
    bad_header = [h for h in header if h != missing]
    with pytest.raises(ValueError) as excinfo:
        sync(db, grid(bad_header, {"Opportunity Name": "Alpha"}))
    assert missing in str(excinfo.value)


def test_a_failed_header_check_writes_nothing_at_all(db):
    tf_sync(db, tf_row())
    before = fetch_one(db, "SELECT * FROM tech_forecast_deals")
    with pytest.raises(ValueError):
        tech_forecast_sync.sync_tech_forecast_from_values(
            db, grid([h for h in TF_HEADER if h != "Close Date"], tf_row())
        )
    assert fetch_one(db, "SELECT * FROM tech_forecast_deals") == before


# ═══════════════════════════════════════════════════════════════════════
# Rep discovery / amount accounting
# ═══════════════════════════════════════════════════════════════════════
def test_a_rep_discovered_in_the_sheet_is_inserted_inactive(db):
    """A name straight off the sheet (or a typo) must never become a current
    direct report by itself — CLAUDE.md's departed-rep rule."""
    deals_sync(db, deal_row(**{"Lead Sales Engineer": "Newly Typed Name (1)"}))
    rep = fetch_one(db, "SELECT * FROM se_reps WHERE name = 'Newly Typed Name'")
    assert rep is not None
    assert rep["active"] == 0


def test_an_existing_active_rep_is_not_deactivated_by_a_sync(db):
    add_rep(db, "Amara Osei", active=1)
    deals_sync(db, deal_row())
    assert fetch_one(db, "SELECT * FROM se_reps WHERE name = 'Amara Osei'")["active"] == 1


def test_unassigned_rows_do_not_create_a_placeholder_rep(db):
    deals_sync(db, deal_row(**{"Lead Sales Engineer": "-"}))
    assert fetch_one(db, "SELECT * FROM se_reps WHERE name = 'Unassigned'") is None
    assert fetch_one(db, "SELECT * FROM deals")["se_rep_id"] is None


def test_unparseable_amounts_are_reported_rather_than_stored_as_zero(db):
    result = tf_sync(
        db,
        tf_row(**{"Opportunity ID": "006A", "Opportunity Name": "Good", "Amount (converted)": "1,000"}),
        tf_row(**{"Opportunity ID": "006B", "Opportunity Name": "Garbage", "Amount (converted)": "TBD"}),
        tf_row(**{"Opportunity ID": "006C", "Opportunity Name": "Blank", "Amount (converted)": ""}),
    )
    assert result["unparsed_amounts"] == 1
    assert fetch_one(db, "SELECT amount FROM tech_forecast_deals WHERE opportunity_name = 'Garbage'")["amount"] is None


def test_accounting_negative_amounts_reach_the_database_as_negative(db):
    closed_sync(db, closed_row(**{"Amount (converted)": "(USD 1,234.00)"}))
    assert fetch_one(db, "SELECT amount FROM closed_deals")["amount"] == -1234.0


# ═══════════════════════════════════════════════════════════════════════
# Snapshot capture + sync bookkeeping
# ═══════════════════════════════════════════════════════════════════════
def test_a_tech_forecast_sync_captures_a_snapshot_and_stamps_the_sync_time(db):
    tf_sync(db, tf_row())
    assert count(db, "tech_forecast_snapshots") == 1
    assert db.get_setting("tech_forecast_last_synced_at")


def test_resyncing_the_same_day_upserts_one_snapshot_rather_than_two(db):
    tf_sync(db, tf_row(**{"Opportunity ID": "006A", "Opportunity Name": "A"}))
    tf_sync(db, tf_row(**{"Opportunity ID": "006A", "Opportunity Name": "A"}),
            tf_row(**{"Opportunity ID": "006B", "Opportunity Name": "B"}))
    assert count(db, "tech_forecast_snapshots") == 1


def test_deals_sync_stamps_its_own_last_synced_setting(db):
    deals_sync(db, deal_row())
    assert db.get_setting("deals_last_synced_at")


def test_rows_absent_from_the_payload_are_deleted(db):
    tf_sync(db, *_many_tf_rows(10))
    result = tf_sync(db, *_many_tf_rows(9))
    assert result["deleted"] == 1
    assert count(db, "tech_forecast_deals") == 9


# ── notes_last_changed_at ────────────────────────────────────────────────────
# notes_stale only says "unchanged since the previous sync". The timestamp is
# what lets the UI say HOW long, which is what decides whether a deal gets
# raised on the call.

def _tf_row(next_steps):
    return {
        "Lead Sales Engineer": "Amara Osei",
        "Deal Forecast Status": "Commit",
        "Opportunity Name": "Acme",
        "Opportunity ID": "006Z",
        "Close Date": "2026-10-31",
        "Amount (converted)": "$50,000",
        "Presales Stage": "3 - Validation",
        "Pre-Sales Next Steps": next_steps,
    }


def _notes_state(database):
    with database.conn() as c:
        row = c.execute(
            "SELECT notes_stale, notes_last_changed_at FROM tech_forecast_deals"
        ).fetchone()
    return row["notes_stale"], row["notes_last_changed_at"]


def test_notes_timestamp_holds_still_while_the_text_does(db):
    tf_sync(db, _tf_row("RK Sep-01 : demo booked"))
    _, first = _notes_state(db)
    tf_sync(db, _tf_row("RK Sep-01 : demo booked"))
    stale, second = _notes_state(db)
    assert stale == 1
    assert second == first, "the stamp moved even though the notes did not"


def test_notes_timestamp_advances_when_the_text_moves(db):
    tf_sync(db, _tf_row("RK Sep-01 : demo booked"))
    _, first = _notes_state(db)
    tf_sync(db, _tf_row("RK Sep-15 : POC started"))
    stale, second = _notes_state(db)
    assert stale == 0
    assert second > first


def test_rows_predating_the_column_keep_a_null_stamp(db):
    """We don't know when they last moved; claiming they just did would show a
    month-old deal as fresh."""
    tf_sync(db, _tf_row("RK Sep-01 : demo booked"))
    with db.conn() as c:
        c.execute("UPDATE tech_forecast_deals SET notes_last_changed_at = NULL")
    tf_sync(db, _tf_row("RK Sep-01 : demo booked"))
    stale, stamp = _notes_state(db)
    assert stale == 1
    assert stamp is None
