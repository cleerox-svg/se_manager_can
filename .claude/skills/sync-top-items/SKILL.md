---
name: sync-top-items
description: Sync just the two feeds behind the Actions page's weekly Top Items summary — Google Calendar (Win Labs/hiring interviews/customer meetings) and Slack recruiting DMs with Cara McArthy. Use when asked to "sync top items", "refresh top items data", or "update top items before I generate the summary".
---

Refreshes the two source-of-truth feeds that `top_items.py`'s `build_scaffold()`
reads for the Actions page's weekly Top Items summary — a narrower slice of
`/sync-se-hub`'s six kinds, matched to Claude Leroux's actual cadence: he
regenerates Top Items roughly weekly and doesn't need the pipeline-sync agents
(deals/closed deals/tech forecast/rep Slack activity) refreshed for that.

## Usage

- `/sync-top-items` or "sync top items" / "refresh top items data" — run
  both kinds in parallel, then remind the user to click "Generate" on the
  Top Items module afterward (the sync only refreshes the DB tables;
  `build_scaffold()` is still triggered by the existing Generate button).

## Procedure

Each kind has a dedicated Claude Code agent in `.claude/agents/` that owns
its full fetch → payload → ingest → cleanup → report flow. This skill's job
is only to dispatch — do not reimplement any sync logic here, and do not
fetch calendar/Slack data yourself in the main thread.

1. Dispatch both kinds **in parallel** — a single message with multiple
   Agent tool calls, not sequential calls:

   | Kind | Agent |
   |---|---|
   | Calendar events (Win Labs/Hiring/Customer Meetings) | `calendar-sync` |
   | Recruiting Slack DMs (Cara McArthy) | `hiring-slack-sync` |

2. Collect both agents' reports and relay them to the user as a single short
   summary — don't let one agent's failure block reporting the other's
   result.
3. After reporting sync counts, tell the user the Top Items scaffold itself
   isn't regenerated automatically — they (or you, on request) still need to
   hit "Generate" on the Actions page's Top Items module to pull the synced
   data into a fresh draft.

Never run these sync flows inline in the main conversation thread; always
delegate to the named agents, same rule as `/sync-se-hub`.

For a full data refresh (pipeline + Slack + calendar), use `/sync-se-hub`
instead — this skill is deliberately scoped to the two feeds Top Items
actually depends on.
