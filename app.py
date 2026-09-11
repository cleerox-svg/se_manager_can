import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import reviews
import sheets_sync
import slack_sync
import tech_forecast_report as report
from db import Database
from salesforce_links import opportunity_url

load_dotenv()

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
        rows = c.execute("""
            SELECT r.*,
                (SELECT COUNT(*) FROM deals d WHERE d.se_rep_id = r.id) AS deal_count,
                (SELECT COALESCE(SUM(amount), 0) FROM closed_deals cd
                    WHERE cd.se_rep_id = r.id
                    AND cd.sales_stage = '10 - Closed/Won') AS arr_total,
                -- tech_forecast_arr sums tech_forecast_deals, not closed_deals, so it's
                -- unaffected by the mixed Won+Lost closed_deals data (see CLAUDE.md).
                (SELECT COALESCE(SUM(tf.amount), 0) FROM tech_forecast_deals tf
                    WHERE tf.opportunity_name IN (
                        SELECT d2.opportunity_name FROM deals d2 WHERE d2.se_rep_id = r.id
                    )) AS tech_forecast_arr,
                rv.status AS review_status,
                rv.content AS review_content
            FROM se_reps r
            LEFT JOIN reviews rv ON rv.se_rep_id = r.id AND rv.period = ?
            ORDER BY r.active DESC, r.name
        """, (period,)).fetchall()
    return jsonify([dict(r) | {"review_period": period} for r in rows])


