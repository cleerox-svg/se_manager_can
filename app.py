import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import reviews
import sheets_sync
import slack_sync
import tech_forecast_report as report
import top_items
from attribution import (
    ATTRIBUTED_SE_ID_SQL,
    EFFECTIVE_SE_ID_SQL,
    LEAD_SE_ID_SQL,
    effective_se_id,
)
from constants import PRESALES_TECH_WIN, STAGE_CLOSED_WON
from db import Database
from salesforce_links import opportunity_url

load_dotenv()

# Without this the app logs nothing at all — tracebacks were being swallowed by
# the `except Exception: return str(e)` handlers below and never written down.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

DATABASE_PATH = os.environ.get("DATABASE_PATH", "se_manager_hub.db")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
SHEET_ID = os.environ.get("SHEET_ID", "")
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN", "")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "https://llm.atko.ai")

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

app = Flask(__name__, static_folder=FRONTEND_DIST, static_url_path="")
app.config["JSON_SORT_KEYS"] = False

db = Database(DATABASE_PATH)
db.init()


def current_quarter() -> str:
    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


def current_half() -> str:
    now = datetime.now()
    half = 1 if now.month <= 6 else 2
    return f"{now.year}-H{half}"


@app.errorhandler(Exception)
def handle_error(e):
    """Every client here is a `fetch()` in the React SPA, which parses the body
    as JSON — Werkzeug's default HTML error page surfaces as an unhelpful parse
    error instead of the actual failure. Deliberately generic: exception text can
    carry a service-account path or a token fragment, so the detail goes to the
    log and only a status-appropriate message goes to the browser."""
    if isinstance(e, HTTPException):
        # 4xx raised by abort() — the description is ours, written for the user.
        return jsonify({"error": e.description}), e.code
    app.logger.exception("Unhandled error handling %s %s", request.method, request.path)
    return jsonify({"error": "Internal server error"}), 500


def _json_body() -> dict:
    """JSON body as a dict. `get_json(force=True)` raises on a malformed body and
    returns a non-dict for `null`/`[]`, both of which then blew up on `.get()`."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    # An absent body is a legitimate "just use the defaults" call. A body that
    # was actually sent but didn't parse as an object is a caller bug: folding
    # it into {} let a garbage POST to /api/top-items silently save an empty
    # entry and report success.
    if data is None and not request.get_data():
        return {}
    abort(400, description="Request body must be a JSON object")


def _int_arg(name: str, default: int, minimum: int = 1, maximum: int = 100) -> int:
    """Bounded int query param. Unparseable values fall back to the default
    rather than 500ing, and the clamp keeps `?limit=100000` from running an
    unbounded query on a caller's typo."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _rep_id_field(data: dict, key: str = "se_rep_id"):
    """Optional SE rep id from a request body, as an int or None.

    A bare string would never match the INTEGER column (SQLite compares
    '3' = 3 as false) and a bogus id trips the foreign key into a 500, so the
    value is coerced here and its existence checked by the caller."""
    raw = data.get(key)
    if raw is None or raw == "" or raw == 0:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        abort(400, description=f"{key} must be an integer id or null")


def _assert_rep_exists(c, se_rep_id):
    if se_rep_id is None:
        return
    if not c.execute("SELECT 1 FROM se_reps WHERE id = ?", (se_rep_id,)).fetchone():
        abort(400, description=f"No SE rep with id {se_rep_id}")


@app.route("/")
def index():
    # Phase 6 cutover: serves the Vite-built React app from frontend/dist.
    # Hashed assets under frontend/dist/assets/ and root files (favicon.svg,
    # icons.svg) are served by Flask's static handler above, since
    # static_url_path="" maps them at the same root paths index.html expects.
    return send_from_directory(app.static_folder, "index.html")


# ── Settings ─────────────────────────────────────────────────────────────
@app.route("/api/settings")
def get_settings():
    return jsonify({
        "google_sheets_configured": bool(SHEET_ID) and os.path.exists(GOOGLE_SERVICE_ACCOUNT_JSON),
        "slack_configured": bool(SLACK_USER_TOKEN),
        "litellm_configured": bool(LITELLM_API_KEY),
        "sheet_id": SHEET_ID,
        "deals_last_synced_at": db.get_setting("deals_last_synced_at"),
        "current_quarter": current_quarter(),
        "current_review_period": current_half(),
    })


