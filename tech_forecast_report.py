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

from attribution import ATTRIBUTED_SE_ID_SQL, EFFECTIVE_SE_ID_SQL, LEAD_SE_ID_SQL
from constants import FORECAST_RISK, PRESALES_TECH_WIN, STAGE_CLOSED_WON
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
    PRESALES_TECH_WIN: "Technical Win",
}

_STAGE_ORDER = {
    "2 - Discovery & Technical Qualification": 1,
    "3 - Technical Scoping": 2,
    "4 - Validate Solution": 3,
    "5 - Final Due Diligence": 4,
    PRESALES_TECH_WIN: 5,
}

_BUCKET_ORDER = {
    "Technical Win": 0,
    "Final Due Diligence": 1,
    "Validate Solution": 2,
    "Early Tech": 3,
    "Untagged": 4,
}

_EXCLUDED_TOP_DEAL_BUCKETS = ("Technical Win", "Final Due Diligence")

# Default cap for the list-shaped builders (SFDC updates, missing notes,
# needs-a-Lead-SE). These feed both an API response and a copy-pasted Slack
# message, so an uncapped list is a wall of text nobody reads — named rather
# than sliced inline so a caller can widen it deliberately.
DEFAULT_LIST_LIMIT = 25

# Sentinel returned by fiscal_quarter_sort_key() for a missing/unparseable
# label. Sorts *before* every real quarter, so any caller that groups by
# quarter must label or drop the undated bucket rather than emitting a
# leading `null`.
_UNKNOWN_QUARTER_KEY = (-1, -1)

# Display label for rows whose target/close date is missing or unparseable.
UNDATED_QUARTER_LABEL = "Undated"

_QUARTER_LABEL_RE = re.compile(r"^FY(\d{2})-Q([1-4])$")


def fiscal_quarter(iso_date):
    """Okta's fiscal year runs Feb 1 - Jan 31, named by its start year
    (e.g. FY26 = Feb 2026 - Jan 2027). Used for the Look Back grouping —
    unrelated to app.py's current_quarter()/sheets_sync.py's _quarter(),
    which are plain calendar quarters for a different feature (the open
    SFDC pipeline's "current quarter" filter)."""
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        # Both sync paths normalize dates, so this only fires on a hand-edited
        # row ('9/15/2026', free text). Treat it as undated rather than
        # raising: five endpoints group by fiscal quarter, and one bad cell
        # used to 500 all of them.
        return None
    fy_year = d.year if d.month >= 2 else d.year - 1
    fq = ((d.month - 2) % 12) // 3 + 1
    return f"FY{fy_year % 100:02d}-Q{fq}"


def fiscal_quarter_sort_key(label):
    """Higher key = more recent quarter. A missing or malformed label yields
    the _UNKNOWN_QUARTER_KEY sentinel, which sorts before every real quarter.
    Parsed with a strict regex rather than fixed slices — `label[-1]` read
    "FY26-Q10" as Q0, silently sorting it ahead of Q1."""
    m = _QUARTER_LABEL_RE.match(label or "")
    if not m:
        return _UNKNOWN_QUARTER_KEY
    return (int(m.group(1)), int(m.group(2)))


def _is_quarter_key(key):
    fy, q = key
    return fy >= 0 and 1 <= q <= 4


def quarter_label(key):
    """Format a (fy, q) sort-key tuple as a display label, e.g. FY26-Q3.
    Guards the unknown-quarter sentinel, which would otherwise format as the
    nonsense label "FY-1-Q-1"."""
    if not _is_quarter_key(key):
        return UNDATED_QUARTER_LABEL
    return f"FY{key[0]:02d}-Q{key[1]}"


def offset_quarter_key(key, n):
    """Shift a (fy, q) key by n quarters, e.g. (26, 3) + 1 -> (26, 4),
    (26, 4) + 1 -> (27, 1). Used to find "next quarter" relative to
    whatever quarter `key` represents. An unknown-quarter sentinel is
    returned unshifted — offsetting it produced keys like (-2, 4)."""
    if not _is_quarter_key(key):
        return key
    fy, q = key
    q += n
    while q > 4:
        q -= 4
        fy += 1
    while q < 1:
        q += 4
        fy -= 1
    return (fy, q)


# app.py still calls the pre-rename private name; keep it as an alias so the
# public helper can be promoted without touching that caller.
_offset_quarter_key = offset_quarter_key


