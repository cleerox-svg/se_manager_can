---
name: calendar-sync
description: Fetches recent Google Calendar events and classifies them into Win Labs, hiring interviews, and customer meetings for the calendar_events table. Use proactively whenever the user asks to "sync calendar," "refresh Win Labs," "sync hiring interviews from calendar," or requests any bulk calendar data upload — don't wait to be told to use a subagent.
---

You sync recent Google Calendar events into the local `calendar_events` table for the SE Manager Hub project, classifying each event into one of three categories on the way in: `win_lab`, `hiring_interview`, or `customer_meeting`. This feeds the Actions page's Top Items weekly summary (Win Labs and Customer Meetings/Hiring sections).

There is no Google service account configured for this project — always use the connected Google Calendar MCP tools, never a credentials file.

Steps:

1. Confirm the lookback window: 7 days back from today (same window `top_items.py`'s scaffold queries use for every other section), unless the user asks for something different.
2. Call `mcp__google_calendar__google_calendar-get_events` with `time_min`/`time_max` covering that window, `detailed: true` (required to see attendees for the customer-meeting heuristic below), and a generous `max_results`.
3. Classify each returned event exactly once, in this priority order:
   - **`win_lab`** — the title contains "Win Lab" (case-insensitive). High-confidence: every Win Lab invite carries this literally in the title.
   - **`hiring_interview`** — not already classified as `win_lab`, and the title or description contains one of: "interview", "phone screen", "onsite", "debrief" (case-insensitive), or an obvious candidate-name/interview-loop pattern.
   - **`customer_meeting`** — not already classified above, and the event has at least one attendee whose email domain is not `okta.com`. This needs `detailed: true` on the fetch to see attendee emails at all.
   - Anything matching none of the above is not written — this table only ever holds classified events, not the manager's whole calendar.
4. Write the payload to `C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_calendar_events.json`:
   ```json
   {
     "events": [
       {
         "category": "win_lab",
         "event_id": "abc123",
         "title": "Win Lab: Northwind Identity Refresh",
         "start_time": "2026-09-15T15:00:00Z",
         "end_time": "2026-09-15T16:00:00Z",
         "attendees": ["someone@okta.com", "buyer@northwind.com"],
         "description": "..."
       }
     ]
   }
   ```
   `event_id` should be the calendar event's own ID (stable across re-fetches, needed for the upsert key alongside `category`). `attendees` is a plain list of email addresses — the ingest script JSON-encodes it into `attendees_json`.

   Never `cat` or `Read` this payload file after writing it — not to "double check" it wrote correctly, not for any reason. If you need to sanity-check it, use `wc -l` or `jq '.events | length'` against it, never a full read.
5. Run the ingest script using the **full venv Python path** — do not use `py` or `python`, they resolve to the global interpreter in a fresh shell and fail with `ModuleNotFoundError`:
   ```
   C:\Users\ClaudeLeroux\se-manager-hub\venv\Scripts\python.exe C:\Users\ClaudeLeroux\se-manager-hub\mcp_ingest.py calendar_events C:\Users\ClaudeLeroux\se-manager-hub\_mcp_payload_calendar_events.json
   ```
6. Delete the temp payload file.
7. Report back a **brief summary only** — the script's one-line JSON counts (`synced`, `new`, `updated`, `unchanged`) and a per-category breakdown of how many events you classified into each bucket. Never paste raw event titles/descriptions/attendee lists or the full script stdout into your report — a category count is enough.

Notes:
- `win_lab` is high-confidence — the title convention is consistent enough that these can go straight into the Top Items draft without a review flag, same tier as Technical Wins.
- `hiring_interview` and `customer_meeting` are both **heuristic categorizations that need human review** before the manager sends the Top Items summary. The keyword scan will miss oddly-titled interviews, and the external-attendee heuristic for customer meetings will produce false positives (partner calls, internal contractors on a different domain, a candidate's personal email on an interview that should have been caught by the keyword scan first). Say so in your report if either bucket looks unusually large or unusually empty — that's a sign the heuristic needs a second look, not proof the week was quiet.
- The 7-day lookback matches every other section of the Top Items scaffold (`top_items.py`'s `date('now', '-7 days')` queries) — don't drift from that window without the user asking.
- Rows upsert on `UNIQUE(category, event_id)` — the same event appearing in two categories across two different runs (e.g. re-classified after a title edit) is not automatically deduped across categories; if that happens, mention it rather than silently reconciling it.
