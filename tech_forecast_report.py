"""Pure aggregation/report-building for the Technical Forecast page and the
weekly Slack preread. No Flask dependency — reused by app.py's routes and by
tech_forecast_sync.py's snapshot capture.

Deliberate deviation from Satish Ponnaluri's "Tech Win Forecast & Risk
Summary" template, called out here for visibility rather than left implicit:
"Total Active Pipeline" applies no dollar floor (reuses the full, already-
curated `tech_forecast_deals` set rather than a raw $100K CRM floor).
"""

import json
import re
from datetime import date, datetime

from salesforce_links import opportunity_url

# Static, team-wide Command of the Message recital ("The Mantra" — Force
# Management's 6-part "Ultimate Summation": Challenges->PBOs, Required
# Capabilities, Metrics, How We Do It, How We Do It Better, Proof Points).
# Anchored on Okta's "Identity security - breach protection" Value Driver
# since it's the flagship, most-universal driver across deals. Per Claude
# Leroux (2026-09-03), deliberately one static script, not per-deal —
# per-deal would need new Value-Driver-tagging fields that don't exist yet.
_MANTRA = (
    "*The Mantra:*\n"
    "1. Challenges -> Outcomes: Fragmented identity, over-privileged human & AI access, "
    "and manual joiner/mover/leaver create breach exposure — customers need measurably lower "
    "breach risk, faster detection/containment, and protected revenue & trust.\n"
    "2. Required Capabilities: One platform across every identity type (SSO/MFA, Governance, "
    "Privileged Access, Identity Security Posture, Device Access, Threat Protection) with a "
    "single control plane for human AND AI/non-human identities.\n"
    "3. Metrics: # identities under management, # AI agents discovered & governed, minutes of "
    "actual vs. contracted downtime, % of access granted just-in-time vs. standing.\n"
    "4. How We Do It: One unified, seamlessly-orchestrated identity fabric — not a "
    "stitched-together stack of point tools.\n"
    "5. How We Do It Better: Independent & vendor-neutral, integrates with everything, backed "
    "by the Okta Secure Identity Commitment.\n"
    "6. Proof Points: Don't take my word for it — Hitachi, Workday, and Sony Pictures "
    "Networks all cut breach exposure and audit time after standardizing on Okta."
)

# Plain-text Slack handles for the four direct reports, keyed by lowercased
# `se_reps.name` — real `<@slack_user_id>` mention syntax only resolves when
# sent via the Slack API, not when pasted as text into Slack's compose box,
# so the Team Prep Message draft (which is copy-pasted) uses plain aliases
# instead. Per Claude Leroux (2026-09-14): only these four get an alias;
# everyone else (Mary Greenlee, inactive reps with historical deals) is
# shown as a plain name with no mention.
_SLACK_ALIAS_BY_NAME = {
    "rishika kondaveeti": "Rishika",
    "nic da silva": "nic",
    "sean keleher": "SeanK",
    "valentin bourneuf": "Valentin",
}

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


def fiscal_quarter(iso_date):
    """Okta's fiscal year runs Feb 1 - Jan 31, named by its start year
    (e.g. FY26 = Feb 2026 - Jan 2027). Used for the Look Back grouping —
    unrelated to app.py's current_quarter()/sheets_sync.py's _quarter(),
    which are plain calendar quarters for a different feature (the open
    SFDC pipeline's "current quarter" filter)."""
    if not iso_date:
        return None
    d = datetime.strptime(iso_date[:10], "%Y-%m-%d")
    fy_year = d.year if d.month >= 2 else d.year - 1
    fq = ((d.month - 2) % 12) // 3 + 1
    return f"FY{fy_year % 100:02d}-Q{fq}"


def fiscal_quarter_sort_key(label):
    """Higher key = more recent quarter; None/unknown sorts last."""
    if not label:
        return (-1, -1)
    return (int(label[2:4]), int(label[-1]))


def quarter_label(key):
    """Format a (fy, q) sort-key tuple as a display label, e.g. FY26-Q3."""
    return f"FY{key[0]:02d}-Q{key[1]}"