# ── SE reps ──────────────────────────────────────────────────────────────
@app.route("/api/reps")
def list_reps():
    period = current_half()
    with db.conn() as c:
        rows = c.execute(f"""
            SELECT r.*,
                (SELECT COUNT(*) FROM deals d WHERE d.se_rep_id = r.id) AS deal_count,
                (SELECT COALESCE(SUM(amount), 0) FROM closed_deals cd
                    WHERE cd.se_rep_id = r.id
                    AND cd.sales_stage = ?) AS arr_total,
                -- tech_forecast_arr sums tech_forecast_deals, not closed_deals, so it's
                -- unaffected by the mixed Won+Lost closed_deals data (see CLAUDE.md).
                -- Attribution is the shared three-step precedence from attribution.py —
                -- the hand-written copy that used to live here is exactly how this query
                -- drifted from /api/tech-forecast and reported $0 for reps attributed by
                -- override or Lead SE name.
                (SELECT COALESCE(SUM(tf.amount), 0) FROM tech_forecast_deals tf
                    WHERE r.id = {EFFECTIVE_SE_ID_SQL}
                ) AS tech_forecast_arr,
                rv.status AS review_status,
                rv.content AS review_content
            FROM se_reps r
            LEFT JOIN reviews rv ON rv.se_rep_id = r.id AND rv.period = ?
            ORDER BY r.active DESC, r.name
        """, (STAGE_CLOSED_WON, period)).fetchall()
    return jsonify([dict(r) | {"review_period": period} for r in rows])


def _coerce_active(value):
    """`active` decides who counts as a current direct report (CLAUDE.md's
    departed-rep rule), so it must land as a real 0/1 — SQLite would happily
    store the string "false" in the INTEGER column, and that reads as truthy."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return 1 if value else 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes"):
            return 1
        if v in ("0", "false", "no", ""):
            return 0
    abort(400, description="active must be a boolean or 0/1")


def _coerce_arr_target(value):
    """REAL column, but SQLite's type affinity accepts a string verbatim — a
    stray "2.5M" would then break every ARR-goal comparison silently."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        abort(400, description="arr_target must be a number or null")
    if isinstance(value, (int, float)):
        target = float(value)
    elif isinstance(value, str):
        try:
            target = float(value.strip())
        except ValueError:
            abort(400, description="arr_target must be a number or null")
    else:
        abort(400, description="arr_target must be a number or null")
    if target < 0:
        abort(400, description="arr_target must not be negative")
    return target


_REP_FIELD_COERCERS = {
    "active": _coerce_active,
    "arr_target": _coerce_arr_target,
}

# Text columns: stored as-is, but only after a scalar check — a dict or list
# would otherwise reach sqlite3 as an unsupported type and 500.
_REP_TEXT_FIELDS = ("slack_user_id", "email", "title", "notes",
                    "product", "segment", "coverage_role", "region")


@app.route("/api/reps/<int:rep_id>", methods=["POST"])
def update_rep(rep_id):
    data = _json_body()
    fields, values = [], []
    for key in (*_REP_FIELD_COERCERS, *_REP_TEXT_FIELDS):
        if key not in data:
            continue
        value = data[key]
        coerce = _REP_FIELD_COERCERS.get(key)
        if coerce:
            value = coerce(value)
        elif not isinstance(value, (str, int, float, type(None))) or isinstance(value, bool):
            abort(400, description=f"{key} must be a string or null")
        fields.append(f"{key} = ?")
        values.append(value)
    if fields:
        with db.conn() as c:
            cur = c.execute(
                f"UPDATE se_reps SET {', '.join(fields)} WHERE id = ?", (*values, rep_id)
            )
            if cur.rowcount == 0:
                abort(404, description=f"No SE rep with id {rep_id}")
    return jsonify({"ok": True})


