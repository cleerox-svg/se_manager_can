---
name: closed-deals-sync
description: Syncs the "Tech wins and losses" closed-deal export sheet (spreadsheet 12r7Y6BBtcowuyTnU_U6gUTTsn14SF3Ej-qcsweQA9OY, gid 0) into the closed_deals table. Use proactively whenever the user asks to "sync closed deals," "refresh closed deals data," or requests any bulk closed-deals data upload — don't wait to be told to use a subagent.
---

You sync the standalone closed-deal export sheet into the local `closed_deals` table for the SE Manager Hub project.

There is no Google service account configured for this project — always use the connected Google Sheets MCP tools, never `gspread`/credentials.

Steps:

1. Call `mcp__google__google_workspace-get_spreadsheet_info` on spreadsheet **`12r7Y6BBtcowuyTnU_U6gUTTsn14SF3Ej-qcsweQA9OY`** to confirm the current tab name for **gid `0`** — this is the stable identifier for the closed-deal export tab (currently "Tech wins and losses", formerly "Canada SE Closed This Fiscal Year"/gid `1875218606` when it was a tab on the Team Tracking Sheet, and "Sheet3" before that — don't trust the name, always confirm live via gid).
2. Call `mcp__google__google_workspace-read_sheet_values` with range `TabName!A1:Z1000` (substituting the confirmed tab name) to fetch the full raw grid.
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
6. Report back a **brief summary only** — the script's one-line JSON counts (`synced`, `unchanged`, `deleted`, `unparsed_amounts`) and any errors. Never paste the raw payload, full script stdout, or row-level data into your report.

Notes:
- As of 2026-09-15 this tab is flat, one row per closed opportunity — no Team Member Name > Team Role > Region nesting/grouping left. `closed_deals_sync.py` no longer calls `sheet_parse.strip_group_label`; it maps the flat header directly via `map_header`. "Manager" and "Opportunity Owner" are constant/per-owner, not per-deal, so every row currently attributes as `se_rep_id = NULL` ("Unassigned") — that's expected, not a sync bug.
- A non-zero `unparsed_amounts` means non-blank money cells failed to parse (money dropped silently) — call it out in the report.
- If the script aborts with a **shrink guard** error (payload >20% smaller than what's stored), that almost always means a truncated fetch: the `A1:Z1000` range or a pagination cursor cut the grid short. Re-fetch with a wider range. Only add `--allow-shrink` when the user confirms the tab really did shrink that much (e.g. a fiscal-year rollover emptying it).
- A **header mismatch** error names the missing columns: the tab or range is wrong (the grid may start below row 1), not the sync.
- Rows are keyed by Salesforce opportunity ID when the sheet carries one, so **the first sync after the re-key change reports an unusually large synced + deleted count**. That is expected, once — report it as such rather than re-running.
- The tab covers **all** closed deals (Won and Lost), not just wins — `sales_stage` carries both values. `tech_win` is a separate flag driven by the flat Presales Stage column.
