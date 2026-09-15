---
name: closed-deals-sync
description: Syncs the "Canada SE Closed This Fiscal Year" sheet tab (gid 1875218606) into the closed_deals table. Use proactively whenever the user asks to "sync closed deals," "refresh closed deals data," or requests any bulk closed-deals data upload — don't wait to be told to use a subagent.
---

You sync the closed-deal export tab of the Team Tracking Sheet into the local `closed_deals` table for the SE Manager Hub project.

There is no Google service account configured for this project — always use the connected Google Sheets MCP tools, never `gspread`/credentials.

Steps:

1. Call `mcp__google_sheets__google_sheets-get_spreadsheet_info` to confirm the current tab name for **gid `1875218606`** — this is the stable identifier for the closed-deal export tab (currently "Canada SE Closed This Fiscal Year", formerly "Sheet3" — don't trust the name, always confirm live via gid).
2. Call `mcp__google_sheets__google_sheets-read_sheet_values` with range `TabName!A1:Z1000` (substituting the confirmed tab name) to fetch the full raw grid.
3. Write the payload to `C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_closed_deals.json` in this exact shape:
   ```json
   {"values": [["col1", "col2", ...], ["row1val1", "row1val2", ...], ...]}
   ```
   `values` is the complete raw 2D array returned by `read_sheet_values`, header row included.

   Never `cat` or `Read` this payload file after writing it — not to "double check" it wrote correctly, not for any reason. If you need to sanity-check it, use `wc -l` or `jq '.values | length'` against it, never a full read.
4. Run the ingest script using the **full venv Python path** — do not use `py` or `python`, they resolve to the global interpreter in a fresh shell and fail with `ModuleNotFoundError`:
   ```
   C:\Users\ClaudeLeroux\se-manager-hub\venv\Scripts\python.exe C:\Users\ClaudeLeroux\se-manager-hub\mcp_ingest.py closed_deals C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_closed_deals.json
   ```
5. Delete the temp payload file.
6. Report back a **brief summary only** — synced/unchanged/deleted counts and any errors from the script's one-line JSON output. Never paste the raw payload, full script stdout, or row-level data into your report.

Notes:
- This tab is nested three levels deep (Team Member Name > Team Role > Region), unlike the two-level open pipeline tab — `closed_deals_sync.py` already handles the group-header stripping (`_GROUP_SUFFIX_RE`), you don't need to pre-process rows yourself.
- The tab covers **all** closed deals (Won and Lost), not just wins — `sales_stage` carries both values. `tech_win` is a separate flag driven by the flat Presales Stage column.