def _offset_quarter_key(key, n):
    """Shift a (fy, q) key by n quarters, e.g. (26, 3) + 1 -> (26, 4),
    (26, 4) + 1 -> (27, 1). Used to find "next quarter" relative to
    whatever quarter `key` represents."""
    fy, q = key
    q += n
    while q > 4:
        q -= 4
        fy += 1
    while q < 1:
        q += 4
        fy -= 1
    return (fy, q)


def fiscal_quarter_date_range(key):
    """Return (start_iso, end_iso) exclusive-end ISO dates for a (fy, q)
    sort-key tuple. Fiscal quarter Q of fiscal year FY (named by its start
    year) starts Feb 1 of that FY's start year plus 3*(Q-1) months, and ends
    (exclusive) 3 months after that start — same Feb-1 fiscal-year math as
    fiscal_quarter()."""
    fy, q = key
    year = 2000 + fy
    start_month = 2 + 3 * (q - 1)
    start_year = year + (start_month - 1) // 12
    start_month = (start_month - 1) % 12 + 1
    end_month = start_month + 3
    end_year = start_year + (end_month - 1) // 12
    end_month = (end_month - 1) % 12 + 1
    start = date(start_year, start_month, 1)
    end = date(end_year, end_month, 1)
    return (start.isoformat(), end.isoformat())


def current_fiscal_quarter():
    return fiscal_quarter(date.today().isoformat())


def quarter_bucket(target_date):
    """Label a deal's target_tw_date as 'current', 'next', or 'later' /
    None relative to today's fiscal quarter — powers the Slack draft's
    Current Quarter / Next Quarter split."""
    if not target_date:
        return None
    key = fiscal_quarter_sort_key(fiscal_quarter(target_date))
    current_key = fiscal_quarter_sort_key(current_fiscal_quarter())
    if key == current_key:
        return "current"
    if key == _offset_quarter_key(current_key, 1):
        return "next"
    return "later"


def _slack_opp_link(d):
    """Plain-text "name (url)" for a deal dict's opportunity name when it
    carries a resolvable `opportunity_url`, else just the plain name. Not
    Slack mrkdwn (`<url|name>`) on purpose: this draft is meant to be
    copy-pasted into Slack's compose box, not sent via chat.postMessage, and
    mrkdwn link syntax is only parsed server-side for Web API sends — pasted
    literally, Slack's client-side auto-linker instead swallows the trailing
    `|name>` into the URL and mangles it."""
    url = d.get("opportunity_url")
    return f"{d['opportunity_name']} ({url})" if url else d["opportunity_name"]


def _stage_label(presales_stage):
    """Strip the CRM's leading numeric stage-order prefix (e.g. "4 - ")
    for human-facing display in the Slack draft — that number is Okta's
    internal presales-stage ordering, not meaningful to a reader."""
    if not presales_stage:
        return "Untagged"
    return re.sub(r"^\d+\s*-\s*", "", presales_stage)


def stage_bucket(presales_stage):
    if not presales_stage:
        return "Untagged"
    return _STAGE_BUCKETS.get(presales_stage, "Untagged")


def aggregate_buckets(deal_rows):
    """confidence -> stage bucket -> {"amount": .., "count": ..}"""
    buckets = {}
    for row in deal_rows:
        status = row.get("confidence") or "Untagged"
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
            "confidence": status,
            "stages": [
                {"bucket": bucket, **stage_slots[bucket]}
                for bucket in sorted(stage_slots, key=lambda b: _BUCKET_ORDER.get(b, 99))
            ],
        })
    return breakdown


def build_arr_trend(snapshot_rows):
    """Team-wide daily ARR time series from the full tech_forecast_snapshots
    history (not just the single most-recent diff build_weekly_deltas uses).
    `snapshot_rows` are {"snapshot_date", "bucket_totals_json"} dicts, one per
    captured day, ordered ascending. Re-derives each day's bucket_totals_json
    (forecast_status -> stage_bucket -> {amount, count}) into the same
    won/in_flight/untagged/total classification build_key_metrics uses,
    summed across all forecast_status keys — this stays name-free by
    construction, since bucket_totals_json never carries SE names."""
    trend = []
    for row in snapshot_rows:
        buckets = json.loads(row["bucket_totals_json"])
        won_amount = won_count = 0.0
        in_flight_amount = in_flight_count = 0.0
        untagged_amount = untagged_count = 0.0
        total_amount = total_count = 0.0
        for stage_slots in buckets.values():
            for bucket, slot in stage_slots.items():
                amount, count = slot.get("amount", 0), slot.get("count", 0)
                total_amount += amount
                total_count += count
                if bucket == "Technical Win":
                    won_amount += amount
                    won_count += count
                elif bucket in ("Validate Solution", "Final Due Diligence"):
                    in_flight_amount += amount
                    in_flight_count += count
                elif bucket == "Untagged":
                    untagged_amount += amount
                    untagged_count += count
        trend.append({
            "snapshot_date": row["snapshot_date"],
            "total_amount": total_amount,
            "total_count": int(total_count),
            "tech_won_amount": won_amount,
            "tech_won_count": int(won_count),
            "in_flight_amount": in_flight_amount,
            "in_flight_count": int(in_flight_count),
            "untagged_amount": untagged_amount,
            "untagged_count": int(untagged_count),
        })
    return trend


