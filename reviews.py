"""Drafts mid-year / check-in style reviews for an SE rep from their deals + Slack activity.

Mirrors the LiteLLM proxy call pattern used in NaughtRFP's agents.py — same
model constants, same httpx verify=False workaround for the corporate
SSL-inspecting proxy.
"""

import warnings

import anthropic
import httpx

from constants import STAGE_CLOSED_WON

# Defined in models.py so bedrock_agent.py and this module cannot drift.
from models import LITELLM_MODEL as _MODEL

_SYSTEM_PROMPT = """You are helping an Okta Sales Engineering manager prep for a FY26 H2 \
Mid-Year Check-In conversation with one of their direct report Solutions Engineers. This is \
a live 1:1 conversation aid, not a formal performance review document — self-reviews and \
peer feedback are optional under the current process, and no written summary is required \
unless the employee is off-track/a low performer.

Write in the manager's voice: direct, specific, evidence-based, no fluff or generic praise.

Structure the output as exactly three sections, using these headings verbatim:

High-impact wins
Areas for improvement & alignment
Career development opportunities

For EACH section:
- A short bulleted list of research notes / talking points. Every bullet must be grounded \
in a specific deal, Slack message, or activity provided in the context below — do not \
invent achievements or concerns that aren't supported by the evidence. If a section has \
thin evidence, keep it short rather than padding it with generic statements.
- End with one "Employee reflection prompt:" line and one "Manager question:" line to use \
in the conversation.

Section-specific guidance:
- High-impact wins: lead with closed-won deals and technical wins (amounts, deal names) as \
concrete evidence of impact, then layer in other delivered work and, especially, moments \
that show Okta's Door 2 Culture in action.
- Areas for improvement & alignment: candidly flag friction points or blockers, and note \
where H2 priorities should be established. Tie course-correction language to Okta \
Principles (challenging the status quo, overcoming hurdles, empowering each other) rather \
than generic feedback-speak. If evidence suggests the rep is genuinely off-track, say so \
plainly — otherwise don't manufacture a concern just to fill the section.
- Career development opportunities: connect current work to longer-term aspirations and \
name a specific stretch skill or project. Always include a two-way AI proficiency angle — \
what the rep is already doing with AI tools (if evidenced) and a pointer to Atko.AI for \
structured upskilling.

Do not add any other sections, preamble, or sign-off."""


def _make_client(api_key: str, base_url: str | None) -> anthropic.Anthropic:
    warnings.filterwarnings("ignore", message=".*verify=False.*")
    kwargs = {"api_key": api_key, "http_client": httpx.Client(verify=False, timeout=120.0)}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def _money(amount) -> str:
    """`closed_deals.amount` / `deals.amount` are nullable — a single NULL row
    used to blow up the whole generate endpoint on `f"{None:,.2f}"`."""
    return f"${amount or 0:,.2f}"


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
        closed = c.execute(
            "SELECT * FROM closed_deals WHERE se_rep_id = ? ORDER BY amount DESC", (se_rep_id,)
        ).fetchall()

    lines = [f"SE: {rep['name']}", ""]

    # `closed_deals` holds BOTH Won and Lost rows (see CLAUDE.md / constants.py).
    # Splitting into two labelled sections rather than filtering Lost out
    # entirely: a technical win on a deal that later closed Lost is still real
    # SE impact and useful review evidence, but its amount must never land in
    # the revenue line the manager reads aloud. The section headings carry the
    # distinction explicitly so the model can't conflate the two either.
    won = [d for d in closed if d["sales_stage"] == STAGE_CLOSED_WON]
    lost = [d for d in closed if d["sales_stage"] != STAGE_CLOSED_WON]

    won_tech_wins = sum(1 for d in won if d["tech_win"])
    won_amount = sum(d["amount"] or 0 for d in won)
    lines.append(
        f"Closed-WON deals this period ({len(won)}, {won_tech_wins} technical wins, "
        f"{_money(won_amount)} total revenue):"
    )
    for d in won:
        win_flag = " [TECHNICAL WIN]" if d["tech_win"] else ""
        lines.append(
            f"- {d['opportunity_name']} | closed={d['close_date']} | "
            f"amount={_money(d['amount'])}{win_flag}"
        )

    if lost:
        lost_tech_wins = sum(1 for d in lost if d["tech_win"])
        lines.append("")
        lines.append(
            f"Closed-LOST deals this period ({len(lost)}, {lost_tech_wins} of them still "
            f"technical wins). These are NOT revenue — do not count their amounts as won "
            f"business. A technical win here means the SE won the technical evaluation "
            f"even though the deal was commercially lost:"
        )
        for d in lost:
            win_flag = " [TECHNICAL WIN]" if d["tech_win"] else ""
            lines.append(
                f"- {d['opportunity_name']} | closed={d['close_date']} | "
                f"stage={d['sales_stage']} | amount={_money(d['amount'])}{win_flag}"
            )

    lines.append("")
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
            f"amount={_money(d['amount'])}{flag_str} | mgr notes: {d['se_manager_notes'] or '-'} | "
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