def next_fiscal_quarter_label(label=None):
    """Display label for the quarter after `label` (today's fiscal quarter
    when omitted). Public entry point so callers don't have to chain
    fiscal_quarter_sort_key/offset_quarter_key/quarter_label themselves."""
    key = fiscal_quarter_sort_key(label or current_fiscal_quarter())
    return quarter_label(offset_quarter_key(key, 1))


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


def quarter_bucket_detailed(target_date):
    """Label a deal's target_tw_date as 'current', 'next', 'overdue' or
    'later' / None relative to today's fiscal quarter. 'overdue' means the
    target quarter has already closed — those are the most urgent deals on
    the board, so the SFDC-note drafts and the Slack draft must surface them
    rather than let them sink into the 'later' tail."""
    if not target_date:
        return None
    key = fiscal_quarter_sort_key(fiscal_quarter(target_date))
    if key == _UNKNOWN_QUARTER_KEY:
        return None  # unparseable date — same as carrying no date at all
    current_key = fiscal_quarter_sort_key(current_fiscal_quarter())
    if key == current_key:
        return "current"
    if key == offset_quarter_key(current_key, 1):
        return "next"
    return "overdue" if key < current_key else "later"


def quarter_bucket(target_date):
    """Three-way 'current'/'next'/'later' bucket — 'later' covers both future
    and already-passed quarters. Kept as-is for app.py, which layers its own
    overdue refinement on top of this return value; new code in this module
    calls quarter_bucket_detailed() instead."""
    bucket = quarter_bucket_detailed(target_date)
    return "later" if bucket == "overdue" else bucket


def _money(amount):
    """Format a nullable amount as "$1,234". `tech_forecast_deals.amount` is
    nullable — a blank sheet cell syncs as None — and f"${None:,.0f}" raises
    TypeError, which 500'd the Slack-draft endpoint whenever one deal on the
    board had no amount yet."""
    return f"${amount or 0:,.0f}"


def _target_tw_date(row):
    """A deal's target Technical Win date: the explicit Tech Win Date when
    set, else the commercial Close Date."""
    return row.get("technical_win_date") or row.get("close_date")


def _by_amount_desc(rows):
    """Highest-$ first, tie-broken on a stable identity. The preread query has
    no ORDER BY, so SQLite's row order is arbitrary — without the secondary
    key, equal-amount deals (two blanks, two round numbers) swap places
    between otherwise identical runs of the same draft."""
    return sorted(
        rows,
        key=lambda r: (
            -(r.get("amount") or 0),
            (r.get("opportunity_name") or "").lower(),
            r.get("sheet_key") or r.get("opportunity_id") or "",
        ),
    )


def effective_se_display_name(row):
    """The SE a deal should be *presented* under: the rep resolved by
    attribution's three-step precedence (manual assignment > sheet Lead SE
    name > opportunity-name join), falling back to the sheet's raw Lead SE
    text for names that aren't `se_reps` rows at all (Mary Greenlee, departed
    reps). Empty string only when nothing resolves — that, and only that, is
    the "No Lead SE on file" case."""
    return (row.get("effective_se_name") or row.get("lead_se_name") or "").strip()


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


# Stage bucket -> key-metric class. Shared by build_key_metrics (live rows)
# and build_arr_trend (re-derived snapshot totals) so the two can't drift:
# they're the same numbers, one from today's rows and one from history.
_METRIC_CLASSES = {
    "Technical Win": "won",
    "Validate Solution": "in_flight",
    "Final Due Diligence": "in_flight",
    "Untagged": "untagged",
}


def metric_class(bucket):
    """'won' / 'in_flight' / 'untagged' for a stage bucket, else None."""
    return _METRIC_CLASSES.get(bucket)