def build_tech_win_trend(closed_win_rows, open_win_rows):
    """Team-wide Technical Win $/count grouped by fiscal quarter, for the
    Dashboard's quarter-over-quarter comparison. Deliberately takes plain
    amount/date rows (no name fields at all) rather than reusing app.py's
    /api/tech-forecast recent_wins construction, since that includes
    se_name/rep_name — this stays name-free at the SQL level, not just by
    dropping fields after the fact. `closed_win_rows` are already-closed
    Technical Wins (closed_deals where tech_win=1, dated by close_date);
    `open_win_rows` are deals currently sitting at the Technical Win stage
    in the open pipeline, dated by technical_win_date falling back to
    close_date, same precedence as build_top_deals."""
    by_quarter = {}
    for r in closed_win_rows:
        q = fiscal_quarter(r.get("close_date"))
        slot = by_quarter.setdefault(q, {"amount": 0.0, "count": 0})
        slot["amount"] += r.get("amount") or 0
        slot["count"] += 1
    for r in open_win_rows:
        q = fiscal_quarter(r.get("technical_win_date") or r.get("close_date"))
        slot = by_quarter.setdefault(q, {"amount": 0.0, "count": 0})
        slot["amount"] += r.get("amount") or 0
        slot["count"] += 1

    return [
        {"fiscal_quarter": q, **by_quarter[q]}
        for q in sorted(by_quarter, key=fiscal_quarter_sort_key)
    ]


_STAGE_QUESTIONS = {
    "1 - Assigned": "Newly assigned — curious what's driving the urgency here. What's the compelling event?",
    "2 - Discovery & Technical Qualification": "How's discovery going — what outcomes are resonating, and do we have a Champion yet?",
    "3 - Technical Scoping": "How are our capabilities lining up with their decision criteria so far?",
    "4 - Validate Solution": "Are we landing the \"how we do it better\" story — any proof points clicking with the economic buyer?",
    "5 - Final Due Diligence": "What's left on the decision/paper process side before we get to close?",
    "6 - Technical Win": "Anything on decision criteria or champion support worth keeping an eye on before close?",
}


def build_discussion_question(row):
    """Rule-based (not LLM-drafted) discussion prompt for a single deal —
    picks the most actionable question from what the sheet already tells
    us: missing next steps, a stale (unchanged-since-last-sync) update,
    an at-risk flag, or just where the deal sits in the stage pipeline.
    Checked in that priority order since each is a stronger signal than
    the stage alone. Per Claude Leroux (2026-09-03), phrased around Command
    of the Message / Opportunity Analysis & Coaching Guide qualification
    pillars (compelling event, Champion, Decision Criteria/Process,
    Proof Points) rather than generic stage-progress language, and in a
    curious/collaborative tone rather than an audit-checklist one."""
    next_steps = (row.get("pre_sales_next_steps") or "").strip()
    if not next_steps:
        return "Nothing logged for next steps yet — what's the story here, and how can the team help?"
    if row.get("notes_stale"):
        return "Hasn't moved since last sync — anything blocking, or support you need to keep it going?"
    if row.get("forecast_status") == "Forecasted Risk":
        return "Flagged as at-risk — want to talk through what's going on and how we de-risk it together?"
    return _STAGE_QUESTIONS.get(row.get("presales_stage"), "What's needed to move this toward Technical Win?")


