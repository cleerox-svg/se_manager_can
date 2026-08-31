"""Pure aggregation/report-building for the Technical Forecast page and the
weekly Slack preread. No Flask dependency — reused by app.py's routes and by
tech_forecast_sync.py's snapshot capture.

Deliberate deviations from Satish Ponnaluri's "Tech Win Forecast & Risk
Summary" template, called out here for visibility rather than left implicit:
"Total Active Pipeline" applies no dollar floor (reuses the full, already-
curated `tech_forecast_deals` set rather than a raw $100K CRM floor, to avoid
a second threshold competing with MUST_WIN_THRESHOLD). "Status & Blocker" and
"Action to TW" map to the existing `pre_sales_notes`/`se_manager_notes`
fields — the closest fit, no new column invented. The Auth0/Okta split on
gap-to-forecast and coverage is *derived* (quota minus each product's native
Forecast Value), since Clari itself only reports those two figures blended,
not split — labeled "_derived"/"_blended" below so callers don't mistake it
for a number Clari actually reports.
"""

import json
import re
from datetime import date, datetime

MUST_WIN_THRESHOLD = 150000

_STAGE_BUCKETS = {
    "2 - Discovery & Technical Qualification": "Early Tech",
    "3 - Technical Scoping": "Early Tech",
    "4 - Validate Solution": "Validate Solution",
    "5 - Final Due Diligence": "Final Due Diligence",
    "6 - Technical Win": "Technical Win",
}

_STAGE_ORDER = {
    "2 - Discovery & Technical Qualification": 1,
    "3 - Technical Scoping": 2,
    "4 - Validate Solution": 3,
    "5 - Final Due Diligence": 4,
    "6 - Technical Win": 5,
}

_BUCKET_ORDER = {
    "Technical Win": 0,
    "Final Due Diligence": 1,
    "Validate Solution": 2,
    "Early Tech": 3,
    "Untagged": 4,
}

_EXCLUDED_TOP_DEAL_BUCKETS = ("Technical Win", "Final Due Diligence")

# Clari (Field, Data Type) pairs this app cares about — shared with
# clari_sync.py so the parser's allow-list and these crossref lookups never
# drift apart. Only meaningful for rows where Timeframe is the bare quarterly
# rollup ("Q3", "Q4", ...) — Clari also exports a per-month breakdown for
# Forecast/Forecast[Auth]/Forecast[Okta] under Timeframe values like "August
# FY 2027", which clari_sync.py filters out.
CLARI_QUOTA_VALUE = ("Quota", "Quota Value")
CLARI_QTD_BOOKINGS = ("Quota", "QTD Bookings")
CLARI_FORECAST_AUTH = ("Forecast [Auth]", "Forecast Value")
CLARI_FORECAST_OKTA = ("Forecast [Okta]", "Forecast Value")
CLARI_FORECAST_BLENDED = ("Forecast", "Forecast Value")
CLARI_TOTAL_PIPELINE = ("Total Pipeline", "Opportunities Total")
CLARI_TOTAL_PIPELINE_CLOSED = ("Total Pipeline", "Closed")
CLARI_GAP_TO_FORECAST = ("Gap to Forecast", "Calculations Total")
CLARI_COVERAGE_VS_QUOTA = ("Total Pipeline vs. Quota Coverage", "Calculations Total")
CLARI_COVERAGE_VS_FORECAST = ("Total Pipeline vs. Forecast Coverage", "Calculations Total")

CLARI_ALLOWED_PAIRS = {
    CLARI_QUOTA_VALUE, CLARI_QTD_BOOKINGS, CLARI_FORECAST_AUTH, CLARI_FORECAST_OKTA,
    CLARI_FORECAST_BLENDED, CLARI_TOTAL_PIPELINE, CLARI_TOTAL_PIPELINE_CLOSED,
    CLARI_GAP_TO_FORECAST, CLARI_COVERAGE_VS_QUOTA, CLARI_COVERAGE_VS_FORECAST,
}


def parse_clari_value(raw: str):
    """Returns (numeric, kind) for a raw Clari Data Value string like
    '$378,000.00', '-0.7X', or ''."""
    if raw is None:
        return None, "text"
    s = raw.strip()
    if not s:
        return None, "text"
    is_ratio = s.upper().endswith("X")
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if not cleaned or cleaned in ("-", "."):
        return None, ("ratio" if is_ratio else "text")
    try:
        value = float(cleaned)
    except ValueError:
        return None, "text"
    if is_ratio:
        return value, "ratio"
    if s.startswith("$"):
        return value, "currency"
    return value, "count"


def stage_bucket(presales_stage):
    if not presales_stage:
        return "Untagged"
    return _STAGE_BUCKETS.get(presales_stage, "Untagged")


