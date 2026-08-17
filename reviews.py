"""Drafts mid-year / check-in style reviews for an SE rep from their deals + Slack activity.

Mirrors the LiteLLM proxy call pattern used in NaughtRFP's agents.py — same
model constants, same httpx verify=False workaround for the corporate
SSL-inspecting proxy.
"""

import warnings

import anthropic
import httpx

_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """You are helping an Okta Sales Engineering manager draft a mid-year \
check-in note for one of their direct report Solutions Engineers. Write in the manager's \
voice: direct, specific, evidence-based, no fluff or generic praise.

Structure the output as exactly three sections, using these headings verbatim:

High-impact wins
Areas for improvement & alignment
Career development opportunities

Each section is a short bulleted list. Every bullet must be grounded in a specific deal, \
Slack message, or activity provided in the context below — do not invent achievements or \
concerns that aren't supported by the evidence. If a section has thin evidence, keep it \
short rather than padding it with generic statements. Do not add any other sections, \
preamble, or sign-off."""


def _make_client(api_key: str, base_url: str | None) -> anthropic.Anthropic:
    warnings.filterwarnings("ignore", message=".*verify=False.*")
    kwargs = {"api_key": api_key, "http_client": httpx.Client(verify=False, timeout=120.0)}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def _build_context(db, se_rep_id: int) -> str:
    with db.conn() as c:
        rep = c.execute("SELECT * FROM se_reps WHERE id = ?", (se_rep_id,)).fetchone()
        deals = c.execute(
            "SELECT * FROM deals WHERE se_rep_id = ? ORDER BY close_date", (se_rep_id,)
        ).fetchall()
        notes = c.execute(
            "SELECT * FROM slack_notes WHERE se_rep_id = ? ORDER BY posted_at DESC LIMIT 60",
            (se_rep_id,),
        ).fetchall()

    lines = [f"SE: {rep['name']}", ""]

    lines.append(f"Open deals ({len(deals)}):")
    for d in deals:
        flags = []
        if d["poc"]:
            flags.append("POC")
        if d["se_needed"]:
            flags.append("SE NEEDED")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"- {d['opportunity_name']} | stage={d['stage']} | close={d['close_date']} | "
            f"amount={d['amount']}{flag_str} | mgr notes: {d['se_manager_notes'] or '-'} | "
            f"presales notes: {d['presales_notes'] or '-'}"
        )

    lines.append("")
    lines.append(f"Recent Slack activity ({len(notes)} messages):")
    for n in notes:
        lines.append(f"- [#{n['channel_name'] or n['channel_id']}] {n['text']}")

    return "\n".join(lines)


def generate_review(db, se_rep_id: int, period: str, api_key: str, base_url: str | None = None) -> str:
    context = _build_context(db, se_rep_id)
    client = _make_client(api_key, base_url)

    resp = client.messages.create(
        model=_MODEL,
        max_tokens=2000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )
    content = resp.content[0].text

    with db.conn() as c:
        c.execute("""
            INSERT INTO reviews (se_rep_id, period, content, status, updated_at)
            VALUES (?, ?, ?, 'draft', datetime('now'))
            ON CONFLICT(se_rep_id, period) DO UPDATE SET
                content = excluded.content, updated_at = datetime('now')
        """, (se_rep_id, period, content))

    return content
