"""The CLI bridge Claude Code uses to load MCP-fetched payloads.

Two contracts worth pinning: a wrong-shaped payload must fail with a readable
reason instead of a traceback from deep inside a sync, and stdout must stay
exactly one line of JSON counts — never row data (CLAUDE.md's context-economy
rule; row data here is real pipeline content).
"""

import json

import pytest

import mcp_ingest
from conftest import DEALS_HEADER, TF_HEADER, add_rep, grid


def write_payload(tmp_path, payload, name="_mcp_payload_test.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def run(monkeypatch, tmp_path, *argv):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ingest.db"))
    monkeypatch.setattr("sys.argv", ["mcp_ingest.py", *argv])
    mcp_ingest.main()


# ── payload validation ───────────────────────────────────────────────────
@pytest.mark.parametrize("payload,expected", [
    ([], "must be a JSON object"),
    ("a string", "must be a JSON object"),
    ({"rows": [[1]]}, "missing the 'values' key"),
    ({"values": "not a grid"}, "list of row lists"),
    ({"values": [["ok"], "not a row"]}, "list of row lists"),
    ({"values": []}, "nothing to sync"),
])
def test_a_wrong_shaped_sheet_payload_fails_with_a_readable_reason(payload, expected):
    with pytest.raises(SystemExit) as excinfo:
        mcp_ingest._validate("deals", payload)
    assert expected in str(excinfo.value)


@pytest.mark.parametrize("payload,expected", [
    ({"matches": []}, "integer 'se_rep_id'"),
    ({"se_rep_id": "5", "matches": []}, "integer 'se_rep_id'"),
    ({"se_rep_id": 5}, "'matches' list"),
])
def test_a_wrong_shaped_slack_payload_names_what_is_missing(payload, expected):
    with pytest.raises(SystemExit) as excinfo:
        mcp_ingest._validate("slack", payload)
    assert expected in str(excinfo.value)


def test_a_well_formed_payload_passes_validation():
    mcp_ingest._validate("deals", {"values": [["Header"], ["row"]]})
    mcp_ingest._validate("slack", {"se_rep_id": 5, "matches": []})


def test_an_unreadable_file_fails_with_the_path_not_a_traceback(monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        run(monkeypatch, tmp_path, "deals", str(tmp_path / "missing.json"))
    assert "can't read" in str(excinfo.value)


def test_a_malformed_json_file_fails_with_the_line_and_column(monkeypatch, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"values": [', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        run(monkeypatch, tmp_path, "deals", str(path))
    assert "isn't valid JSON" in str(excinfo.value)


def test_an_unknown_kind_prints_usage_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run(monkeypatch, tmp_path, "not_a_kind", "whatever.json")
    assert excinfo.value.code == 1
    assert "Usage:" in capsys.readouterr().out


# ── stdout contract ──────────────────────────────────────────────────────
def test_stdout_is_one_line_of_counts_and_never_row_data(monkeypatch, tmp_path, capsys):
    payload = {"values": grid(DEALS_HEADER, {
        "Lead Sales Engineer": "Amara Osei (1)", "Stage": "3 - Technical Scoping (1)",
        "Opportunity Name": "Confidential Mega Deal", "Close Date": "5/4/2026",
        "Amount": "$9,000,000",
    })}
    run(monkeypatch, tmp_path, "deals", write_payload(tmp_path, payload))

    out = capsys.readouterr().out
    assert out.count("\n") == 1, "exactly one line of output"
    result = json.loads(out)
    assert result["synced"] == 1
    assert "Confidential Mega Deal" not in out
    assert "9,000,000" not in out


def test_the_tech_forecast_kind_loads_and_reports_counts(monkeypatch, tmp_path, capsys):
    payload = {"values": grid(TF_HEADER, {
        "Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
        "Opportunity Name": "Granite Peak Zero Trust", "Close Date": "5/4/2026",
        "Amount (converted)": "300,000", "Presales Stage": "4 - Validate Solution",
    })}
    run(monkeypatch, tmp_path, "tech_forecast", write_payload(tmp_path, payload))
    result = json.loads(capsys.readouterr().out)
    assert result == {"synced": 1, "unchanged": 0, "deleted": 0,
                      "overrides_carried": 0, "unparsed_amounts": 0}


def test_the_allow_shrink_flag_is_parsed_out_of_the_arguments(monkeypatch, tmp_path, capsys):
    """Without the flag a big shrink aborts; with it the same payload loads."""
    db_path = tmp_path / "ingest.db"
    big = {"values": grid(TF_HEADER, *[{
        "Lead Sales Engineer": "Amara Osei (1)", "Deal Forecast Status": "Strong (1)",
        "Opportunity Name": f"Deal {i:02d}", "Close Date": "5/4/2026",
        "Amount (converted)": "1,000", "Presales Stage": "4 - Validate Solution",
        "Opportunity ID": f"006BULK{i:02d}",
    } for i in range(10)])}
    small = {"values": big["values"][:3]}

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setattr("sys.argv", ["mcp_ingest.py", "tech_forecast", write_payload(tmp_path, big, "big.json")])
    mcp_ingest.main()
    capsys.readouterr()

    small_path = write_payload(tmp_path, small, "small.json")
    monkeypatch.setattr("sys.argv", ["mcp_ingest.py", "tech_forecast", small_path])
    with pytest.raises(RuntimeError):
        mcp_ingest.main()

    monkeypatch.setattr("sys.argv", ["mcp_ingest.py", "tech_forecast", small_path, "--allow-shrink"])
    mcp_ingest.main()
    assert json.loads(capsys.readouterr().out)["deleted"] == 8


def test_the_slack_kind_loads_matches_for_the_given_rep(monkeypatch, tmp_path, capsys):
    from db import Database
    database = Database(str(tmp_path / "ingest.db"))
    database.init()
    rep = add_rep(database, "Amara Osei", slack_user_id="U0SYNTH")

    payload = {"se_rep_id": rep, "matches": [{
        "ts": "1757000000.000100", "channel_id": "C01", "channel_name": "se-canada",
        "text": "Sensitive customer detail", "permalink": "https://example.slack.com/x",
    }]}
    run(monkeypatch, tmp_path, "slack", write_payload(tmp_path, payload))

    out = capsys.readouterr().out
    assert json.loads(out)["new"] == 1
    assert "Sensitive customer detail" not in out