@app.route("/api/reps/<int:rep_id>/deals")
def rep_deals(rep_id):
    with db.conn() as c:
        rows = c.execute("SELECT * FROM deals WHERE se_rep_id = ? ORDER BY close_date", (rep_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/reps/<int:rep_id>/slack")
def rep_slack(rep_id):
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM slack_notes WHERE se_rep_id = ? ORDER BY posted_at DESC LIMIT 200", (rep_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── Deals ────────────────────────────────────────────────────────────────
@app.route("/api/deals")
def list_deals():
    quarter = request.args.get("quarter", "current")
    stage = request.args.get("stage")
    search = request.args.get("search")

    clauses, params = [], []
    if quarter == "current":
        clauses.append("quarter = ?")
        params.append(current_quarter())
    elif quarter and quarter != "all":
        clauses.append("quarter = ?")
        params.append(quarter)
    if stage:
        clauses.append("stage = ?")
        params.append(stage)
    if search:
        clauses.append("opportunity_name LIKE ?")
        params.append(f"%{search}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db.conn() as c:
        rows = c.execute(f"SELECT * FROM deals {where} ORDER BY close_date", params).fetchall()
        quarters = c.execute(
            "SELECT DISTINCT quarter FROM deals WHERE quarter IS NOT NULL ORDER BY quarter"
        ).fetchall()

    return jsonify({
        "deals": [dict(r) for r in rows],
        "quarters": [q["quarter"] for q in quarters],
        "current_quarter": current_quarter(),
    })


# ── Technical Forecast ──────────────────────────────────────────────────
@app.route("/api/tech-forecast")
def tech_forecast():
    with db.conn() as c:
        # SE-attribution precedence: (1) assigned_se_rep_id — Claude Leroux's manual
        # override, always wins; (2) the sheet's own Lead Sales Engineer column,
        # resolved by case-insensitive name match against se_reps; (3) an opportunity-
        # name join against `deals.se_rep_id`, kept as a fallback for rows the sheet
        # hasn't attributed yet; (4) "Unassigned". `needs_lead_se` is reported
        # separately from all of that — it's the literal "sheet has no Lead SE set"
        # signal, independent of whatever attribution the app manages to resolve.
        deal_rows = c.execute(f"""
            SELECT tf.*,
                {LEAD_SE_ID_SQL} AS lead_se_rep_id,
                {ATTRIBUTED_SE_ID_SQL} AS attributed_se_id
            FROM tech_forecast_deals tf
            ORDER BY tf.amount DESC
        """).fetchall()
        # tech_win = 1 alone, deliberately: a technical win can precede a
        # commercial loss and those stay visible in the Look Back (CLAUDE.md).
        # sales_stage rides along so each row can be labelled won/lost below
        # instead of the UI assuming "not Closed/Won" means "still open".
        closed_wins = c.execute(
            "SELECT * FROM closed_deals WHERE tech_win = 1 ORDER BY amount DESC"
        ).fetchall()
        reps_by_id = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM se_reps")}

    deals = []
    for r in deal_rows:
        d = dict(r)
        se_id = effective_se_id(d)
        d["attributed_se_name"] = reps_by_id.get(d["attributed_se_id"])
        d["effective_se_rep_id"] = se_id
        d["effective_se_name"] = reps_by_id.get(se_id, "Unassigned") if se_id else "Unassigned"
        d["needs_lead_se"] = not se_id
        d["opportunity_url"] = opportunity_url(d["opportunity_id"])

        # quarter_bucket() only distinguishes current/next/later — "later" also
        # catches deals whose target date already passed. Add "overdue" as a
        # local refinement on top, without touching quarter_bucket() itself
        # (it also powers build_top_deals/build_sfdc_updates/build_slack_draft).
        target_tw_date = d["technical_win_date"] or d["close_date"]
        bucket = report.quarter_bucket(target_tw_date)
        if bucket == "later" and target_tw_date:
            target_key = report.fiscal_quarter_sort_key(report.fiscal_quarter(target_tw_date))
            current_key = report.fiscal_quarter_sort_key(report.current_fiscal_quarter())
            if target_key < current_key:
                bucket = "overdue"
        d["target_tw_date"] = target_tw_date
        d["quarter_bucket"] = bucket

        deals.append(d)

    recent_wins = [
        dict(r) | {"source": "closed", "win_date": r["close_date"], "notes_stale": False}
        for r in closed_wins
    ]
    recent_wins += [
        r | {"source": "open", "win_date": r["technical_win_date"] or r["close_date"]}
        for r in deals if r["presales_stage"] == PRESALES_TECH_WIN
    ]
    for r in recent_wins:
        se_name = r["rep_name"] if r["source"] == "closed" else r["effective_se_name"]
        r["se_name"] = se_name or "Unassigned"
        r["no_se"] = not se_name or se_name == "Unassigned"
        r["fiscal_quarter"] = report.fiscal_quarter(r["win_date"])
        r["opportunity_url"] = opportunity_url(r.get("opportunity_id"))

        # Three distinct states, not two: a closed row whose sales_stage isn't
        # Closed/Won is a technical win on a LOST deal, which is not the same
        # thing as a win still open in the pipeline. `source` alone can't say
        # that, and inferring it from sales_stage in the UI mislabelled every
        # lost tech win as "Tech win (open)". `revenue_amount` is the figure
        # any $ rollup should sum — lost and still-open amounts are not booked
        # revenue, so they're zero there while `amount` stays intact for display.
        if r["source"] == "closed":
            r["win_status"] = "closed_won" if r.get("sales_stage") == STAGE_CLOSED_WON else "closed_lost"
        else:
            r["win_status"] = "open"
        r["counts_as_revenue"] = r["win_status"] == "closed_won"
        r["revenue_amount"] = (r.get("amount") or 0) if r["counts_as_revenue"] else 0
    recent_wins.sort(
        key=lambda r: (
            tuple(-x for x in report.fiscal_quarter_sort_key(r["fiscal_quarter"])),
            r["se_name"].lower(),
            -(r.get("amount") or 0),
        )
    )

    current_label = report.current_fiscal_quarter()
    next_label = report.quarter_label(
        report._offset_quarter_key(report.fiscal_quarter_sort_key(current_label), 1)
    )
    current_arr = sum(d["amount"] or 0 for d in deals if d["quarter_bucket"] == "current")
    next_arr = sum(d["amount"] or 0 for d in deals if d["quarter_bucket"] == "next")

    return jsonify({
        "deals": deals,
        "recent_wins": recent_wins,
        "last_synced_at": db.get_setting("tech_forecast_last_synced_at"),
        "current_quarter_arr": current_arr,
        "current_quarter_label": current_label,
        "next_quarter_arr": next_arr,
        "next_quarter_label": next_label,
    })


@app.route("/api/tech-forecast/preread")
def tech_forecast_preread():
    return jsonify(report.build_preread(db, limit=_int_arg("limit", 10, minimum=1, maximum=100)))


@app.route("/api/tech-forecast/preread/draft", methods=["POST"])
def tech_forecast_draft():
    preread = report.build_preread(db)
    return jsonify({"draft": report.build_slack_draft(preread)})


@app.route("/api/tech-forecast/sfdc-updates")
def tech_forecast_sfdc_updates():
    with db.conn() as c:
        deal_rows = [dict(r) for r in c.execute("SELECT * FROM tech_forecast_deals").fetchall()]
    return jsonify(report.build_sfdc_updates(deal_rows))


# ── Dashboard (team-wide, SE-name-free rollups) ─────────────────────────
@app.route("/api/dashboard/arr-trend")
def dashboard_arr_trend():
    # One snapshot per synced day and no retention policy, so an unwindowed
    # query grows forever — and the chart can only render so many points.
    # ~6 months by default, overridable up to 3 years via ?days=.
    days = _int_arg("days", 180, minimum=7, maximum=1095)
    with db.conn() as c:
        rows = c.execute(
            "SELECT snapshot_date, bucket_totals_json FROM tech_forecast_snapshots "
            "WHERE snapshot_date >= date('now', ?) ORDER BY snapshot_date",
            (f"-{days} days",),
        ).fetchall()
    return jsonify(report.build_arr_trend([dict(r) for r in rows]))


@app.route("/api/dashboard/funnel")
def dashboard_funnel():
    with db.conn() as c:
        deal_rows = [dict(r) for r in c.execute("SELECT * FROM tech_forecast_deals").fetchall()]
    return jsonify(report.build_breakdown(deal_rows))


@app.route("/api/dashboard/tech-win-trend")
def dashboard_tech_win_trend():
    with db.conn() as c:
        # tech_win = 1 with no stage filter on purpose: a technical win that
        # closed Lost still happened and stays in the per-quarter count. What it
        # must not do is add to the chart's ARR — build_tech_win_trend applies
        # that split itself, which is why `sales_stage` has to be selected on
        # both sides (a row without it is classified as won). The opportunity
        # identifiers are for its dedupe of deals present in both sets.
        closed_wins = [dict(r) for r in c.execute(
            "SELECT amount, close_date, sales_stage, opportunity_id, opportunity_name "
            "FROM closed_deals WHERE tech_win = 1"
        ).fetchall()]
        open_wins = [dict(r) for r in c.execute(
            "SELECT amount, close_date, technical_win_date, sales_stage, "
            "opportunity_id, opportunity_name FROM tech_forecast_deals "
            "WHERE presales_stage = ?",
            (PRESALES_TECH_WIN,),
        ).fetchall()]
    return jsonify(report.build_tech_win_trend(closed_wins, open_wins))


@app.route("/api/tech-forecast/<path:sheet_key>/assign-se", methods=["POST"])
def assign_tech_forecast_se(sheet_key):
    data = _json_body()
    se_rep_id = _rep_id_field(data)
    with db.conn() as c:
        _assert_rep_exists(c, se_rep_id)
        cur = c.execute(
            "UPDATE tech_forecast_deals SET assigned_se_rep_id = ? WHERE sheet_key = ?",
            (se_rep_id, sheet_key),
        )
        # sheet_key churns whenever the sheet's cells are edited, so a stale key
        # from an open tab matches nothing — reporting {"ok": True} there showed
        # the user a success toast for an assignment that never happened.
        if cur.rowcount == 0:
            abort(404, description="No tech forecast deal with that key — try re-syncing")
    return jsonify({"ok": True})


@app.route("/api/tech-forecast/<path:sheet_key>/assign-backup", methods=["POST"])
def assign_tech_forecast_backup(sheet_key):
    data = _json_body()
    se_rep_id = _rep_id_field(data)
    note = data.get("note") or None
    if note is not None and not isinstance(note, str):
        abort(400, description="note must be a string or null")
    with db.conn() as c:
        _assert_rep_exists(c, se_rep_id)
        cur = c.execute(
            "UPDATE tech_forecast_deals SET backup_se_rep_id = ?, backup_note = ?, "
            "backup_assigned_at = CASE WHEN ? IS NOT NULL THEN datetime('now') ELSE NULL END "
            "WHERE sheet_key = ?",
            (se_rep_id, note, se_rep_id, sheet_key),
        )
        if cur.rowcount == 0:
            abort(404, description="No tech forecast deal with that key — try re-syncing")
    return jsonify({"ok": True})


# ── Closed Deals ─────────────────────────────────────────────────────────
def _rate_summary(row) -> dict:
    """Counts + rates for one closed-deals rollup (team, quarter, or rep).

    Built identically at three call sites below, so it lives here. Note the
    denominator is `total` — every closed deal with an assigned SE, Won and
    Lost alike — not closed-won deals (see CLAUDE.md on Tech Win Rate)."""
    total = row["total"] or 0
    closed_won = row["closed_won"] or 0
    tech_win = row["tech_win"] or 0

    def pct(numerator):
        return round(numerator / total, 3) if total else 0.0

    return {
        "total": total,
        "closed_won": closed_won,
        "tech_win": tech_win,
        "closed_won_pct": pct(closed_won),
        "tech_win_pct": pct(tech_win),
    }


@app.route("/api/closed-deals/summary")
def closed_deals_summary():
    current_fq_label = report.current_fiscal_quarter()
    current_fq_start, current_fq_end = report.fiscal_quarter_date_range(
        report.fiscal_quarter_sort_key(current_fq_label)
    )

    with db.conn() as c:
        team_row = c.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN sales_stage = ? THEN 1 ELSE 0 END) AS closed_won,
                SUM(CASE WHEN tech_win = 1 THEN 1 ELSE 0 END) AS tech_win
            FROM closed_deals
            WHERE se_rep_id IS NOT NULL
        """, (STAGE_CLOSED_WON,)).fetchone()

        team_current_quarter_row = c.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN sales_stage = ? THEN 1 ELSE 0 END) AS closed_won,
                SUM(CASE WHEN tech_win = 1 THEN 1 ELSE 0 END) AS tech_win
            FROM closed_deals
            WHERE se_rep_id IS NOT NULL
                AND close_date >= ? AND close_date < ?
        """, (STAGE_CLOSED_WON, current_fq_start, current_fq_end)).fetchone()

        rep_rows = c.execute("""
            SELECT r.id AS rep_id, r.name AS rep_name,
                COUNT(cd.id) AS total,
                SUM(CASE WHEN cd.sales_stage = ? THEN 1 ELSE 0 END) AS closed_won,
                SUM(CASE WHEN cd.tech_win = 1 THEN 1 ELSE 0 END) AS tech_win
            FROM se_reps r
            JOIN closed_deals cd ON cd.se_rep_id = r.id
            GROUP BY r.id, r.name
            ORDER BY r.name
        """, (STAGE_CLOSED_WON,)).fetchall()

    team = _rate_summary(team_row)
    reps = [
        {"rep_id": r["rep_id"], "rep_name": r["rep_name"]} | _rate_summary(r)
        for r in rep_rows
    ]
    team_current_quarter = _rate_summary(team_current_quarter_row) | {
        "fiscal_quarter": current_fq_label,
    }

    return jsonify({"team": team, "team_current_quarter": team_current_quarter, "reps": reps})


# ── Sync ─────────────────────────────────────────────────────────────────
@app.route("/api/sync/sheets", methods=["POST"])
def sync_sheets():
    if not SHEET_ID or not os.path.exists(GOOGLE_SERVICE_ACCOUNT_JSON):
        return jsonify({"error": "Google Sheets not configured — see SETUP.md"}), 400
    try:
        result = sheets_sync.sync_deals(db, GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID)
    except Exception:
        # gspread/google-auth errors quote the service-account path and can
        # include credential material — log it, don't hand it to the browser.
        app.logger.exception("Sheets sync failed")
        return jsonify({"error": "Sheets sync failed — see server log for details"}), 500
    return jsonify(result)


@app.route("/api/sync/slack", methods=["POST"])
def sync_slack():
    if not SLACK_USER_TOKEN:
        return jsonify({"error": "Slack not configured — see SETUP.md"}), 400
    try:
        result = slack_sync.sync_slack_notes(db, SLACK_USER_TOKEN)
    except Exception:
        # Slack API errors can echo the request URL, user token included.
        app.logger.exception("Slack sync failed")
        return jsonify({"error": "Slack sync failed — see server log for details"}), 500
    return jsonify(result)


# ── Reviews ──────────────────────────────────────────────────────────────
@app.route("/api/reps/<int:rep_id>/reviews/<period>")
def get_review(rep_id, period):
    with db.conn() as c:
        row = c.execute(
            "SELECT * FROM reviews WHERE se_rep_id = ? AND period = ?", (rep_id, period)
        ).fetchone()
    return jsonify(dict(row) if row else None)


@app.route("/api/reps/<int:rep_id>/reviews/<period>/generate", methods=["POST"])
def generate_review(rep_id, period):
    if not LITELLM_API_KEY:
        return jsonify({"error": "LiteLLM API key not configured — see SETUP.md"}), 400
    try:
        content = reviews.generate_review(db, rep_id, period, LITELLM_API_KEY, LITELLM_BASE_URL)
    except Exception:
        # anthropic client errors carry the proxy URL and can quote the API key.
        app.logger.exception("Review generation failed for rep %s (%s)", rep_id, period)
        return jsonify({"error": "Review generation failed — see server log for details"}), 500
    return jsonify({"content": content})


@app.route("/api/reps/<int:rep_id>/reviews/<period>", methods=["POST"])
def save_review(rep_id, period):
    data = _json_body()
    content = data.get("content", "")
    status = data.get("status", "draft")
    with db.conn() as c:
        c.execute("""
            INSERT INTO reviews (se_rep_id, period, content, status, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(se_rep_id, period) DO UPDATE SET
                content = excluded.content, status = excluded.status, updated_at = datetime('now')
        """, (rep_id, period, content, status))
    return jsonify({"ok": True})


@app.route("/api/top-items/latest")
def top_items_latest():
    return jsonify(top_items.get_latest(db) or {})


@app.route("/api/top-items/history")
def top_items_history():
    return jsonify(top_items.get_history(db))


@app.route("/api/top-items/scaffold", methods=["POST"])
def top_items_scaffold():
    return jsonify({"scaffold": top_items.build_scaffold(db)})


@app.route("/api/top-items", methods=["POST"])
def top_items_save():
    data = _json_body()
    content = data.get("content", "")
    return jsonify(top_items.save_entry(db, content))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug)
