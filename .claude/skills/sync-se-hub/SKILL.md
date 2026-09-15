---
name: sync-se-hub
description: Sync SE Manager Hub data from Google Sheets and Slack into the local DB. Use when asked to "sync se hub", "sync everything", "refresh all data", or run without an argument as the default full sync.
---

Refreshes SE Manager Hub's local database from its four source-of-truth
systems: three Team Tracking Sheet tabs (open pipeline, closed deals,
technical forecast) plus Slack rep activity.

## Usage

- `/sync-se-hub` or "sync everything" / "refresh all data" — run all four
  kinds in parallel.
- "sync deals" / "sync closed deals" / "sync tech forecast" / "sync Slack"
  — run only that one kind.

## Procedure

Each sync kind has a dedicated Claude Code agent in `.claude/agents/` that
owns its full fetch → payload → ingest → cleanup → report flow. This skill's
job is only to dispatch — do not reimplement any sync logic here, and do not
fetch sheet/Slack data yourself in the main thread.

1. Determine which kind(s) were requested (default: all four).
2. Dispatch each requested kind to its agent **in parallel** — a single
   message with multiple Agent tool calls, not sequential calls:

   | Kind | Agent |
   |---|---|
   | Open pipeline | `deals-sync` |
   | Closed deals | `closed-deals-sync` |
   | Technical forecast | `tech-forecast-sync` |
   | Slack | `slack-sync` |

3. Each agent reports its own synced/unchanged/deleted (or loaded/skipped)
   counts. Collect all four reports and relay them to the user as a single
   short summary — don't let any one agent's failure block reporting the
   others' results.

Never run these four sync flows inline in the main conversation thread; always
delegate to the named agents so a long sync doesn't fill up the primary
session's context.
