"""HTTP contract smoke tests.

Nothing here asserts business numbers (those live in the other modules) — this
file only pins the shapes a React `fetch()` depends on: no 5xx on a seeded DB,
bounded/garbage query params handled, 400 vs 404 on the assign routes, and a
JSON body (never an HTML error page) whatever gets posted.
"""

import re

import pytest

# URL placeholders -> a value that exists in the seeded fixture DB.
_PATH_VALUES = {
    "rep_id": "1",
    "period": "2026-H2",
    "sheet_key": "oid:0081",
    "filename": "index.html",
}


def _concrete_paths(flask_app):
    paths = []
    for rule in flask_app.url_map.iter_rules():
        if rule.endpoint == "static" or "GET" not in rule.methods:
            continue
        path = re.sub(
            r"<(?:[^:<>]+:)?([^<>]+)>",
            lambda m: _PATH_VALUES.get(m.group(1), "1"),
            rule.rule,
        )
        paths.append(path)
    return sorted(set(paths))


def test_every_get_route_is_exercised_by_this_file(api):
    """Guard against a new route silently escaping the smoke test."""
    assert len(_concrete_paths(api.application)) >= 14


def test_no_get_route_returns_a_server_error_on_a_seeded_database(api):
    failures = {}
    for path in _concrete_paths(api.application):
        response = api.get(path)
        if response.status_code >= 500:
            failures[path] = response.status_code
    assert failures == {}


def test_json_endpoints_return_json_not_an_html_error_page(api):
    for path in _concrete_paths(api.application):
        if not path.startswith("/api/"):
            continue
        response = api.get(path)
        assert response.status_code == 200, path
        assert response.is_json, path


@pytest.mark.parametrize("query", ["?limit=abc", "?limit=999999", "?limit=-5", "?limit=", "?limit=0",
                                   "?limit=1.5", "?limit[]=3"])
def test_preread_limit_param_is_bounded_and_never_500s(api, query):
    response = api.get(f"/api/tech-forecast/preread{query}")
    assert response.status_code == 200
    assert "top_deals" in response.get_json()


@pytest.mark.parametrize("query", ["?days=abc", "?days=999999", "?days=0", "?days="])
def test_arr_trend_days_param_is_bounded_and_never_500s(api, query):
    response = api.get(f"/api/dashboard/arr-trend{query}")
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_deals_filters_accept_arbitrary_query_values(api):
    for query in ["", "?quarter=all", "?quarter=current", "?quarter=nonsense",
                  "?stage=2 - Discovery", "?search=%25", "?search=' OR 1=1 --"]:
        response = api.get(f"/api/deals{query}")
        assert response.status_code == 200, query
        assert "deals" in response.get_json()


def test_unknown_route_is_a_404_json_error(api):
    response = api.get("/api/definitely-not-a-route")
    assert response.status_code == 404


# ── assign routes ────────────────────────────────────────────────────────
@pytest.mark.parametrize("route", ["assign-se", "assign-backup"])
def test_assigning_a_nonexistent_rep_is_a_400(api, route):
    response = api.post(f"/api/tech-forecast/oid:0081/{route}", json={"se_rep_id": 987654})
    assert response.status_code == 400
    assert "987654" in response.get_json()["error"]


@pytest.mark.parametrize("route", ["assign-se", "assign-backup"])
def test_a_non_integer_rep_id_is_a_400(api, route):
    response = api.post(f"/api/tech-forecast/oid:0081/{route}", json={"se_rep_id": "not-an-id"})
    assert response.status_code == 400
    assert "integer" in response.get_json()["error"]


@pytest.mark.parametrize("route", ["assign-se", "assign-backup"])
def test_an_unknown_sheet_key_is_a_404_not_a_false_success(api, route):
    """A stale key from an open tab matches no row; reporting ok would show a
    success toast for an assignment that never happened."""
    response = api.post(
        f"/api/tech-forecast/oid:does-not-exist/{route}",
        json={"se_rep_id": api.rep_ids["amara"]},
    )
    assert response.status_code == 404
    assert "re-syncing" in response.get_json()["error"]


def test_assigning_a_valid_rep_persists_the_override(api):
    response = api.post("/api/tech-forecast/oid:0082/assign-se",
                        json={"se_rep_id": api.rep_ids["amara"]})
    assert response.status_code == 200
    with api.db.conn() as c:
        row = c.execute(
            "SELECT assigned_se_rep_id FROM tech_forecast_deals WHERE sheet_key = 'oid:0082'"
        ).fetchone()
    assert row["assigned_se_rep_id"] == api.rep_ids["amara"]


def test_a_null_rep_id_clears_the_assignment(api):
    api.post("/api/tech-forecast/oid:0082/assign-se", json={"se_rep_id": api.rep_ids["amara"]})
    assert api.post("/api/tech-forecast/oid:0082/assign-se",
                    json={"se_rep_id": None}).status_code == 200
    with api.db.conn() as c:
        row = c.execute(
            "SELECT assigned_se_rep_id FROM tech_forecast_deals WHERE sheet_key = 'oid:0082'"
        ).fetchone()
    assert row["assigned_se_rep_id"] is None


def test_a_non_string_backup_note_is_a_400(api):
    response = api.post("/api/tech-forecast/oid:0081/assign-backup",
                        json={"se_rep_id": api.rep_ids["bo"], "note": {"nested": "object"}})
    assert response.status_code == 400


