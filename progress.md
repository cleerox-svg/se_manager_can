# Backend audit remediation — working scratchpad

Task: fix the findings from the 2026-09-15 backend review (5 read-only review
agents), update docs, push. Delete this file when the task is done.

## Key IDs

- Branch: `claude/brave-volta-58kom7` (fast-forwarded to `7ba9407`)
- Base at review time: `6e36ab9`; review findings re-based onto `7ba9407`
- New since review: `bf03fc7` (rewrote `tech_forecast_sync._normalize_values`
  + `_strip_group_suffix` three-way signal), `13d28bb` (new `top_items.py`),
  `7ba9407` (CLAUDE.md git policy -> always push origin/main)
- Scratchpad: /tmp/claude-0/-home-user-se-manager-can/b494782b-3f80-58a3-8141-5e9badd8b5ea/scratchpad

## Completed

- Fast-forwarded branch to origin/main `7ba9407`; re-verified findings against it
- Wrote shared contract modules: `constants.py` (stage strings),
  `attribution.py` (single copy of the three-step SE precedence)

## In flight (4 parallel agents, disjoint file ownership)

- A: `db.py` — indexes (+4.6x measured on /api/reps), `deals.opportunity_id`,
  `utc_now_iso()`, snapshot retention, schema_version guard
- B: `app.py` + `reviews.py` — Closed/Won filters, NULL money guards, JSON
  error handler + logging, input validation, use shared attribution SQL
- C: sync modules + new `sheet_parse.py` — override preservation across
  re-key, `notes_stale` fix, delete guard, "total" substring, cascade,
  header validation, tag re-derivation, snapshot columns
- D: `tech_forecast_report.py` + `top_items.py` — attribution in preread,
  NULL money, tech-win double-count, overdue bucket, single-pass metrics

## Next steps

1. Collect agent reports; resolve any cross-file contract mismatches
   (`db.utc_now_iso` imported by C; `attribution.*` used by B and D)
2. Wave 2: tests (`tests/`) + docs (README.md, CLAUDE.md) agents
3. Full verification pass: compile, import, run test suite, build frontend
4. Commit + push + draft PR

## Open decisions (asked of user)

- Push target: designated branch + PR vs. direct to `origin/main` (the
  updated CLAUDE.md says always push main; session config says never push
  outside the designated branch without explicit permission)
- `_before_sync_dump.json`: tracked file containing real customer pipeline
  data — untrack / leave / purge from history

## Assumptions

- The sheet_key fix does NOT depend on knowing how well `opportunity_id` is
  populated in production (that query was never run): agent C implements
  BOTH id-preferred keying AND override carry-forward across re-key, so it
  is safe either way.
