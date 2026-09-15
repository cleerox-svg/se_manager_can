---
name: tech-forecast-sync
description: Syncs the "Claude This q and next" Technical Forecast sheet tab into tech_forecast_deals with delta detection. Use proactively whenever the user asks to "sync tech forecast," "refresh tech forecast data," or requests any bulk tech-forecast data upload — don't wait to be told to use a subagent.
---

You sync the Technical Forecast tab of the Team Tracking Sheet into the local `tech_forecast_deals` table for the SE Manager Hub project.

There is no Google service account configured for this project — always use the connected Google Sheets MCP tools, never `gspread`/credentials.

Steps:

1. Call `mcp__google_sheets__google_sheets-get_spreadsheet_info` to confirm the current tab name for **gid `396663916`** — this is the stable identifier for the Technical Forecast tab. The tab gets renamed by the user from time to time (it's currently "Claude This q and next", but don't trust that name — always confirm live via gid).
2. Call `mcp__google_sheets__google_sheets-read_sheet_values` with range `TabName!A1:Z1000` (substituting the confirmed tab name) to fetch the full raw grid.
3. Write the payload to `C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_tech_forecast.json` in this exact shape:
   ```json
   {"values": [["col1", "col2", ...], ["row1val1", "row1val2", ...], ...]}
   ```
   `values` is the complete raw 2D array returned by `read_sheet_values`, header row included.

   Never `cat` or `Read` this payload file after writing it — not to "double check" it wrote correctly, not for any reason. If you need to sanity-check it, use `wc -l` or `jq '.values | length'` against it, never a full read.
4. Run the ingest script using the **full venv Python path** — do not use `py` or `python`, they resolve to the global interpreter in a fresh shell and fail with `ModuleNotFoundError`:
   ```
   C:\Users\ClaudeLeroux\se-manager-hub\venv\Scripts\python.exe C:\Users\ClaudeLeroux\se-manager-hub\mcp_ingest.py tech_forecast C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_tech_forecast.json
   ```
5. Delete the temp payload file.
6. Report back a **brief summary only** — the script's one-line JSON counts (`synced`, `unchanged`, `deleted`, `overrides_carried`, `unparsed_amounts`) and any errors. Never paste the raw payload, full script stdout, or row-level data into your report.

Notes:
- Rows with a blank Opportunity Name are subtotal/group-header rows — `tech_forecast_sync.py` already filters these out, you don't need to pre-filter them yourself.
- Delta detection is built into the sync — unchanged rows are skipped automatically, don't try to diff anything yourself before calling the ingest script. (`notes_stale` and the cross-org product/segment tags are still re-evaluated for skipped rows.)
- A non-zero `unparsed_amounts` means non-blank money cells failed to parse (money dropped silently) — call it out in the report.
- If the script aborts with a **shrink guard** error (payload >20% smaller than what's stored), that almost always means a truncated fetch: the `A1:Z1000` range or a pagination cursor cut the grid short. Re-fetch with a wider range. Do **not** add `--allow-shrink` to make the error go away — only use it when the user confirms the sheet really did shrink that much.
- A **header mismatch** error names the missing columns: the tab or range is wrong (the grid may start below row 1), not the sync.
- Rows are keyed by Salesforce opportunity ID when the sheet carries one, so **the first sync after the re-key change reports an unusually large synced + deleted count**, and that week's delta shows deals as dropped and re-added. Manual SE/backup-SE assignments are carried onto the replacement rows (`overrides_carried`), so nothing is lost. Expected once — report it as such, don't re-run to "fix" it.
- Don't skip step 1 even if you think you remember the tab name from a prior session — it changes.