def build_key_metrics(deal_rows):
    totals = {cls: {"amount": 0.0, "count": 0} for cls in ("won", "in_flight", "untagged")}
    total_amount = 0.0
    total_count = 0

    # One pass: stage_bucket() used to be recomputed ~4x per row across four
    # separate list comprehensions over the same list.
    for r in deal_rows:
        amount = r.get("amount") or 0
        total_amount += amount
        total_count += 1
        slot = totals.get(metric_class(stage_bucket(r.get("presales_stage"))))
        if slot is not None:
            slot["amount"] += amount
            slot["count"] += 1

    won, in_flight, untagged = totals["won"], totals["in_flight"], totals["untagged"]
    return {
        "total_active_pipeline_amount": total_amount,
        "total_active_pipeline_count": total_count,
        "total_tech_won_amount": won["amount"],
        "total_tech_won_count": won["count"],
        "total_tech_won_pct": (won["amount"] / total_amount) if total_amount else 0.0,
        "in_flight_amount": in_flight["amount"],
        "in_flight_count": in_flight["count"],
        "untagged_amount": untagged["amount"],
        "untagged_count": untagged["count"],
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
        totals = {cls: {"amount": 0.0, "count": 0} for cls in ("won", "in_flight", "untagged")}
        total_amount = 0.0
        total_count = 0
        for stage_slots in buckets.values():
            for bucket, slot in stage_slots.items():
                amount, count = slot.get("amount", 0), slot.get("count", 0)
                total_amount += amount
                total_count += count
                # Same classifier build_key_metrics uses — the duplicated
                # if/elif chain here drifted out of sync too easily.
                cls = totals.get(metric_class(bucket))
                if cls is not None:
                    cls["amount"] += amount
                    cls["count"] += count
        trend.append({
            "snapshot_date": row["snapshot_date"],
            "total_amount": total_amount,
            "total_count": int(total_count),
            "tech_won_amount": totals["won"]["amount"],
            "tech_won_count": int(totals["won"]["count"]),
            "in_flight_amount": totals["in_flight"]["amount"],
            "in_flight_count": int(totals["in_flight"]["count"]),
            "untagged_amount": totals["untagged"]["amount"],
            "untagged_count": int(totals["untagged"]["count"]),
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
    close_date, same precedence as build_top_deals.

    Two counting rules, both of which used to be missing:

    * **Dedupe.** A won deal lives in `closed_deals` (tech_win=1) *and* stays
      in `tech_forecast_deals` at Technical Win / Closed-Won — a state
      build_sfdc_updates already filters for — so its ARR and count landed in
      the quarter twice. Open rows already seen in the closed set, or already
      marked Closed/Won, are skipped. Callers should therefore select
      `opportunity_id`/`opportunity_name` and `sales_stage` on both sides;
      when neither identifier is present the match falls back to
      (amount, close_date), which is the only signal left.
    * **Closed/Won only for revenue.** `closed_deals` holds Won *and* Lost
      rows, so a technical win that closed Lost stays visible in `count`
      (it happened) but is excluded from `amount` and reported separately as
      `closed_lost_count`. Rows with no `sales_stage` column selected can't
      be classified and are treated as won, as before.
    """
    by_quarter = {}
    seen = set()

    def _identity(r):
        opp_id = r.get("opportunity_id")
        if opp_id:
            return ("id", str(opp_id))
        name = (r.get("opportunity_name") or "").strip().lower()
        if name:
            return ("name", name)
        amount = r.get("amount")
        if amount and r.get("close_date"):
            return ("amount_date", amount, r["close_date"])
        return None

    def _add(quarter, amount, is_revenue):
        slot = by_quarter.setdefault(
            quarter, {"amount": 0.0, "count": 0, "closed_lost_count": 0}
        )
        slot["count"] += 1
        if is_revenue:
            slot["amount"] += amount
        else:
            slot["closed_lost_count"] += 1

    for r in closed_win_rows:
        identity = _identity(r)
        if identity:
            seen.add(identity)
        stage = r.get("sales_stage")
        _add(
            fiscal_quarter(r.get("close_date")),
            r.get("amount") or 0,
            stage is None or stage == STAGE_CLOSED_WON,
        )

    for r in open_win_rows:
        if r.get("sales_stage") == STAGE_CLOSED_WON:
            continue  # already counted out of closed_deals
        identity = _identity(r)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        _add(fiscal_quarter(_target_tw_date(r)), r.get("amount") or 0, True)

    # Undated rows used to emit a `fiscal_quarter: null` bucket that sorted
    # ahead of every real quarter (the (-1,-1) sentinel), drawing an
    # unlabeled leading bar on the Dashboard. Label it and sort it last.
    undated = by_quarter.pop(None, None)
    trend = [
        {"fiscal_quarter": q, **by_quarter[q]}
        for q in sorted(by_quarter, key=fiscal_quarter_sort_key)
    ]
    if undated:
        trend.append({"fiscal_quarter": UNDATED_QUARTER_LABEL, **undated})
    return trend


_STAGE_QUESTIONS = {
    "1 - Assigned": "Newly assigned — curious what's driving the urgency here. What's the compelling event?",
    "2 - Discovery & Technical Qualification": "How's discovery going — what outcomes are resonating, and do we have a Champion yet?",
    "3 - Technical Scoping": "How are our capabilities lining up with their decision criteria so far?",
    "4 - Validate Solution": "Are we landing the \"how we do it better\" story — any proof points clicking with the economic buyer?",
    "5 - Final Due Diligence": "What's left on the decision/paper process side before we get to close?",
    PRESALES_TECH_WIN: "Anything on decision criteria or champion support worth keeping an eye on before close?",
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
    if row.get("forecast_status") == FORECAST_RISK:
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
    by SE. "overdue" (target quarter already closed) gets the per-quarter cap
    too — those are the deals most in need of airtime, and they used to be
    capped away inside "later"."""
    if per_quarter_limit is None:
        per_quarter_limit = max(limit, 15)
    candidates = [
        r for r in deal_rows
        if stage_bucket(r.get("presales_stage")) not in _EXCLUDED_TOP_DEAL_BUCKETS
    ]

    grouped = {"overdue": [], "current": [], "next": [], "later": []}
    for r in candidates:
        bucket = quarter_bucket_detailed(_target_tw_date(r)) or "later"
        grouped[bucket if bucket in grouped else "later"].append(r)

    selected = (
        _by_amount_desc(grouped["overdue"])[:per_quarter_limit]
        + _by_amount_desc(grouped["current"])[:per_quarter_limit]
        + _by_amount_desc(grouped["next"])[:per_quarter_limit]
        + _by_amount_desc(grouped["later"])[:limit]
    )

    result = []
    for r in selected:
        target_tw_date = _target_tw_date(r)
        result.append({
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            # Normalized to 0 rather than passed through as None: every
            # consumer (Slack draft, page) formats this as money.
            "amount": r.get("amount") or 0,
            "presales_stage": r.get("presales_stage"),
            "forecast_status": r.get("forecast_status"),
            "opportunity_owner": r.get("opportunity_owner"),
            "lead_se_name": r.get("lead_se_name") or "",
            "effective_se_name": effective_se_display_name(r),
            "pre_sales_notes": r.get("pre_sales_notes") or "",
            "se_manager_notes": r.get("se_manager_notes") or "",
            "pre_sales_next_steps": r.get("pre_sales_next_steps") or "",
            "notes_stale": bool(r.get("notes_stale")),
            "target_tw_date": target_tw_date,
            "target_fiscal_quarter": fiscal_quarter(target_tw_date),
            "quarter_bucket": quarter_bucket_detailed(target_tw_date),
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

    if row.get("presales_stage") == PRESALES_TECH_WIN:
        message = (
            f"Technical Win is confirmed. Commercial stage is "
            f"{_stage_label(row.get('sales_stage'))} — no further pre-sales "
            f"action needed unless something changes."
        )
    else:
        se_note = _latest_note_entry(row.get("se_manager_notes"))
        presales_note = _latest_note_entry(row.get("pre_sales_notes"))
        next_steps = (row.get("pre_sales_next_steps") or "").strip()

        if se_note:
            message = f"Latest SE Manager note: {se_note}"
        elif presales_note:
            message = f"No SE Manager note logged yet. Latest Pre-Sales note: {presales_note}"
        elif next_steps:
            message = f"No notes logged yet — next step on file: {next_steps}"
        else:
            message = f"No notes logged yet for {opp} — worth a quick sync with the SE before the next forecast call."

    return f"CL {date.today():%m/%d/%Y} : {message}"


# Buckets worth drafting an SFDC note for. "overdue" leads: a deal whose
# target Tech Win date has already passed is the most urgent one on the
# board, and under the old three-way quarter_bucket() it resolved to "later"
# and produced no draft at all.
_SFDC_UPDATE_BUCKETS = ("overdue", "current", "next")


def build_sfdc_updates(deal_rows, limit=DEFAULT_LIST_LIMIT):
    candidates = [
        r for r in deal_rows
        if r.get("sales_stage") != STAGE_CLOSED_WON
        and quarter_bucket_detailed(_target_tw_date(r)) in _SFDC_UPDATE_BUCKETS
    ]
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount") or 0,
            "presales_stage": r.get("presales_stage"),
            "sales_stage": r.get("sales_stage"),
            "lead_se_name": r.get("lead_se_name") or "",
            "effective_se_name": effective_se_display_name(r),
            "target_fiscal_quarter": fiscal_quarter(_target_tw_date(r)),
            "quarter_bucket": quarter_bucket_detailed(_target_tw_date(r)),
            "proposed_note": draft_sfdc_note(r),
        }
        for r in _by_amount_desc(candidates)[:limit]
    ]


def build_missing_notes(deal_rows, limit=DEFAULT_LIST_LIMIT):
    """Open deals (not yet a Technical Win) with no Pre-Sales Next Steps
    logged at all — a stronger, more urgent signal than `notes_stale`
    (which just means an existing next step hasn't changed)."""
    candidates = [
        r for r in deal_rows
        if r.get("presales_stage") != PRESALES_TECH_WIN
        and not (r.get("pre_sales_next_steps") or "").strip()
    ]
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount") or 0,
            "presales_stage": r.get("presales_stage"),
            "lead_se_name": r.get("lead_se_name") or "",
            "effective_se_name": effective_se_display_name(r),
        }
        for r in _by_amount_desc(candidates)[:limit]
    ]


def build_needs_lead_se(deal_rows, limit=DEFAULT_LIST_LIMIT):
    """Deals the sheet itself has no Lead SE set for yet — the literal
    "-" group, independent of any manual override or opportunity-name-join
    fallback the app might otherwise resolve. Deliberately reads the RAW
    `lead_se_name`, not the attribution-resolved effective name: this is the
    step-0 "nobody typed an SE into the sheet" signal, and resolving it would
    hide exactly the rows it exists to surface."""
    candidates = [r for r in deal_rows if not r.get("lead_se_name")]
    return [
        {
            "opportunity_name": r.get("opportunity_name"),
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount") or 0,
            "presales_stage": r.get("presales_stage"),
            "forecast_status": r.get("forecast_status"),
            "opportunity_owner": r.get("opportunity_owner"),
        }
        for r in _by_amount_desc(candidates)[:limit]
    ]


def build_executive_takeaway(metrics):
    return (
        f"Technical pipeline stands at {_money(metrics['total_active_pipeline_amount'])} "
        f"across {metrics['total_active_pipeline_count']} active opportunities. "
        f"{_money(metrics['total_tech_won_amount'])} ({metrics['total_tech_won_pct']:.0%}) is "
        f"already secured as Technical Wins, with {metrics['in_flight_count']} deals "
        f"({_money(metrics['in_flight_amount'])}) in active SE engagement (Validate Solution / "
        f"Final Due Diligence). {metrics['untagged_count']} deals "
        f"({_money(metrics['untagged_amount'])}) are untagged and need SE Manager triage."
    )


def build_weekly_deltas(current_rows, prior_states):
    """Diff the deal rows the caller already holds against `prior_states` —
    the previous snapshot's parsed `deal_states_json`, or None when there's no
    earlier snapshot to diff against.

    Pure, like the rest of this module: it used to take `db` and re-read
    `tech_forecast_deals` in a second transaction, so a sync landing mid-
    request could leave the deltas describing a different set of rows than the
    metrics in the same response."""
    if not prior_states:
        return []

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
            "amount": r.get("amount") or 0,
            "detail": f"New to pipeline at {r['presales_stage'] or 'Untagged'}",
        })

    for key in prior_keys - current_keys:
        r = prior_states[key]
        deltas.append({
            "type": "dropped",
            "opportunity_name": r["opportunity_name"],
            "opportunity_url": opportunity_url(r.get("opportunity_id")),
            "amount": r.get("amount") or 0,
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
                "amount": cur.get("amount") or 0,
                "detail": f"{prev['presales_stage'] or 'Untagged'} -> {cur['presales_stage'] or 'Untagged'}",
            })
        elif prev["forecast_status"] != cur["forecast_status"]:
            deltas.append({
                "type": "status_change",
                "opportunity_name": cur["opportunity_name"],
                "opportunity_url": opportunity_url(cur.get("opportunity_id")),
                "amount": cur.get("amount") or 0,
                "detail": f"{prev['forecast_status'] or 'Untagged'} -> {cur['forecast_status'] or 'Untagged'}",
            })

    return _by_amount_desc(deltas)