@app.route("/api/reps/<int:rep_id>", methods=["POST"])
def update_rep(rep_id):
    data = request.get_json(force=True)
    fields, values = [], []
    for key in ("active", "slack_user_id", "email", "title", "notes", "arr_target"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if fields:
        with db.conn() as c:
            c.execute(f"UPDATE se_reps SET {', '.join(fields)} WHERE id = ?", (*values, rep_id))
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
        deal_rows = c.execute("""
            SELECT tf.*,
                (SELECT r.id FROM se_reps r
                    WHERE lower(r.name) = lower(tf.lead_se_name) LIMIT 1) AS lead_se_rep_id,
                (SELECT d.se_rep_id FROM deals d
                    WHERE d.opportunity_name = tf.opportunity_name
                    ORDER BY d.id LIMIT 1) AS attributed_se_id
            FROM tech_forecast_deals tf
            ORDER BY tf.amount DESC
        """).fetchall()
        closed_wins = c.execute(
            "SELECT * FROM closed_deals WHERE tech_win = 1 ORDER BY amount DESC"
        ).fetchall()
        reps_by_id = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM se_reps")}

    deals = []
    for r in deal_rows:
        d = dict(r)
        effective_se_id = d["assigned_se_rep_id"] or d["lead_se_rep_id"] or d["attributed_se_id"]
        d["attributed_se_name"] = reps_by_id.get(d["attributed_se_id"])
        d["effective_se_rep_id"] = effective_se_id
        d["effective_se_name"] = reps_by_id.get(effective_se_id, "Unassigned") if effective_se_id else "Unassigned"
        d["needs_lead_se"] = not d["lead_se_name"]
        d["opportunity_url"] = opportunity_url(d["opportunity_id"])
        deals.append(d)

    recent_wins = [
        dict(r) | {"source": "closed", "win_date": r["close_date"], "notes_stale": False}
        for r in closed_wins
    ]
    recent_wins += [
        r | {"source": "open", "win_date": r["technical_win_date"] or r["close_date"]}
        for r in deals if r["presales_stage"] == "6 - Technical Win"
    ]
    for r in recent_wins:
        se_name = r["rep_name"] if r["source"] == "closed" else r["effective_se_name"]
        r["se_name"] = se_name or "Unassigned"
        r["no_se"] = not se_name or se_name == "Unassigned"
        r["fiscal_quarter"] = report.fiscal_quarter(r["win_date"])
        r["opportunity_url"] = opportunity_url(r.get("opportunity_id"))
    recent_wins.sort(
        key=lambda r: (
            tuple(-x for x in report.fiscal_quarter_sort_key(r["fiscal_quarter"])),
            r["se_name"].lower(),
            -(r.get("amount") or 0),
        )
    )

    return jsonify({
        "deals": deals,
        "recent_wins": recent_wins,
        "last_synced_at": db.get_setting("tech_forecast_last_synced_at"),
    })


@app.route("/api/tech-forecast/preread")
def tech_forecast_preread():
    limit = int(request.args.get("limit", 10))
    return jsonify(report.build_preread(db, limit=limit))


@app.route("/api/tech-forecast/preread/draft", methods=["POST"])
def tech_forecast_draft():
    preread = report.build_preread(db)
    return jsonify({"draft": report.build_slack_draft(preread)})


@app.route("/api/tech-forecast/<path:sheet_key>/assign-se", methods=["POST"])
def assign_tech_forecast_se(sheet_key):
    data = request.get_json(force=True)
    se_rep_id = data.get("se_rep_id") or None
    with db.conn() as c:
        c.execute(
            "UPDATE tech_forecast_deals SET assigned_se_rep_id = ? WHERE sheet_key = ?",
            (se_rep_id, sheet_key),
        )
    return jsonify({"ok": True})


# ── Closed Deals ─────────────────────────────────────────────────────────
@app.route("/api/closed-deals/summary")
def closed_deals_summary():
    def pct(numerator, total):
        return round(numerator / total, 3) if total else 0.0

    with db.conn() as c:
        team_row = c.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN sales_stage = '10 - Closed/Won' THEN 1 ELSE 0 END) AS closed_won,
                SUM(CASE WHEN tech_win = 1 THEN 1 ELSE 0 END) AS tech_win
            FROM closed_deals
            WHERE se_rep_id IS NOT NULL
        """).fetchone()

        rep_rows = c.execute("""
            SELECT r.id AS rep_id, r.name AS rep_name,
                COUNT(cd.id) AS total,
                SUM(CASE WHEN cd.sales_stage = '10 - Closed/Won' THEN 1 ELSE 0 END) AS closed_won,
                SUM(CASE WHEN cd.tech_win = 1 THEN 1 ELSE 0 END) AS tech_win
            FROM se_reps r
            JOIN closed_deals cd ON cd.se_rep_id = r.id
            GROUP BY r.id, r.name
            ORDER BY r.name
        """).fetchall()

    team_total = team_row["total"] or 0
    team_closed_won = team_row["closed_won"] or 0
    team_tech_win = team_row["tech_win"] or 0
    team = {
        "total": team_total,
        "closed_won": team_closed_won,
        "tech_win": team_tech_win,
        "closed_won_pct": pct(team_closed_won, team_total),
        "tech_win_pct": pct(team_tech_win, team_total),
    }

    reps = []
    for r in rep_rows:
        total = r["total"] or 0
        closed_won = r["closed_won"] or 0
        tech_win = r["tech_win"] or 0
        reps.append({
            "rep_id": r["rep_id"],
            "rep_name": r["rep_name"],
            "total": total,
            "closed_won": closed_won,
            "tech_win": tech_win,
            "closed_won_pct": pct(closed_won, total),
            "tech_win_pct": pct(tech_win, total),
        })

    return jsonify({"team": team, "reps": reps})


# ── Sync ─────────────────────────────────────────────────────────────────
@app.route("/api/sync/sheets", methods=["POST"])
def sync_sheets():
    if not SHEET_ID or not os.path.exists(GOOGLE_SERVICE_ACCOUNT_JSON):
        return jsonify({"error": "Google Sheets not configured — see SETUP.md"}), 400
    try:
        result = sheets_sync.sync_deals(db, GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(result)


@app.route("/api/sync/slack", methods=["POST"])
def sync_slack():
    if not SLACK_USER_TOKEN:
        return jsonify({"error": "Slack not configured — see SETUP.md"}), 400
    try:
        result = slack_sync.sync_slack_notes(db, SLACK_USER_TOKEN)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"content": content})


@app.route("/api/reps/<int:rep_id>/reviews/<period>", methods=["POST"])
def save_review(rep_id, period):
    data = request.get_json(force=True)
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug)