def build_top_deals(deal_rows, limit=10, per_quarter_limit=None):
    """Candidate deals for the Slack preread's "Come ready to discuss"
    section. Capped per quarter bucket (current/next), not with one global
    top-N — per Claude Leroux (2026-09-14), a single global top-N by raw
    amount can starve one quarter's section (e.g. if the highest-$ deals all
    happen to land in "current") before build_slack_draft even gets a chance
    to group them by SE, leaving "next" thin or empty. `per_quarter_limit`
    defaults to max(limit, 15) so a caller that only passes the legacy
    `limit` (e.g. /api/tech-forecast/preread's `?limit=`) still gets a
    generous per-quarter candidate pool; "later"/unscheduled deals keep the
    old flat `limit` cap since build_slack_draft doesn't group that bucket
    by SE."""
    if per_quarter_limit is None:
        per_quarter_limit = max(limit, 15)
    candidates = [
        r for r in deal_rows
        if stage_bucket(r.get("presales_stage")) not in _EXCLUDED_TOP_DEAL_BUCKETS
    ]

    grouped = {"current": [], "next": [], "later": []}
    for r in candidates:
        target_tw_date = r.get("technical_win_date") or r.get("close_date")
        bucket = quarter_bucket(target_tw_date) or "later"
        grouped.setdefault(bucket, grouped["later"]).append(r)

    for group in grouped.values():
        group.sort(key=lambda r: r.get("amount") or 0, reverse=True)

    selected = (
        grouped["current"][:per_quarter_limit]
        + grouped["next"][:per_quarter_limit]
        + grouped["later"][:limit]
    )

    result = []
    for r in selected:
        target_tw_date = r.get("technical_win_date") or r.get("close_date")
        result.append({
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount"),
            "presales_stage": r.get("presales_stage"),
            "forecast_status": r.get("forecast_status"),
            "opportunity_owner": r.get("opportunity_owner"),
            "lead_se_name": r.get("lead_se_name") or "",
            "pre_sales_notes": r.get("pre_sales_notes") or "",
            "se_manager_notes": r.get("se_manager_notes") or "",
            "pre_sales_next_steps": r.get("pre_sales_next_steps") or "",
            "notes_stale": bool(r.get("notes_stale")),
            "target_tw_date": target_tw_date,
            "target_fiscal_quarter": fiscal_quarter(target_tw_date),
            "quarter_bucket": quarter_bucket(target_tw_date),
            "discussion_question": build_discussion_question(r),
        })
    return result


_ENTRY_SPLIT_RE = re.compile(r"\r?\n\r?\n+")

def _latest_note_entry(text):
    if not text:
        return ""
    return _ENTRY_SPLIT_RE.split(text.strip(), maxsplit=1)[0].strip()


def draft_sfdc_note(row):
    opp = row.get("opportunity_name") or "This opportunity"

    if row.get("presales_stage") == "6 - Technical Win":
        return (
            f"Technical Win is confirmed. Commercial stage is "
            f"{_stage_label(row.get('sales_stage'))} — no further pre-sales "
            f"action needed unless something changes."
        )

    se_note = _latest_note_entry(row.get("se_manager_notes"))
    if se_note:
        return f"Latest SE Manager note: {se_note}"

    presales_note = _latest_note_entry(row.get("pre_sales_notes"))
    if presales_note:
        return f"No SE Manager note logged yet. Latest Pre-Sales note: {presales_note}"

    next_steps = (row.get("pre_sales_next_steps") or "").strip()
    if next_steps:
        return f"No notes logged yet — next step on file: {next_steps}"

    return f"No notes logged yet for {opp} — worth a quick sync with the SE before the next forecast call."


def build_sfdc_updates(deal_rows):
    candidates = [
        r for r in deal_rows
        if r.get("sales_stage") != "10 - Closed/Won"
        and quarter_bucket(r.get("technical_win_date") or r.get("close_date")) in ("current", "next")
    ]
    candidates.sort(key=lambda r: r.get("amount") or 0, reverse=True)
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount"),
            "presales_stage": r.get("presales_stage"),
            "sales_stage": r.get("sales_stage"),
            "lead_se_name": r.get("lead_se_name") or "",
            "target_fiscal_quarter": fiscal_quarter(r.get("technical_win_date") or r.get("close_date")),
            "quarter_bucket": quarter_bucket(r.get("technical_win_date") or r.get("close_date")),
            "proposed_note": draft_sfdc_note(r),
        }
        for r in candidates
    ]