# Per-section caps for the copy-pasted draft. Named (and overridable) rather
# than sliced inline: the lists these read are already capped by
# build_preread, but build_slack_draft also accepts a preread built elsewhere.
SLACK_LATER_LIMIT = 5
SLACK_LIST_LIMIT = 10
SLACK_DELTA_LIMIT = 8


def _deal_bullet(d, show_se=False):
    """The draft's one deal-bullet shape: opportunity, ARR, stage, optional
    SE, then the discussion question underneath. Rendered identically in the
    per-SE groups, the no-Lead-SE group and the unscheduled tail — it was
    copy-pasted three times, which is how the `${amount:,.0f}` NULL crash got
    three chances to fire."""
    suffix = ""
    if show_se:
        suffix = f", SE: {effective_se_display_name(d) or 'no Lead SE on file'}"
    return [
        f"- {_slack_opp_link(d)} — {_money(d.get('amount'))} "
        f"({_stage_label(d.get('presales_stage'))}{suffix})",
        f"  ↳ {d['discussion_question']}",
    ]


def _group_by_se(deals):
    """(ordered [(display_name, deals)], deals with no SE at all).

    Keyed by lowercased name so casing differences (e.g. "nic da silva" vs
    "Nic Da Silva") group together rather than splitting into separate
    sub-headings; display name uses the casing from the first deal seen for
    that SE. Groups on the attribution-resolved name, not the sheet's raw
    Lead SE column — a deal Claude Leroux assigned by hand in the UI used to
    render under "No Lead SE on file" and leave its ARR out of that SE's
    subtotal."""
    se_groups = {}
    no_se_group = []
    for d in deals:
        name = effective_se_display_name(d)
        if not name:
            no_se_group.append(d)
            continue
        slot = se_groups.setdefault(name.lower(), {"name": name, "deals": []})
        slot["deals"].append(d)

    ordered = sorted(
        se_groups.items(),
        key=lambda kv: (-sum(d.get("amount") or 0 for d in kv[1]["deals"]), kv[0]),
    )
    return ordered, no_se_group