def aggregate_buckets(deal_rows):
    """forecast_status -> stage bucket -> {"amount": .., "count": ..}"""
    buckets = {}
    for row in deal_rows:
        status = row.get("forecast_status") or "Untagged"
        bucket = stage_bucket(row.get("presales_stage"))
        slot = buckets.setdefault(status, {}).setdefault(bucket, {"amount": 0.0, "count": 0})
        slot["amount"] += row.get("amount") or 0
        slot["count"] += 1
    return buckets


def build_key_metrics(deal_rows):
    total_amount = sum(r.get("amount") or 0 for r in deal_rows)
    total_count = len(deal_rows)

    won = [r for r in deal_rows if stage_bucket(r.get("presales_stage")) == "Technical Win"]
    won_amount = sum(r.get("amount") or 0 for r in won)

    in_flight = [
        r for r in deal_rows
        if stage_bucket(r.get("presales_stage")) in ("Validate Solution", "Final Due Diligence")
    ]
    in_flight_amount = sum(r.get("amount") or 0 for r in in_flight)

    untagged = [r for r in deal_rows if stage_bucket(r.get("presales_stage")) == "Untagged"]
    untagged_amount = sum(r.get("amount") or 0 for r in untagged)

    return {
        "total_active_pipeline_amount": total_amount,
        "total_active_pipeline_count": total_count,
        "total_tech_won_amount": won_amount,
        "total_tech_won_count": len(won),
        "total_tech_won_pct": (won_amount / total_amount) if total_amount else 0.0,
        "in_flight_amount": in_flight_amount,
        "in_flight_count": len(in_flight),
        "untagged_amount": untagged_amount,
        "untagged_count": len(untagged),
    }


def build_breakdown(deal_rows):
    buckets = aggregate_buckets(deal_rows)
    breakdown = []
    for status in sorted(buckets):
        stage_slots = buckets[status]
        breakdown.append({
            "forecast_status": status,
            "stages": [
                {"bucket": bucket, **stage_slots[bucket]}
                for bucket in sorted(stage_slots, key=lambda b: _BUCKET_ORDER.get(b, 99))
            ],
        })
    return breakdown


def build_top_deals(deal_rows, limit=10):
    candidates = [
        r for r in deal_rows
        if stage_bucket(r.get("presales_stage")) not in _EXCLUDED_TOP_DEAL_BUCKETS
    ]
    candidates.sort(key=lambda r: r.get("amount") or 0, reverse=True)
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "amount": r.get("amount"),
            "presales_stage": r.get("presales_stage"),
            "forecast_status": r.get("forecast_status"),
            "opportunity_owner": r.get("opportunity_owner"),
            "status_and_blocker": r.get("pre_sales_notes") or "",
            "action_to_tw": r.get("se_manager_notes") or "",
            "target_tw_date": r.get("technical_win_date") or r.get("close_date"),
        }
        for r in candidates[:limit]
    ]


def build_executive_takeaway(metrics):
    return (
        f"Technical pipeline stands at ${metrics['total_active_pipeline_amount']:,.0f} "
        f"across {metrics['total_active_pipeline_count']} active opportunities. "
        f"${metrics['total_tech_won_amount']:,.0f} ({metrics['total_tech_won_pct']:.0%}) is "
        f"already secured as Technical Wins, with {metrics['in_flight_count']} deals "
        f"(${metrics['in_flight_amount']:,.0f}) in active SE engagement (Validate Solution / "
        f"Final Due Diligence). {metrics['untagged_count']} deals "
        f"(${metrics['untagged_amount']:,.0f}) are untagged and need SE Manager triage."
    )


