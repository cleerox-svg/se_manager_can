---
name: tech-forecast-sync
description: Syncs the "Claude This q and next" Technical Forecast sheet tab into tech_forecast_deals with delta detection. Use when asked to "sync tech forecast" or "refresh tech forecast data."
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
4. Run the ingest script using the **full venv Python path** — do not use `py` or `python`, they resolve to the global interpreter in a fresh shell and fail with `ModuleNotFoundError`:
   ```
   C:\Users\ClaudeLeroux\se-manager-hub\venv\Scripts\python.exe C:\Users\ClaudeLeroux\se-manager-hub\mcp_ingest.py tech_forecast C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_tech_forecast.json
   ```
5. Delete the temp payload file.
6. Report the result to the user, including synced/unchanged/deleted counts from the script's output.

Notes:
- Rows with a blank Opportunity Name are subtotal/group-header rows — `tech_forecast_sync.py` already filters these out, you don't need to pre-filter them yourself.
- Delta detection is built into the sync — unchanged rows are skipped automatically, don't try to diff anything yourself before calling the ingest script.
- Don't skip step 1 even if you think you remember the tab name from a prior session — it changes.