def build_slack_draft(preread, later_limit=SLACK_LATER_LIMIT,
                      list_limit=SLACK_LIST_LIMIT, delta_limit=SLACK_DELTA_LIMIT):
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
        f"- Total active pipeline: {_money(m['total_active_pipeline_amount'])} "
        f"({m['total_active_pipeline_count']} deals)",
        f"- Technical Wins secured: {_money(m['total_tech_won_amount'])} "
        f"({m['total_tech_won_pct']:.0%}, {m['total_tech_won_count']} deals)",
        f"- In active SE engagement: {_money(m['in_flight_amount'])} ({m['in_flight_count']} deals)",
        f"- Untagged, needs triage: {_money(m['untagged_amount'])} ({m['untagged_count']} deals)",
        "",
    ]

    top_deals = preread["top_deals"]
    lines.append("*Come ready to discuss:*")
    if top_deals:
        current_key = fiscal_quarter_sort_key(current_fiscal_quarter())
        next_key = offset_quarter_key(current_key, 1)
        buckets = {"overdue": [], "current": [], "next": [], "later": []}
        for d in top_deals:
            bucket = d.get("quarter_bucket") or "later"
            buckets[bucket if bucket in buckets else "later"].append(d)

        # "overdue"/"current"/"next" are grouped by SE and sorted by each
        # SE's aggregate ARR in that bucket (highest first), per Claude
        # Leroux (2026-09-14) — "later" stays flat/amount-sorted like
        # before since the request only concerns the current/next split.
        # Overdue leads: a passed target date is more urgent than either.
        grouped_section_specs = [
            ("overdue", "*Overdue — target Tech Win date has passed*"),
            ("current", f"*Current Quarter — {quarter_label(current_key)}*"),
            ("next", f"*Next Quarter — {quarter_label(next_key)}*"),
        ]
        for bucket_key, heading in grouped_section_specs:
            bucket_deals = buckets.get(bucket_key) or []
            if not bucket_deals:
                continue
            lines.append(heading)

            ordered, no_se_group = _group_by_se(bucket_deals)
            for key, group in ordered:
                se_arr = sum(d.get("amount") or 0 for d in group["deals"])
                alias = _SLACK_ALIAS_BY_NAME.get(key)
                mention = f" @{alias}" if alias else ""
                lines.append(f"*{group['name']}*{mention} — {_money(se_arr)}")
                for d in group["deals"]:
                    lines += _deal_bullet(d)

            if no_se_group:
                no_se_arr = sum(d.get("amount") or 0 for d in no_se_group)
                lines.append(f"*No Lead SE on file* — {_money(no_se_arr)}")
                for d in no_se_group:
                    lines += _deal_bullet(d)

        later_deals = buckets.get("later") or []
        if later_deals:
            lines.append("*Unscheduled / later:*")
            for d in later_deals[:later_limit]:
                lines += _deal_bullet(d, show_se=True)
    else:
        lines.append("- Nothing outstanding — pipeline is caught up.")
    lines.append("")

    missing_notes = preread["missing_notes"]
    if missing_notes:
        lines.append("*Missing notes — no next steps logged:*")
        for d in missing_notes[:list_limit]:
            se = effective_se_display_name(d) or "no Lead SE on file"
            lines.append(
                f"- {_slack_opp_link(d)} — {_money(d.get('amount'))} "
                f"({_stage_label(d.get('presales_stage'))}, SE: {se})"
            )
        lines.append("")

    needs_lead_se = preread["needs_lead_se"]
    if needs_lead_se:
        lines.append("*Needs a Lead SE — please claim one if it's yours:*")
        for d in needs_lead_se[:list_limit]:
            lines.append(
                f"- {_slack_opp_link(d)} — {_money(d.get('amount'))} "
                f"(AE: {d.get('opportunity_owner') or '-'})"
            )
        lines.append("")

    lines.append("*Since last sync:*")
    deltas = preread["weekly_deltas"]
    if deltas:
        for d in deltas[:delta_limit]:
            lines.append(f"- {_slack_opp_link(d)}: {d['detail']}")
    else:
        lines.append("- No changes since last sync yet.")
    lines.append("")

    lines.append("See you Monday — come prepared with an update on your deals above. 🙌")
    lines.append("")
    lines.append(_MANTRA)
    return "\n".join(lines)


