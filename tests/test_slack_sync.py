"""The MCP-assisted Slack load path (`sync_slack_notes_from_matches`).

The credential path isn't exercised — it needs a live user token — but the
loader underneath it is the part that writes rows, and it has two documented
traps: re-running a sync must not report a whole lookback window as new, and
Slack's `ts` is a UTC epoch that must not be rendered in local time.
"""

from datetime import datetime, timezone

import slack_sync
from conftest import add_rep

TS = "1757000000.000100"


def nested_match(**overrides):
    match = {
        "ts": TS,
        "text": "Wrapped the Northwind workshop.",
        "permalink": "https://example.slack.com/archives/C01/p1757000000000100",
        "channel": {"id": "C01", "name": "se-canada"},
    }
    match.update(overrides)
    return match


def flat_match(**overrides):
    match = {
        "ts": TS,
        "text": "Wrapped the Northwind workshop.",
        "permalink": "https://example.slack.com/archives/C01/p1757000000000100",
        "channel_id": "C01",
        "channel_name": "se-canada",
    }
    match.update(overrides)
    return match


def notes(db):
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM slack_notes ORDER BY id")]


def test_slack_timestamps_are_stored_in_utc_not_the_hosts_local_time():
    """Two machines importing the same message must agree on posted_at."""
    expected = datetime.fromtimestamp(float(TS), tz=timezone.utc).isoformat()
    assert slack_sync._ts_to_iso(TS) == expected
    assert slack_sync._ts_to_iso(TS).endswith("+00:00")


def test_a_first_load_reports_every_match_as_new(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    result = slack_sync.sync_slack_notes_from_matches(db, rep, [nested_match()])
    assert result == {"synced": 1, "new": 1, "updated": 0, "unchanged": 0}
    stored = notes(db)[0]
    assert stored["channel_name"] == "se-canada"
    assert stored["se_rep_id"] == rep


def test_rerunning_the_same_sync_reports_unchanged_not_a_second_window_of_activity(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    slack_sync.sync_slack_notes_from_matches(db, rep, [nested_match()])

    result = slack_sync.sync_slack_notes_from_matches(db, rep, [nested_match()])

    assert result == {"synced": 0, "new": 0, "updated": 0, "unchanged": 1}
    assert len(notes(db)) == 1, "the upsert is keyed on (rep, ts, channel)"


def test_an_edited_message_is_reported_as_updated_and_overwrites_the_text(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    slack_sync.sync_slack_notes_from_matches(db, rep, [nested_match()])

    result = slack_sync.sync_slack_notes_from_matches(
        db, rep, [nested_match(text="Wrapped the Northwind workshop (edited).")]
    )

    assert result["updated"] == 1
    assert result["synced"] == 1
    assert notes(db)[0]["text"] == "Wrapped the Northwind workshop (edited)."


def test_the_flat_mcp_shape_and_the_raw_search_shape_load_identically(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    slack_sync.sync_slack_notes_from_matches(db, rep, [flat_match()])
    stored = notes(db)[0]
    assert (stored["channel_id"], stored["channel_name"]) == ("C01", "se-canada")

    # The same message arriving in the other shape must not duplicate the row.
    result = slack_sync.sync_slack_notes_from_matches(db, rep, [nested_match()])
    assert result["unchanged"] == 1
    assert len(notes(db)) == 1


def test_posted_at_is_derived_from_the_slack_ts_when_not_supplied(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    slack_sync.sync_slack_notes_from_matches(db, rep, [flat_match()])
    assert notes(db)[0]["posted_at"] == slack_sync._ts_to_iso(TS)


def test_an_explicit_posted_at_wins_over_the_derived_one(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    slack_sync.sync_slack_notes_from_matches(
        db, rep, [flat_match(posted_at="2026-09-10T12:00:00+00:00")]
    )
    assert notes(db)[0]["posted_at"] == "2026-09-10T12:00:00+00:00"


def test_the_same_message_for_two_reps_is_two_distinct_rows(db):
    amara = add_rep(db, "Amara Osei", slack_user_id="U0A")
    bo = add_rep(db, "Bo Nakamura", slack_user_id="U0B")
    slack_sync.sync_slack_notes_from_matches(db, amara, [nested_match()])
    slack_sync.sync_slack_notes_from_matches(db, bo, [nested_match()])
    assert {n["se_rep_id"] for n in notes(db)} == {amara, bo}


def test_loading_an_empty_match_list_writes_nothing(db):
    rep = add_rep(db, "Amara Osei", slack_user_id="U0SYNTH")
    assert slack_sync.sync_slack_notes_from_matches(db, rep, []) == {
        "synced": 0, "new": 0, "updated": 0, "unchanged": 0,
    }
    assert notes(db) == []


def test_slack_notes_surface_on_the_reps_endpoint(api):
    body = api.get(f"/api/reps/{api.rep_ids['amara']}/slack").get_json()
    assert len(body) == 1
    assert body[0]["channel_name"] == "se-canada"
