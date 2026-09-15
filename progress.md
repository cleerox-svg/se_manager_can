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
- Shared contract modules: `constants.py`, `attribution.py`
- Commit `33dd77e` (local, unpushed): db.py indexes + shared modules +
  deleted tracked `_before_sync_dump.json`, gitignored `*_dump.json`
- All four code agents landed: db.py, app.py+reviews.py, sync layer +
  new `sheet_parse.py`, tech_forecast_report.py + top_items.py
- Integration pass run by main thread — all 13 modules compile and import;
  every route < 500 on a seeded synthetic DB; verified end to end:
  overrides survive a re-key, shrink guard aborts without deleting,
  "TotalEnergies" survives, `(1,234.00)` -> -1234.0, new reps `active=0`,
  tech-win trend counts Lost but earns no revenue and does not double-count
- Fixed a gap the integration pass found: `_json_body()` folded a
  present-but-invalid body into `{}`, so a garbage POST to /api/top-items
  saved an empty entry and reported success; now 400 (absent body still OK)

## In flight

- tests agent: `tests/` + pinned `requirements.txt`
- docs agent: README.md, CLAUDE.md, `.claude/agents/*.md`

## Next steps

1. Collect tests + docs agent reports; run the full suite myself
2. Commit remaining work; push blocked on GitHub access (403)
3. Delete this file once pushed

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