# Every preread row carries the SE that attribution resolves for it, not just
# the sheet's raw Lead SE column: the manual assignment made from the Tech
# Forecast page (step 1) and the opportunity-name join (step 3) were invisible
# here, so an assigned deal rendered under "No Lead SE on file" in the Monday
# message and its ARR was missing from that SE's subtotal. The precedence
# itself lives in attribution.py — this is the third query site to need it.
# The name lookup wraps the id resolution so EFFECTIVE_SE_ID_SQL is evaluated
# once per row rather than again per name.
_PREREAD_DEALS_SQL = f"""
    SELECT t.*,
        (SELECT r3.name FROM se_reps r3 WHERE r3.id = t.effective_se_rep_id) AS effective_se_name
    FROM (
        SELECT tf.*,
            {LEAD_SE_ID_SQL} AS lead_se_rep_id,
            {ATTRIBUTED_SE_ID_SQL} AS attributed_se_id,
            {EFFECTIVE_SE_ID_SQL} AS effective_se_rep_id
        FROM tech_forecast_deals tf
    ) t
"""


def build_preread(db, limit=10, list_limit=DEFAULT_LIST_LIMIT):
    today = date.today().isoformat()
    with db.conn() as c:
        deal_rows = [dict(r) for r in c.execute(_PREREAD_DEALS_SQL).fetchall()]
        # Same transaction as the rows above, and only the one column the diff
        # needs (deal_states_json is a full per-deal blob). build_weekly_deltas
        # used to re-read the whole deals table in a second transaction, so a
        # sync landing mid-request could make the two halves of one response
        # describe different data.
        prior = c.execute(
            "SELECT deal_states_json FROM tech_forecast_snapshots WHERE snapshot_date < ? "
            "ORDER BY snapshot_date DESC LIMIT 1",
            (today,),
        ).fetchone()

    prior_states = json.loads(prior["deal_states_json"]) if prior else None
    metrics = build_key_metrics(deal_rows)
    top_deals = build_top_deals(deal_rows, limit=limit)

    return {
        "executive_takeaway": build_executive_takeaway(metrics),
        "key_metrics": metrics,
        "breakdown": build_breakdown(deal_rows),
        "top_deals": top_deals,
        "weekly_deltas": build_weekly_deltas(deal_rows, prior_states),
        "needs_lead_se": build_needs_lead_se(deal_rows, limit=list_limit),
        "missing_notes": build_missing_notes(deal_rows, limit=list_limit),
        "generated_at": datetime.now().isoformat(),
    }
