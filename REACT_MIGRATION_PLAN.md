# React Migration Plan

Plan for migrating SE Manager Hub's frontend from the current vanilla
JS/HTML SPA (`templates/index.html` + `static/app.js` + `static/style.css`)
to a React-based frontend. Written to be handed off to subagents in phases —
each phase is independently reviewable and leaves the app in a working state.

**Status: plan only. No implementation has started.**

## Why migrate

The current frontend is a single 704-line `static/app.js` acting as router,
API client, and renderer for five pages (Dashboard, Team, Person, Technical
Forecast, Settings), all built with string-templated HTML and manual DOM
updates. That worked while the app was small; it's now the largest, most
change-churned file in the repo and every new feature (recent example:
Technical Forecast's five sub-sections) makes it harder to reason about
which state changes touch which DOM. React buys componentization,
declarative state, and a much easier path for subagents to work on isolated
pieces in parallel without stepping on each other inside one giant file.

## What does NOT change

The backend needs **zero changes**. `app.py`'s 17 routes are already clean
JSON APIs with one exception (`GET /` serves the SPA shell). React consumes
the same endpoints via `fetch`:

- `GET /api/settings`
- `GET /api/reps`, `POST /api/reps/<id>`
- `GET /api/reps/<id>/deals`, `GET /api/reps/<id>/slack`
- `GET /api/deals` (query: `quarter`, `stage`, `search`)
- `GET /api/tech-forecast`
- `GET /api/tech-forecast/preread`, `POST /api/tech-forecast/preread/draft`
- `POST /api/tech-forecast/<sheet_key>/assign-se`
- `GET /api/closed-deals/summary`
- `POST /api/sync/sheets`, `POST /api/sync/slack`
- `GET /api/reps/<id>/reviews/<period>`
- `POST /api/reps/<id>/reviews/<period>/generate`
- `POST /api/reps/<id>/reviews/<period>`

Business logic that must **stay in Flask/Python, not get reimplemented in
React**:

- Okta fiscal-quarter math (`tech_forecast_report.fiscal_quarter`,
  `quarter_bucket`) — deliberately distinct from `app.py`'s calendar-based
  `current_quarter()`. React just renders whatever quarter labels the API
  already returns.
- SE-attribution precedence in `tech_forecast()` (override >
  `lead_se_name` match > opportunity-name join > "Unassigned").
- Recent-wins merge/sort logic, closed-deal win-rate aggregation.
- Slack draft templating (`tech_forecast_report.build_slack_draft`,
  `_slack_opp_link`'s plain-text-not-mrkdwn link format,
  `build_discussion_question`'s heuristic priority order, `_MANTRA`).

Only `GET /` changes meaning: instead of rendering the current SPA shell, it
serves the built React app's `index.html` (or the Vite dev server proxies to
Flask during development — see Phase 0).

## Architecture decisions

- **Build tool: Vite.** No build tooling exists today (no `package.json`).
  Vite is the standard low-config choice for a Flask-backed React SPA and
  has a fast dev server with HMR.
- **Language: JavaScript, not TypeScript**, to match the existing codebase's
  untyped JS convention (`static/app.js` has no type annotations). Revisit
  only if the user asks for TypeScript explicitly.
- **Routing: client-side, no react-router initially.** The current app has
  exactly 5 top-level pages with simple string-based navigation
  (`navigate('page-name')`) and one detail view (Person, reached from Team).
  A minimal custom router (a `currentPage` state value + a `<Router>`
  switch) is enough and avoids a dependency; upgrade to `react-router` later
  only if URL deep-linking becomes a real need.
- **State/data fetching: no Redux/React Query initially.** Each page owns
  its own `fetch` calls in a `useEffect`, mirroring the current
  page-by-page fetch pattern in `app.js`. Introduce a shared data layer only
  if duplicate fetching becomes a real problem after migration.
- **Styling: port `static/style.css` as-is**, including the Okta dark-theme
  CSS custom properties and the `body.light-mode` override block. Do not
  rewrite to CSS-in-JS or a utility framework — this is a pure structural
  migration, not a redesign.
- **Directory layout:**
  ```
  se-manager-hub/
    frontend/              # new Vite React app
      src/
        api.js             # fetch helpers, one per API route
        App.jsx            # top-level shell: sidebar, topbar, router, toasts
        components/
          Sidebar.jsx
          Topbar.jsx
          Toasts.jsx
        pages/
          Dashboard.jsx
          Team.jsx
          Person.jsx
          TechForecast/
            TechForecast.jsx
            TeamPrepMessage.jsx
            MacroView.jsx
            LookBack.jsx
            LookForwardInspect.jsx
            WrapUpRisk.jsx
          Settings.jsx
        theme.js           # light/dark + present-mode toggle logic
      index.html
      vite.config.js
      package.json
    static/                # existing CSS ported here, or moved under frontend/src
    templates/             # index.html removed once React build replaces it
    app.py                 # unchanged except the `/` route
  ```

## Phased task breakdown

Each phase should be its own commit (and, per the user's authorization for
this task, pushed to GitHub) so subagents can pick up the next phase from a
clean, working state.

### Phase 0 — Scaffold (no visible behavior change)
- `npm create vite@latest frontend -- --template react`
- Configure Vite dev server to proxy `/api/*` to `http://localhost:5050`
  (Flask stays the API server during development).
- Decide and wire up the production serve path: either Flask serves
  `frontend/dist` as static files at `/`, or Vite's build output replaces
  `templates/index.html` + `static/`. Confirm which before Phase 1 so later
  phases don't need to redo the wiring.
- Add an npm script (`npm run build`) and document it in README.md's "Run
  it" section alongside the existing `py app.py` instructions.
- No pages ported yet — this phase just proves the toolchain builds and
  Flask can serve the built output.

### Phase 1 — Shell: Sidebar, Topbar, Router, Toasts, Theme toggle
- Port `templates/index.html`'s structure into `App.jsx`: sidebar with 4
  nav buttons + theme-toggle button, topbar with dynamic page title, a
  `#toasts`-equivalent notification area, and the custom page router.
- Port the `body.light-mode` / `localStorage` theme persistence and the
  `body.present-mode` toggle (currently exit-button-triggered from inside
  Technical Forecast — keep that trigger point when porting Phase 5).
- Pages can render placeholder content in this phase; the goal is the shell
  (nav, routing, theming, toasts) working end-to-end.

### Phase 2 — Dashboard + Team pages
- `Dashboard.jsx`: deals list, quarter/stage/search filters, POC/SE-Needed
  flags. Straightforward `GET /api/deals` fetch + client-side filter
  controls hitting the same query params (`quarter`, `stage`, `search`).
- `Team.jsx`: roster table, active/inactive toggle (`POST /api/reps/<id>`),
  ARR-vs-target progress bars, inline review editor (Generate draft / Save
  draft / Mark final) reusing the same `/api/reps/<id>/reviews/<period>`
  endpoints as the Person page's Review tab — consider a shared
  `ReviewEditor` component used by both Team and Person from the start to
  avoid duplicating this logic twice.

### Phase 3 — Person detail page
- `Person.jsx`: open deals, Slack activity, Review tab (shared
  `ReviewEditor` component from Phase 2).
- Reachable via a click-through from Team, matching current navigation
  (no URL-based deep link needed per the no-react-router decision above).

### Phase 4 — Settings page
- Smallest page: sync status + Sheets/Slack sync buttons
  (`POST /api/sync/sheets`, `POST /api/sync/slack`), Gong placeholder.
- Good candidate for a subagent's first solo task given its small surface
  area.

### Phase 5 — Technical Forecast page (largest page, split into sub-tasks)
This is the most complex page (5 sections) — break it into its own
sub-phases rather than one large task:
- 5a. Macro View stat-grid + page-level data fetch (`GET /api/tech-forecast`).
- 5b. Team Prep Message card (Generate draft / Copy-to-clipboard, hitting
  `/api/tech-forecast/preread` + `/api/tech-forecast/preread/draft`).
- 5c. Look Back — recent wins grouped by fiscal quarter → SE → amount, with
  collapsible `<details class="flyout">` groups and "No SE" / "No new
  notes" badges. Port the collapsible-group rendering carefully; this is
  the most structurally nested part of the current `app.js`.
- 5d. Look Forward & Inspect — Must-Win table + collapsible below-threshold
  flyout, SE-assignment dropdown (`POST /api/tech-forecast/<sheet_key>/assign-se`).
- 5e. Wrap-Up & Risk section + Present-mode exit button wiring.

### Phase 6 — Cutover
- Point `GET /` (or the static file serving) at the React build.
- Remove `templates/index.html` and the old `static/app.js` once every page
  is confirmed working in the new frontend.
- Update README.md's Stack/Run-it sections and CLAUDE.md's Key Files table
  to describe the new `frontend/` structure and build step, replacing the
  now-inaccurate "vanilla JS/HTML frontend with no build step" line.

## Out of scope for this migration

- No new features. Any behavior difference found while porting a page
  (e.g. a filter that behaves oddly) should be preserved as-is and flagged
  separately, not silently "fixed" mid-migration.
- No backend changes beyond the `/` route.
- No design/visual changes beyond what's needed to port existing CSS into
  a component structure.
- Gong integration remains not-built, per existing project convention.

## Handoff notes for subagents

- Read this file, `README.md`, and `CLAUDE.md` in full before starting any
  phase — `CLAUDE.md` documents non-obvious backend business logic (fiscal
  quarters, SE attribution, Slack link formatting) that must not be
  reimplemented differently in the frontend.
- Work one phase at a time, in a separate commit per phase, per the
  project's "small, reviewable chunks" convention.
- After any change, check whether the Flask dev server (port 5050) is
  running and restart it — same as any other change to this project.
- Update README.md after each phase that changes user-visible behavior or
  the run/build instructions.