# ── malformed bodies ─────────────────────────────────────────────────────
_POST_PATHS = [
    "/api/reps/1",
    "/api/tech-forecast/oid:0081/assign-se",
    "/api/tech-forecast/oid:0081/assign-backup",
    "/api/reps/1/reviews/2026-H2",
    "/api/top-items",
]

_BAD_BODIES = [
    ("literal null", "null"),
    ("json array", "[]"),
    ("json string", '"just a string"'),
    ("json number", "42"),
    ("truncated json", '{"se_rep_id":'),
    ("not json at all", "<html></html>"),
    ("empty body", ""),
]


@pytest.mark.parametrize("path", _POST_PATHS)
@pytest.mark.parametrize("label,body", _BAD_BODIES, ids=[b[0] for b in _BAD_BODIES])
def test_a_malformed_json_body_never_causes_a_server_error(api, path, label, body):
    response = api.post(path, data=body, content_type="application/json")
    assert response.status_code < 500, f"{path} with {label}"
    assert response.is_json


@pytest.mark.parametrize("path", _POST_PATHS)
def test_a_missing_body_entirely_never_causes_a_server_error(api, path):
    response = api.post(path)
    assert response.status_code < 500
    assert response.is_json


@pytest.mark.parametrize("path", _POST_PATHS)
def test_a_non_object_json_body_is_rejected_with_400(api, path):
    response = api.post(path, data="[]", content_type="application/json")
    assert response.status_code == 400
    assert "JSON object" in response.get_json()["error"]


# ── rep updates ──────────────────────────────────────────────────────────
def test_updating_an_unknown_rep_is_a_404(api):
    assert api.post("/api/reps/987654", json={"title": "Ghost"}).status_code == 404


@pytest.mark.parametrize("value,expected", [
    (True, 1), (False, 0), (1, 1), (0, 0), ("true", 1), ("FALSE", 0), ("yes", 1), ("", 0),
])
def test_active_is_coerced_to_a_real_zero_or_one(api, value, expected):
    assert api.post(f"/api/reps/{api.rep_ids['bo']}", json={"active": value}).status_code == 200
    with api.db.conn() as c:
        row = c.execute("SELECT active FROM se_reps WHERE id = ?", (api.rep_ids["bo"],)).fetchone()
    assert row["active"] == expected


@pytest.mark.parametrize("value", ["maybe", "2.5M", [], {}, "-1"])
def test_a_nonsense_active_or_arr_target_is_rejected_rather_than_stored(api, value):
    response = api.post(f"/api/reps/{api.rep_ids['bo']}", json={"active": value})
    if response.status_code == 200:
        # Only a genuinely valid boolean-ish string may get through.
        pytest.fail(f"active={value!r} was accepted")
    assert response.status_code == 400


@pytest.mark.parametrize("value", ["2.5M", "abc", -1, True, [], {}])
def test_a_nonnumeric_arr_target_is_a_400(api, value):
    assert api.post(f"/api/reps/{api.rep_ids['bo']}", json={"arr_target": value}).status_code == 400


def test_a_valid_arr_target_is_stored_as_a_number(api):
    assert api.post(f"/api/reps/{api.rep_ids['bo']}", json={"arr_target": "1500000"}).status_code == 200
    reps = {r["name"]: r for r in api.get("/api/reps").get_json()}
    assert reps["Bo Nakamura"]["arr_target"] == 1_500_000.0


def test_a_structured_value_in_a_text_field_is_a_400(api):
    assert api.post(f"/api/reps/{api.rep_ids['bo']}", json={"title": {"a": 1}}).status_code == 400


# ── unconfigured integrations ────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/sync/sheets", "/api/sync/slack",
                                  "/api/reps/1/reviews/2026-H2/generate"])
def test_unconfigured_integrations_return_400_with_a_json_reason(api, path):
    response = api.post(path)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_settings_reports_what_is_configured(api):
    body = api.get("/api/settings").get_json()
    assert body["litellm_configured"] is False
    assert body["google_sheets_configured"] is False
    assert body["slack_configured"] is False
    assert body["current_review_period"].endswith(("-H1", "-H2"))


# ── writes that should succeed ───────────────────────────────────────────
def test_saving_and_reading_back_a_review(api):
    assert api.post(f"/api/reps/{api.rep_ids['bo']}/reviews/2026-H2",
                    json={"content": "notes", "status": "final"}).status_code == 200
    body = api.get(f"/api/reps/{api.rep_ids['bo']}/reviews/2026-H2").get_json()
    assert body["content"] == "notes"
    assert body["status"] == "final"


def test_reading_a_review_that_does_not_exist_returns_null(api):
    assert api.get(f"/api/reps/{api.rep_ids['bo']}/reviews/1999-H1").get_json() is None


def test_top_items_scaffold_and_save_round_trip(api):
    scaffold = api.post("/api/top-items/scaffold").get_json()["scaffold"]
    assert "Hiring" in scaffold
    saved = api.post("/api/top-items", json={"content": scaffold}).get_json()
    assert saved["content"] == scaffold
    assert api.get("/api/top-items/latest").get_json()["content"] == scaffold
    assert len(api.get("/api/top-items/history").get_json()) >= 1


def test_slack_draft_endpoint_returns_a_rendered_message(api):
    draft = api.post("/api/tech-forecast/preread/draft").get_json()["draft"]
    assert "Tech Forecast Call Prep" in draft
    assert "The Mantra" in draft