def build_missing_notes(deal_rows):
    """Open deals (not yet a Technical Win) with no Pre-Sales Next Steps
    logged at all — a stronger, more urgent signal than `notes_stale`
    (which just means an existing next step hasn't changed)."""
    candidates = [
        r for r in deal_rows
        if r.get("presales_stage") != "6 - Technical Win" and not (r.get("pre_sales_next_steps") or "").strip()
    ]
    candidates.sort(key=lambda r: r.get("amount") or 0, reverse=True)
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount"),
            "presales_stage": r.get("presales_stage"),
            "lead_se_name": r.get("lead_se_name") or "",
        }
        for r in candidates
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
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
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
                "SELECT sheet_key, opportunity_name, opportunity_id, amount, presales_stage, forecast_status "
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
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r["amount"],
            "detail": f"New to pipeline at {r['presales_stage'] or 'Untagged'}",
        })

    for key in prior_keys - current_keys:
        r = prior_states[key]
        deltas.append({
            "type": "dropped",
            "opportunity_name": r["opportunity_name"],
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
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
                "opportunity_url": opportunity_url(cur.get("opportunity_id")),
                "amount": cur["amount"],
                "detail": f"{prev['presales_stage'] or 'Untagged'} -> {cur['presales_stage'] or 'Untagged'}",
            })
        elif prev["forecast_status"] != cur["forecast_status"]:
            deltas.append({
                "type": "status_change",
                "opportunity_name": cur["opportunity_name"],
                "opportunity_url": opportunity_url(cur.get("opportunity_id")),
                "amount": cur["amount"],
                "detail": f"{prev['forecast_status'] or 'Untagged'} -> {cur['forecast_status'] or 'Untagged'}",
            })

    deltas.sort(key=lambda d: d.get("amount") or 0, reverse=True)
    return deltas