def build_weekly_deltas(db):
    today = date.today().isoformat()
    with db.conn() as c:
        prior = c.execute(
            "SELECT * FROM tech_forecast_snapshots WHERE snapshot_date < ? "
            "ORDER BY snapshot_date DESC LIMIT 1",
            (today,),
        ).fetchone()
        current_rows = [
            dict(r) for r in c.execute(
                "SELECT sheet_key, opportunity_name, amount, presales_stage, forecast_status "
                "FROM tech_forecast_deals"
            ).fetchall()
        ]

    if not prior:
        return []

    prior_states = json.loads(prior["deal_states_json"])
    current_states = {r["sheet_key"]: r for r in current_rows}

    prior_keys = set(prior_states)
    current_keys = set(current_states)

    deltas = []

    for key in current_keys - prior_keys:
        r = current_states[key]
        deltas.append({
            "type": "new",
            "opportunity_name": r["opportunity_name"],
            "amount": r["amount"],
            "detail": f"New to pipeline at {r['presales_stage'] or 'Untagged'}",
        })

    for key in prior_keys - current_keys:
        r = prior_states[key]
        deltas.append({
            "type": "dropped",
            "opportunity_name": r["opportunity_name"],
            "amount": r["amount"],
            "detail": "Dropped off the technical pipeline since last week",
        })

    for key in prior_keys & current_keys:
        prev, cur = prior_states[key], current_states[key]
        if prev["presales_stage"] != cur["presales_stage"]:
            prev_order = _STAGE_ORDER.get(prev["presales_stage"], 0)
            cur_order = _STAGE_ORDER.get(cur["presales_stage"], 0)
            direction = "advanced" if cur_order > prev_order else "regressed"
            deltas.append({
                "type": direction,
                "opportunity_name": cur["opportunity_name"],
                "amount": cur["amount"],
                "detail": f"{prev['presales_stage'] or 'Untagged'} -> {cur['presales_stage'] or 'Untagged'}",
            })
        elif prev["forecast_status"] != cur["forecast_status"]:
            deltas.append({
                "type": "status_change",
                "opportunity_name": cur["opportunity_name"],
                "amount": cur["amount"],
                "detail": f"{prev['forecast_status'] or 'Untagged'} -> {cur['forecast_status'] or 'Untagged'}",
            })

    deltas.sort(key=lambda d: d.get("amount") or 0, reverse=True)
    return deltas


def build_ae_crossref(db):
    with db.conn() as c:
        snapshot_rows = [dict(r) for r in c.execute("SELECT * FROM clari_ae_snapshots").fetchall()]
        pipeline_rows = [
            dict(r) for r in c.execute(
                "SELECT opportunity_owner, amount, presales_stage FROM tech_forecast_deals"
            ).fetchall()
        ]

    if not snapshot_rows:
        return []

    by_ae = {}
    for row in snapshot_rows:
        by_ae.setdefault(row["ae_name"], {})[(row["field"], row["data_type"])] = row

    open_pipeline = {}
    for row in pipeline_rows:
        if stage_bucket(row["presales_stage"]) == "Technical Win":
            continue
        slot = open_pipeline.setdefault(row["opportunity_owner"], {"amount": 0.0, "count": 0})
        slot["amount"] += row["amount"] or 0
        slot["count"] += 1

    crossref = []
    for ae_name, metrics in sorted(by_ae.items()):
        quota = metrics.get(CLARI_QUOTA_VALUE)
        forecast_auth = metrics.get(CLARI_FORECAST_AUTH)
        forecast_okta = metrics.get(CLARI_FORECAST_OKTA)
        coverage_quota = metrics.get(CLARI_COVERAGE_VS_QUOTA)
        coverage_forecast = metrics.get(CLARI_COVERAGE_VS_FORECAST)

        quota_amount = quota["data_value_numeric"] if quota else None
        forecast_auth_amount = forecast_auth["data_value_numeric"] if forecast_auth else None
        forecast_okta_amount = forecast_okta["data_value_numeric"] if forecast_okta else None
        pipeline_slot = open_pipeline.get(ae_name, {"amount": 0.0, "count": 0})

        crossref.append({
            "ae_name": ae_name,
            "quota_amount": quota_amount,
            "forecast_auth_amount": forecast_auth_amount,
            "forecast_okta_amount": forecast_okta_amount,
            "gap_auth_derived": (
                quota_amount - forecast_auth_amount
                if quota_amount is not None and forecast_auth_amount is not None else None
            ),
            "gap_okta_derived": (
                quota_amount - forecast_okta_amount
                if quota_amount is not None and forecast_okta_amount is not None else None
            ),
            "coverage_vs_quota_blended": coverage_quota["data_value"] if coverage_quota else None,
            "coverage_vs_forecast_blended": coverage_forecast["data_value"] if coverage_forecast else None,
            "open_tech_pipeline_amount": pipeline_slot["amount"],
            "open_tech_pipeline_count": pipeline_slot["count"],
        })
    return crossref


def build_preread(db, limit=10):
    with db.conn() as c:
        deal_rows = [dict(r) for r in c.execute("SELECT * FROM tech_forecast_deals").fetchall()]

    metrics = build_key_metrics(deal_rows)
    return {
        "executive_takeaway": build_executive_takeaway(metrics),
        "key_metrics": metrics,
        "breakdown": build_breakdown(deal_rows),
        "top_deals": build_top_deals(deal_rows, limit=limit),
        "weekly_deltas": build_weekly_deltas(db),
        "ae_crossref": build_ae_crossref(db),
        "must_win_threshold": MUST_WIN_THRESHOLD,
        "generated_at": datetime.now().isoformat(),
    }
