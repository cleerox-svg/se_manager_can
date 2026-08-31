"""Pure aggregation/report-building for the Technical Forecast page and the
weekly Slack preread. No Flask dependency — reused by app.py's routes and by
tech_forecast_sync.py's snapshot capture.

Deliberate deviation from Satish Ponnaluri's "Tech Win Forecast & Risk
Summary" template, called out here for visibility rather than left implicit:
"Total Active Pipeline" applies no dollar floor (reuses the full, already-
curated `tech_forecast_deals` set rather than a raw $100K CRM floor, to avoid
a second threshold competing with MUST_WIN_THRESHOLD).
"""

import json
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
            "lead_se_name": r.get("lead_se_name") or "",
            "pre_sales_notes": r.get("pre_sales_notes") or "",
            "se_manager_notes": r.get("se_manager_notes") or "",
            "pre_sales_next_steps": r.get("pre_sales_next_steps") or "",
            "target_tw_date": r.get("technical_win_date") or r.get("close_date"),
        }
        for r in candidates[:limit]
    ]


def build_needs_lead_se(deal_rows):
    """Deals the sheet itself has no Lead SE set for yet — the literal
    "-" group, independent of any manual override or opportunity-name-join
    fallback the app might otherwise resolve."""
    candidates = [r for r in deal_rows if not r.get("lead_se_name")]
    candidates.sort(key=lambda r: r.get("amount") or 0, reverse=True)
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "amount": r.get("amount"),
            "presales_stage": r.get("presales_stage"),
            "forecast_status": r.get("forecast_status"),
            "opportunity_owner": r.get("opportunity_owner"),
        }
        for r in candidates
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
        "needs_lead_se": build_needs_lead_se(deal_rows),
        "must_win_threshold": MUST_WIN_THRESHOLD,
        "generated_at": datetime.now().isoformat(),
    }