def build_slack_draft(preread):
    """Template-formatted Slack message for the weekly Tech Forecast call —
    deliberately not LLM-drafted (no LITELLM_API_KEY configured yet); every
    fact here already exists on the preread payload, so this is pure string
    formatting. Swapping in an LLM polish pass later (reusing reviews.py's
    _make_client) only needs to change this one function."""
    lines = [
        f"*Tech Forecast Call Prep — {datetime.now():%B} {datetime.now().day}, {datetime.now():%Y}*",
        "",
        preread["executive_takeaway"],
        "",
        "*Key metrics:*",
    ]

    m = preread["key_metrics"]
    lines += [
        f"- Total active pipeline: ${m['total_active_pipeline_amount']:,.0f} "
        f"({m['total_active_pipeline_count']} deals)",
        f"- Technical Wins secured: ${m['total_tech_won_amount']:,.0f} "
        f"({m['total_tech_won_pct']:.0%}, {m['total_tech_won_count']} deals)",
        f"- In active SE engagement: ${m['in_flight_amount']:,.0f} ({m['in_flight_count']} deals)",
        f"- Untagged, needs triage: ${m['untagged_amount']:,.0f} ({m['untagged_count']} deals)",
        "",
    ]

    top_deals = preread["top_deals"]
    lines.append("*Come ready to discuss:*")
    if top_deals:
        current_key = fiscal_quarter_sort_key(current_fiscal_quarter())
        next_key = _offset_quarter_key(current_key, 1)
        buckets = {"current": [], "next": [], "later": []}
        for d in top_deals:
            buckets.setdefault(d.get("quarter_bucket") or "later", buckets["later"]).append(d)

        # "current" and "next" are grouped by lead SE and sorted by each
        # SE's aggregate ARR in that bucket (highest first), per Claude
        # Leroux (2026-09-14) — "later" stays flat/amount-sorted like
        # before since the request only concerns the current/next split.
        grouped_section_specs = [
            ("current", f"*Current Quarter — {quarter_label(current_key)}*"),
            ("next", f"*Next Quarter — {quarter_label(next_key)}*"),
        ]
        for bucket_key, heading in grouped_section_specs:
            bucket_deals = buckets.get(bucket_key) or []
            if not bucket_deals:
                continue
            lines.append(heading)

            # Keyed by lowercased name so casing differences (e.g. "nic da
            # silva" vs "Nic Da Silva") group together rather than splitting
            # into separate sub-headings; display name uses the casing from
            # the first deal seen for that SE.
            se_groups = {}
            no_se_group = []
            for d in bucket_deals:
                lead_se_name = (d.get("lead_se_name") or "").strip()
                if not lead_se_name:
                    no_se_group.append(d)
                    continue
                key = lead_se_name.lower()
                slot = se_groups.setdefault(key, {"name": lead_se_name, "deals": []})
                slot["deals"].append(d)

            ordered_keys = sorted(
                se_groups,
                key=lambda key: sum(d["amount"] or 0 for d in se_groups[key]["deals"]),
                reverse=True,
            )

            for key in ordered_keys:
                name = se_groups[key]["name"]
                se_deals = se_groups[key]["deals"]
                se_arr = sum(d["amount"] or 0 for d in se_deals)
                alias = _SLACK_ALIAS_BY_NAME.get(key)
                mention = f" @{alias}" if alias else ""
                lines.append(f"*{name}*{mention} — ${se_arr:,.0f}")
                for d in se_deals:
                    lines.append(
                        f"- {_slack_opp_link(d)} — ${d['amount']:,.0f} "
                        f"({_stage_label(d['presales_stage'])})"
                    )
                    lines.append(f"  ↳ {d['discussion_question']}")

            if no_se_group:
                no_se_arr = sum(d["amount"] or 0 for d in no_se_group)
                lines.append(f"*No Lead SE on file* — ${no_se_arr:,.0f}")
                for d in no_se_group:
                    lines.append(
                        f"- {_slack_opp_link(d)} — ${d['amount']:,.0f} "
                        f"({_stage_label(d['presales_stage'])})"
                    )
                    lines.append(f"  ↳ {d['discussion_question']}")

        later_deals = buckets.get("later") or []
        if later_deals:
            lines.append("*Unscheduled / later:*")
            for d in later_deals[:5]:
                se = d["lead_se_name"] or "no Lead SE on file"
                lines.append(
                    f"- {_slack_opp_link(d)} — ${d['amount']:,.0f} "
                    f"({_stage_label(d['presales_stage'])}, SE: {se})"
                )
                lines.append(f"  ↳ {d['discussion_question']}")
    else:
        lines.append("- Nothing outstanding — pipeline is caught up.")
    lines.append("")

    missing_notes = preread["missing_notes"]
    if missing_notes:
        lines.append("*Missing notes — no next steps logged:*")
        for d in missing_notes:
            se = d["lead_se_name"] or "no Lead SE on file"
            lines.append(f"- {_slack_opp_link(d)} — ${d['amount']:,.0f} ({_stage_label(d['presales_stage'])}, SE: {se})")
        lines.append("")

    needs_lead_se = preread["needs_lead_se"]
    if needs_lead_se:
        lines.append("*Needs a Lead SE — please claim one if it's yours:*")
        for d in needs_lead_se:
            lines.append(f"- {_slack_opp_link(d)} — ${d['amount']:,.0f} (AE: {d['opportunity_owner'] or '-'})")
        lines.append("")

    lines.append("*Since last sync:*")
    deltas = preread["weekly_deltas"]
    if deltas:
        for d in deltas[:8]:
            lines.append(f"- {_slack_opp_link(d)}: {d['detail']}")
    else:
        lines.append("- No changes since last sync yet.")
    lines.append("")

    lines.append("See you Monday — come prepared with an update on your deals above. 🙌")
    lines.append("")
    lines.append(_MANTRA)
    return "\n".join(lines)


def build_preread(db, limit=10):
    with db.conn() as c:
        deal_rows = [dict(r) for r in c.execute("SELECT * FROM tech_forecast_deals").fetchall()]

    metrics = build_key_metrics(deal_rows)
    top_deals = build_top_deals(deal_rows, limit=limit)

    return {
        "executive_takeaway": build_executive_takeaway(metrics),
        "key_metrics": metrics,
        "breakdown": build_breakdown(deal_rows),
        "top_deals": top_deals,
        "weekly_deltas": build_weekly_deltas(db),
        "needs_lead_se": build_needs_lead_se(deal_rows),
        "missing_notes": build_missing_notes(deal_rows),
        "generated_at": datetime.now().isoformat(),
    }
