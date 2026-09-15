"""Agentic AWS Bedrock proof-of-concept: computes SE performance metrics from
local SQLite data via a Converse tool-use loop, writing results into
`agent_metrics`.

Unlike reviews.py's single-shot LiteLLM call, this uses boto3's bedrock-runtime
Converse API with a real tool-use loop — the model decides which local-data
tools to call, then calls `write_metric` itself to persist results. No new
external credentials: auth is via the existing Okta SSO -> AWS IAM Identity
Center federation (profile `okta-bedrock`), and all data tools read only
already-synced local tables.
"""

import json

import boto3

_MODEL_ID = "us.anthropic.claude-sonnet-5"

_SYSTEM_PROMPT = """You are an agent that computes SE (Solutions Engineer) performance metrics \
from an Okta Sales Engineering team's local pipeline data. Use the provided tools to gather \
data about each active SE rep, then compute the following metrics and persist each one with \
the write_metric tool:

- arr_attainment_pct: closed-won ARR / arr_target * 100. If arr_target is 0 or missing, skip \
this metric for that rep rather than dividing by zero.
- tech_win_rate: (technical wins / closed deals with an assigned SE) * 100. If there are no \
closed deals with an assigned SE, skip this metric for that rep.
- stale_notes_count: count of that rep's tech_forecast_deals rows where notes_stale = 1.

Process every active SE rep returned by list_se_reps. For each rep, call get_rep_deals, \
get_rep_forecast, and get_rep_slack_activity as needed, compute the three metrics above, and \
call write_metric once per metric with a short one-sentence rationale citing the actual numbers \
you computed. Skip a metric rather than guessing if the underlying data is missing or would \
require division by zero. When you are done with every rep, reply with a brief plain-text \
summary of what you wrote."""

_TOOLS = [
    {
        "toolSpec": {
            "name": "list_se_reps",
            "description": "List active SE reps with their id, name, and arr_target.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "get_rep_deals",
            "description": "Get a rep's open deals and closed deals (with tech_win flag and amount).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"se_rep_id": {"type": "integer"}},
                    "required": ["se_rep_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_rep_forecast",
            "description": "Get a rep's tech_forecast_deals rows, including forecast_status and notes_stale flag.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"se_rep_id": {"type": "integer"}},
                    "required": ["se_rep_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_rep_slack_activity",
            "description": "Get the count and most recent timestamp of a rep's Slack notes.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"se_rep_id": {"type": "integer"}},
                    "required": ["se_rep_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "write_metric",
            "description": "Persist a computed metric value for an SE rep into agent_metrics.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "se_rep_id": {"type": "integer"},
                        "metric_key": {"type": "string"},
                        "value": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["se_rep_id", "metric_key", "value", "rationale"],
                }
            },
        }
    },
]


def _list_se_reps(db) -> list[dict]:
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, name, arr_target FROM se_reps WHERE active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def _get_rep_deals(db, se_rep_id: int) -> dict:
    with db.conn() as c:
        open_deals = c.execute(
            "SELECT opportunity_name, stage, amount, close_date FROM deals WHERE se_rep_id = ?",
            (se_rep_id,),
        ).fetchall()
        closed = c.execute(
            "SELECT opportunity_name, amount, tech_win, sales_stage FROM closed_deals "
            "WHERE se_rep_id = ?",
            (se_rep_id,),
        ).fetchall()
    return {
        "open_deals": [dict(r) for r in open_deals],
        "closed_deals": [dict(r) for r in closed],
    }


def _get_rep_forecast(db, se_rep_id: int) -> list[dict]:
    with db.conn() as c:
        rows = c.execute(
            "SELECT opportunity_name, forecast_status, notes_stale FROM tech_forecast_deals "
            "WHERE assigned_se_rep_id = ?",
            (se_rep_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _get_rep_slack_activity(db, se_rep_id: int) -> dict:
    with db.conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS count, MAX(posted_at) AS most_recent FROM slack_notes "
            "WHERE se_rep_id = ?",
            (se_rep_id,),
        ).fetchone()
    return dict(row)


def _write_metric(db, se_rep_id: int, metric_key: str, value: float, rationale: str) -> dict:
    with db.conn() as c:
        c.execute(
            """
            INSERT INTO agent_metrics (se_rep_id, metric_key, value, rationale, computed_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(se_rep_id, metric_key) DO UPDATE SET
                value = excluded.value, rationale = excluded.rationale,
                computed_at = datetime('now')
            """,
            (se_rep_id, metric_key, value, rationale),
        )
    return {"status": "ok"}


def _dispatch_tool(db, name: str, tool_input: dict):
    if name == "list_se_reps":
        return _list_se_reps(db)
    if name == "get_rep_deals":
        return _get_rep_deals(db, tool_input["se_rep_id"])
    if name == "get_rep_forecast":
        return _get_rep_forecast(db, tool_input["se_rep_id"])
    if name == "get_rep_slack_activity":
        return _get_rep_slack_activity(db, tool_input["se_rep_id"])
    if name == "write_metric":
        return _write_metric(
            db,
            tool_input["se_rep_id"],
            tool_input["metric_key"],
            tool_input["value"],
            tool_input["rationale"],
        )
    raise ValueError(f"unknown tool: {name}")


def run_metrics_agent(db, aws_profile: str = "okta-bedrock", max_turns: int = 40) -> str:
    session = boto3.Session(profile_name=aws_profile)
    client = session.client("bedrock-runtime", region_name="us-east-1")

    messages = [{"role": "user", "content": [{"text": "Compute and persist metrics for every active SE rep."}]}]

    for _ in range(max_turns):
        resp = client.converse(
            modelId=_MODEL_ID,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": _TOOLS},
        )
        output_message = resp["output"]["message"]
        messages.append(output_message)

        if resp["stopReason"] != "tool_use":
            return "".join(
                block["text"] for block in output_message["content"] if "text" in block
            )

        tool_results = []
        for block in output_message["content"]:
            if "toolUse" not in block:
                continue
            tool_use = block["toolUse"]
            try:
                result = _dispatch_tool(db, tool_use["name"], tool_use.get("input", {}))
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": result}],
                    }
                })
            except Exception as exc:
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": {"error": str(exc)}}],
                        "status": "error",
                    }
                })

        messages.append({"role": "user", "content": tool_results})

    return "Agent stopped after reaching max_turns without a final answer."
