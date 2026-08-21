"""One-off seed: loads FY26 H2 Mid-Year Check-In prep notes (hand-researched, from the
'FY26 H2 Mid-Year Check-Ins — Direct Reports' prep doc) into the reviews table as drafts
for period 2026-H2. Run once with `py seed_mid_year_2026h2.py`; re-running overwrites the
same drafts (ON CONFLICT upsert), so it's safe to re-run after editing the content below.
"""

from db import Database

PERIOD = "2026-H2"

REVIEWS = {
    "Nic Da Silva": """High-impact wins
- Recognized via Oktapreciate by Amar Goel for the Goeasy Financial QBR: "Nic knocked it out of the park... His product smarts and way of weaving a story with the CISO were just awesome." Strong exec-level, CISO-facing storytelling.
- Recognized via Oktapreciate by Mohammad Hussain for always jumping in on tough last-minute customer requests and building rapport that drives opportunities forward.
- Diverse, high-volume pipeline: Axiom Builders (OIG/LCM, $54,743.78, technical win confirmed), Jobber (XAA upsell, $100,000), Hopper (OIG/Access Requests, $24,750), Hiive (WIC Cross-Sell, $71,760), plus Cadillac Fairview, Broadstreet Properties, KOHO, Jane App, AlayaCare, TMX Group, Tecsys, EdgePoint Wealth.
- Stepped up to lead the McCain Foods FY27 RFP effort — coordinating the demo environment build-out, recruiting Rishika and Sean onto the deal team, and requesting a dedicated ServiceNow SME. A real deal-lead role on a strategic multi-person pursuit.
- Door 2 Culture: personally welcomed new teammate Pratul Agarwal, and was named (with Rishika and Valentin) in Pratul's thank-you note for helping him get up to speed.
Employee reflection prompt: "Where did I make the biggest impact over the last six months, and how did I bring our Door 2 culture into my daily work?"
Manager question: "What are you proudest of achieving over the last six months, and what felt like your biggest win?"

Areas for improvement & alignment
- On Bombardier Inc. ISPM ($288,000) he played a background/supporting role while Ajay led — worth exploring whether he wants more ownership on large strategic accounts vs. staying in a supporting capacity.
- With such a broad, varied book of smaller/mid-size deals plus now leading McCain, check whether he feels stretched thin and where he'd want prioritization support for H2.
Employee reflection prompt: "Where did I face the most friction or run into blockers? How can I use Okta's Principles to approach these challenges differently?"
Manager question: "Looking back, where did you run into the most friction, and what support or shifts do we need to make to set you up for success in the second half of the year?"

Career development opportunities
- Already engaging with Okta's newest product line via the Jobber XAA (Okta for AI Agents) upsell — a natural entry point to talk about deepening AI-agent-security expertise as a stretch skill.
- Filed two Product Gap tickets in #okta-identity-governance and volunteered to test NFC+PIN with his own hardware for a frontline-worker use case — genuine pull toward shaping the roadmap; worth exploring a more formal product-liaison/SME role.
- Ask whether he wants more lead-SE ownership on strategic/enterprise accounts (vs. the supporting role on Bombardier) — McCain RFP leadership is a good proof point to build on.
Employee reflection prompt: "What skills or stretch projects do I want to tackle next? How am I currently experimenting with AI, and what skills do I want to learn and build next?"
Manager question: "What skills or experiences do you want to prioritize next to get closer to your long-term career goals? What's one new AI skill that would meaningfully improve your effectiveness, and how can I help you build it?" (Point him to Atko.AI for structured AI upskilling.)""",

    "Sean Keleher": """High-impact wins
- Title: Team Lead – Principal Solutions Engineer — already carries informal leadership scope on the team.
- Caught a bad AI machine-translation of the Revenu Québec RFI (Loi 25 privacy-law context), converted the PDF to DOCX himself, produced an accurate translation, and proactively shared it with the Deloitte partner team and internal colleagues — strong technical initiative on a sensitive public-sector deal.
- On WELL Health Technologies, made and documented the technical call that Okta Workflows shouldn't be used in production for the Telephony inline-hook use case due to latency/reliability — good technical judgment protecting solution integrity.
- Caught and drove resolution of an owner auto-assignment bug in Okta's AI Agents (Preview) ahead of an Aug 13 customer demo, and pushed the AI/LLM platform team directly on MCP server allowlisting to unblock Claude-based demos — deep, hands-on engagement with Okta's newest product surface under real deadline pressure.
- Sharp blocker analysis on the DND EAGS RFP, flagging air-gap/on-prem requirements as go/no-go issues early — protected the team from over-investing in a deal that wasn't winnable as scoped.
- Accepted a same-day TMR for an Alberta customer with no notice; pinch-hit for Nic's Jobber account by briefing the team on XAA.
- Sent an unprompted, heartfelt Oktapreciate recognition praising your leadership and its impact on the Canada SE team's culture.
Employee reflection prompt: "Where did I make the biggest impact over the last six months, and how did I bring our Door 2 culture into my daily work?"
Manager question: "What are you proudest of achieving over the last six months, and what felt like your biggest win?"

Areas for improvement & alignment
- He's already operating with informal Team Lead scope (mentoring, cross-team support, technical arbitration, AI/platform escalations) — worth checking whether that's sustainable alongside his own account load, and whether the scope should be made more explicit for H2.
Employee reflection prompt: "Where did I face the most friction or run into blockers? How can I use Okta's Principles to approach these challenges differently?"
Manager question: "Looking back, where did you run into the most friction, and what support or shifts do we need to make to set you up for success in the second half of the year?"

Career development opportunities
- Given the existing Team Lead title, this is a good moment to discuss formalizing/expanding a people-leadership track vs. staying an IC Principal SE.
- He's already shown organic AI proficiency (translation tooling to solve a real deal problem, troubleshooting Okta's AI Agents Preview, pushing on MCP allowlisting) — a good jumping-off point to discuss him becoming the team's informal AI/agent specialist, alongside structured upskilling via Atko.AI.
Employee reflection prompt: "What skills or stretch projects do I want to tackle next? How am I currently experimenting with AI, and what skills do I want to learn and build next?"
Manager question: "What skills or experiences do you want to prioritize next to get closer to your long-term career goals? What's one new AI skill that would meaningfully improve your effectiveness, and how can I help you build it?\"""",

    "Rishika Kondaveeti": """High-impact wins
- Owns the single largest and most technically advanced deal in the book: Bell Canada — O4AA + FGA, $917,250, active POC with a dedicated "Technical Win Lab" deck. Helping architect genuinely new territory for Okta — AI agent identity security across Confluence/Jira/SAP via an MCP Gateway concept, fine-grained authorization for agents, and Gemini/Vertex AI integration patterns.
- Proactively suspended Bell's O4AA POC tenant access pending clarity on an upstream platform change — protected the customer from disruption on her own initiative. Strong risk judgment on a high-value deal.
- Telus Digital Solutions (OWI, $120,000, competitive displacement vs. Ping) — all technical questions and concerns addressed. LayerZero Labs — verbal technical win confirmed at final POC check-in. Also driving HostPapa ($120,000 New Business, active POC) and D2L ($100,000 WIC Expansion).
- Gave a strong, detailed candidate debrief recommendation, and stepped in to cover Nic's McCain RFP responsibilities in his absence, including booking an internal sync — reliable, team-first behavior beyond her own book.
- Door 2 Culture: named by new teammate Pratul Agarwal, alongside Nic and Valentin, in his thank-you note for helping him get up to speed.
Employee reflection prompt: "Where did I make the biggest impact over the last six months, and how did I bring our Door 2 culture into my daily work?"
Manager question: "What are you proudest of achieving over the last six months, and what felt like your biggest win?"

Areas for improvement & alignment
- Bell alone is a large, multi-workstream POC; she's also carrying a full secondary portfolio (WorkJam, HudBay Minerals, Peel Regional Police, Videotron, Corporation of the County of Simcoe RFP, and more) plus increasingly being the person others lean on when someone is out. Worth explicitly checking bandwidth and where she needs support or deprioritization heading into H2.
Employee reflection prompt: "Where did I face the most friction or run into blockers? How can I use Okta's Principles to approach these challenges differently?"
Manager question: "Looking back, where did you run into the most friction, and what support or shifts do we need to make to set you up for success in the second half of the year?"

Career development opportunities
- She's effectively doing frontier AI-agent-identity architecture work already (FGA + MCP Gateway + Gemini/Vertex AI for Bell). Natural conversation: formalize this as an AI-agent-identity specialization — enablement, internal SME work, or conference-level talks.
- Consistently the person other team members lean on (hiring panels, covering for Nic, proactive risk calls on Bell) — worth discussing whether this informal reliability should translate into a more explicit leadership or mentorship track.
Employee reflection prompt: "What skills or stretch projects do I want to tackle next? How am I currently experimenting with AI, and what skills do I want to learn and build next?"
Manager question: "What skills or experiences do you want to prioritize next to get closer to your long-term career goals? What's one new AI skill that would meaningfully improve your effectiveness, and how can I help you build it?" (Point her to Atko.AI for structured AI upskilling.)""",

    "Valentin Bourneuf": """High-impact wins
- Surerus Murphy Joint Venture (WIC, $164,220) — designed a complex identity architecture spanning four distinct organizations (Surerus Pipeline, SMJV, Murphy Group Canada, WHC).
- Benevity (O4AA, $100,000) — navigated significant stakeholder turnover on the customer side and kept the deal moving. AbCellera — solving for auditability/JIT provisioning needs (ODA + OPA/PAM).
- Ran 3 demos to advance CPAC (WIC upsell); also active on Coveo Solutions, Altasciences, BioRender, CAUSEWORX.
- Leading a forward-looking POC with ruby evaluating Okta's AI agent identity layer (MCP bridge/adapter) — connecting Kiro (an AI IDE) through the Okta MCP bridge to back-end resources. Genuinely hands-on with emerging AI-agent tooling.
- Took on a highly technical, short-notice TMR for Forsight Cybersecurity covering RADIUS/PKI, Linux MFA/SSH, and xRDP/Wayland — picked up real technical range with minimal prep time.
- Raised a sharp architecture question in #canada-se about scaling Okta as a second IdP for an MSP managing 50+ Salesforce orgs under the new Salesforce phishing-resistant MFA mandate — thinking beyond his own accounts to broader partner-ecosystem problems.
- Door 2 Culture: named by new teammate Pratul Agarwal, alongside Nic and Rishika, in his thank-you note for helping him get up to speed.
Employee reflection prompt: "Where did I make the biggest impact over the last six months, and how did I bring our Door 2 culture into my daily work?"
Manager question: "What are you proudest of achieving over the last six months, and what felt like your biggest win?"

Areas for improvement & alignment
- Benevity stalled when the single champion (Patrick Audet) was "left alone" and requested extra time — a good example to discuss multi-threading strategies for deals that depend on one champion, heading into H2.
Employee reflection prompt: "Where did I face the most friction or run into blockers? How can I use Okta's Principles to approach these challenges differently?"
Manager question: "Looking back, where did you run into the most friction, and what support or shifts do we need to make to set you up for success in the second half of the year?"

Career development opportunities
- The ruby MCP-bridge/Kiro POC is a strong AI-proficiency conversation starter — he's already building hands-on with AI dev tooling and Okta's AI agent identity layer. Worth discussing whether he wants to go deeper here as a specialization.
- The MSP/Salesforce multi-org architecture question also signals interest in partner-ecosystem problems — another possible specialization thread alongside the AI-agent identity work.
Employee reflection prompt: "What skills or stretch projects do I want to tackle next? How am I currently experimenting with AI, and what skills do I want to learn and build next?"
Manager question: "What skills or experiences do you want to prioritize next to get closer to your long-term career goals? What's one new AI skill that would meaningfully improve your effectiveness, and how can I help you build it?" (Point him to Atko.AI for structured AI upskilling.)""",
}


def main():
    db = Database("se_manager_hub.db")
    db.init()
    with db.conn() as c:
        reps = {row["name"]: row["id"] for row in c.execute("SELECT id, name FROM se_reps")}
        for name, content in REVIEWS.items():
            rep_id = reps.get(name)
            if not rep_id:
                print(f"Skipping {name} — not found in se_reps")
                continue
            c.execute("""
                INSERT INTO reviews (se_rep_id, period, content, status, updated_at)
                VALUES (?, ?, ?, 'draft', datetime('now'))
                ON CONFLICT(se_rep_id, period) DO UPDATE SET
                    content = excluded.content, updated_at = datetime('now')
            """, (rep_id, PERIOD, content))
            print(f"Seeded {PERIOD} draft review for {name} (rep_id={rep_id})")


if __name__ == "__main__":
    main()
