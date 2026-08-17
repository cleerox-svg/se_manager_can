import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import reviews
import sheets_sync
import slack_sync
from db import Database

load_dotenv()

DATABASE_PATH = os.environ.get("DATABASE_PATH", "se_manager_hub.db")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
SHEET_ID = os.environ.get("SHEET_ID", "")
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN", "")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "https://llm.atko.ai")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

db = Database(DATABASE_PATH)
db.init()


def current_quarter() -> str:
    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


@app.route("/")
def index():
    return render_template("index.html")


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
    })


# ── SE reps ──────────────────────────────────────────────────────────────
@app.route("/api/reps")
def list_reps():
    with db.conn() as c:
        rows = c.execute("""
            SELECT r.*, COUNT(d.id) AS deal_count
            FROM se_reps r
            LEFT JOIN deals d ON d.se_rep_id = r.id
            GROUP BY r.id
            ORDER BY r.active DESC, r.name
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/reps/<int:rep_id>", methods=["POST"])
def update_rep(rep_id):
    data = request.get_json(force=True)
    fields, values = [], []
    for key in ("active", "slack_user_id", "email", "title", "notes"):
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
