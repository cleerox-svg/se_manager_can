/* ── SE Manager Hub Frontend ─────────────────────────────────────────────── */

const API = {
  get:  (url) => fetch(url).then(r => r.json()),
  post: (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then(r => r.json()),
};

const state = {
  page: 'dashboard',
  deals: [],
  quarters: [],
  currentQuarter: null,
  quarterFilter: 'current',
  stageFilter: '',
  searchFilter: '',
  reps: [],
  currentRep: null,
  settings: {},
};

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  el.style.cursor = 'pointer';
  el.addEventListener('click', () => el.remove());
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 8000 : 3500);
}

function navigate(page, data = null) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`page-${page}`)?.classList.add('active');
  document.querySelector(`.sidebar-btn[data-page="${page}"]`)?.classList.add('active');
  state.page = page;

  if (page === 'dashboard') renderDashboard();
  if (page === 'team') renderTeam();
  if (page === 'tech-forecast') renderTechForecast();
  if (page === 'settings') renderSettings();
  if (page === 'person' && data) renderPerson(data);
}

function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function stageBadge(stage) {
  const map = { 'Closed Won': 'badge-green', 'Closed Lost': 'badge-red' };
  const cls = map[stage] || 'badge-blue';
  return `<span class="badge ${cls}">${stage || '-'}</span>`;
}

/* ── ARR vs target ───────────────────────────────────────────────────────── */
function arrGoalBar(total, target) {
  total = total || 0;
  const t = target || 0;
  const met = t > 0 && total >= t;
  const fillPct = t > 0 ? Math.min(100, (total / t) * 100) : 0;
  const pct = t > 0 ? Math.round((total / t) * 100) : null;
  return `
    <div class="goal-bar-wrap">
      <div class="goal-bar">
        <div class="goal-bar-fill ${met ? 'met' : ''}" style="width:${fillPct}%"></div>
        ${t > 0 ? '<div class="goal-bar-tick"></div>' : ''}
      </div>
      <div class="goal-bar-label">
        <span>${fmtMoney(total)}${t > 0 ? ' / ' + fmtMoney(t) : ''}</span>
        ${pct != null ? `<span class="pct ${met ? 'met' : ''}">${pct}%</span>` : ''}
      </div>
    </div>
  `;
}

/* ── Win rate (% Closed Won / % Tech Win) ───────────────────────────────── */
function pctBar(pct, opts = {}) {
  const { modifier = '', countLabel = '' } = opts;
  const p = Math.round((pct || 0) * 100);
  return `
    <div class="goal-bar-wrap">
      <div class="goal-bar">
        <div class="goal-bar-fill ${modifier}" style="width:${p}%"></div>
      </div>
      <div class="goal-bar-label">
        <span>${countLabel}</span>
        <span class="pct">${p}%</span>
      </div>
    </div>
  `;
}

function winRateRepRow(r) {
  return `
    <div class="winrate-rep-row">
      <div class="winrate-rep-name">${r.rep_name}</div>
      <div class="winrate-rep-bars">
        <div class="winrate-rep-bar">
          <span class="winrate-rep-bar-label">Closed Won</span>
          ${pctBar(r.closed_won_pct, { countLabel: `${r.closed_won}/${r.total}` })}
        </div>
        <div class="winrate-rep-bar">
          <span class="winrate-rep-bar-label">Tech Win</span>
          ${pctBar(r.tech_win_pct, { modifier: 'accent', countLabel: `${r.tech_win}/${r.total}` })}
        </div>
      </div>
    </div>
  `;
}

function renderWinRateSummary(summary) {
  const team = summary.team;
  return `
    <div class="winrate-team">
      <div class="winrate-team-metric">
        <div class="winrate-team-metric-label">Closed Won</div>
        ${pctBar(team.closed_won_pct, { countLabel: `${team.closed_won}/${team.total}` })}
      </div>
      <div class="winrate-team-metric">
        <div class="winrate-team-metric-label">Tech Win</div>
        ${pctBar(team.tech_win_pct, { modifier: 'accent', countLabel: `${team.tech_win}/${team.total}` })}
      </div>
    </div>
    <div class="winrate-reps">
      ${summary.reps.map(winRateRepRow).join('')}
    </div>
  `;
}

function reviewStatusBadge(status) {
  if (status === 'final') return '<span class="badge badge-green">Final</span>';
  if (status === 'draft') return '<span class="badge badge-blue">Draft</span>';
  return '<span class="badge badge-muted">Not started</span>';
}

/* ── Dashboard ───────────────────────────────────────────────────────────── */
async function renderDashboard() {
  const params = new URLSearchParams({ quarter: state.quarterFilter });
  if (state.stageFilter) params.set('stage', state.stageFilter);
  if (state.searchFilter) params.set('search', state.searchFilter);

  const data = await API.get(`/api/deals?${params}`);
  state.deals = data.deals;
  state.quarters = data.quarters;
  state.currentQuarter = data.current_quarter;

  const el = document.getElementById('dashboard-content');

  const totalAmount = data.deals.reduce((sum, d) => sum + (d.amount || 0), 0);
  const pocCount = data.deals.filter(d => d.poc).length;
  const needSeCount = data.deals.filter(d => d.se_needed).length;
  const stages = [...new Set(data.deals.map(d => d.stage).filter(Boolean))];

  el.innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-value">${data.deals.length}</div><div class="stat-label">Deals in view</div></div>
      <div class="stat-card"><div class="stat-value">${fmtMoney(totalAmount)}</div><div class="stat-label">Total pipeline</div></div>
      <div class="stat-card"><div class="stat-value">${pocCount}</div><div class="stat-label">Active POCs</div></div>
      <div class="stat-card"><div class="stat-value">${needSeCount}</div><div class="stat-label">SE needed</div></div>
    </div>

    <div class="filter-row">
      <select id="quarter-filter">
        <option value="current" ${state.quarterFilter === 'current' ? 'selected' : ''}>Current quarter (${data.current_quarter})</option>
        <option value="all" ${state.quarterFilter === 'all' ? 'selected' : ''}>All quarters</option>
        ${data.quarters.map(q => `<option value="${q}" ${state.quarterFilter === q ? 'selected' : ''}>${q}</option>`).join('')}
      </select>
      <select id="stage-filter">
        <option value="">All stages</option>
        ${stages.map(s => `<option value="${s}" ${state.stageFilter === s ? 'selected' : ''}>${s}</option>`).join('')}
      </select>
      <input type="search" id="search-filter" placeholder="Search opportunity..." value="${state.searchFilter}">
    </div>

    <div class="card">
      <table>
        <thead><tr>
          <th>Opportunity</th><th>SE</th><th>Stage</th><th>Close date</th><th>Amount</th><th>Flags</th>
        </tr></thead>
        <tbody>
          ${data.deals.map(d => `
            <tr>
              <td>${d.opportunity_name}<div style="color:var(--text-muted);font-size:.72rem">${d.geo_seg || ''}</div></td>
              <td>${d.lead_se}</td>
              <td>${stageBadge(d.stage)}</td>
              <td>${d.close_date || '-'}</td>
              <td>${fmtMoney(d.amount)}</td>
              <td><div class="pill-row">
                ${d.poc ? '<span class="badge badge-purple">POC</span>' : ''}
                ${d.se_needed ? '<span class="badge badge-amber">SE Needed</span>' : ''}
              </div></td>
            </tr>
          `).join('') || `<tr><td colspan="6"><div class="empty-state">No deals match these filters</div></td></tr>`}
        </tbody>
      </table>
    </div>
  `;

  document.getElementById('quarter-filter').onchange = e => { state.quarterFilter = e.target.value; renderDashboard(); };
  document.getElementById('stage-filter').onchange = e => { state.stageFilter = e.target.value; renderDashboard(); };
  document.getElementById('search-filter').oninput = debounce(e => { state.searchFilter = e.target.value; renderDashboard(); }, 300);
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ── Team ────────────────────────────────────────────────────────────────── */
async function renderTeam() {
  state.reps = await API.get('/api/reps');
  const el = document.getElementById('team-content');
  const period = state.reps[0]?.review_period || '';

  el.innerHTML = `
    <div class="card">
      <table>
        <thead><tr>
          <th>Name</th><th>Title</th><th>Deals</th><th>Tech Forecast ARR</th>
          <th>ARR vs Target (${period})</th><th>Review (${period})</th><th>Status</th><th></th>
        </tr></thead>
        <tbody>
          ${state.reps.map(r => `
            <tr class="clickable ${r.active ? '' : 'inactive-flag'}" onclick="navigate('person', ${r.id})">
              <td>${r.name}</td>
              <td>${r.title || '-'}</td>
              <td>${r.deal_count}</td>
              <td>${fmtMoney(r.tech_forecast_arr)}</td>
              <td onclick="event.stopPropagation()">
                ${arrGoalBar(r.arr_total, r.arr_target)}
                <input type="number" class="goal-bar-target-input" value="${r.arr_target || ''}"
                  placeholder="Target" onchange="updateRepTarget(${r.id}, this.value)" />
              </td>
              <td onclick="event.stopPropagation(); toggleReviewRow(${r.id})" style="cursor:pointer">
                ${reviewStatusBadge(r.review_status)}
              </td>
              <td>${r.active ? '<span class="badge badge-green">Active</span>' : '<span class="badge badge-muted">Inactive / departed</span>'}</td>
              <td><button class="btn" onclick="event.stopPropagation(); toggleRepActive(${r.id}, ${r.active ? 0 : 1})">${r.active ? 'Mark inactive' : 'Mark active'}</button></td>
            </tr>
            <tr id="review-row-${r.id}" class="review-inline-row" style="display:none">
              <td colspan="8">
                <div class="filter-row">
                  <button class="btn btn-primary" onclick="teamGenerateReview(${r.id}, '${period}')">Generate draft from deals + Slack</button>
                  <button class="btn" onclick="teamSaveReview(${r.id}, '${period}', 'draft')">Save draft</button>
                  <button class="btn" onclick="teamSaveReview(${r.id}, '${period}', 'final')">Mark final</button>
                </div>
                <textarea id="review-text-${r.id}" placeholder="Click 'Generate draft' or write manually...">${r.review_content || ''}</textarea>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

async function toggleRepActive(repId, active) {
  await API.post(`/api/reps/${repId}`, { active });
  toast('Updated', 'success');
  renderTeam();
}

async function updateRepTarget(repId, value) {
  await API.post(`/api/reps/${repId}`, { arr_target: Number(value) || 0 });
  toast('Target updated', 'success');
  renderTeam();
}

function toggleReviewRow(repId) {
  const row = document.getElementById(`review-row-${repId}`);
  row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

async function teamGenerateReview(repId, period) {
  toast('Generating draft...');
  const res = await API.post(`/api/reps/${repId}/reviews/${period}/generate`, {});
  if (res.error) { toast(res.error, 'error'); return; }
  document.getElementById(`review-text-${repId}`).value = res.content;
  toast('Draft generated', 'success');
}

async function teamSaveReview(repId, period, status) {
  const content = document.getElementById(`review-text-${repId}`).value;
  await API.post(`/api/reps/${repId}/reviews/${period}`, { content, status });
  toast(status === 'final' ? 'Marked final' : 'Saved', 'success');
  renderTeam();
}

/* ── Technical Forecast ──────────────────────────────────────────────────── */
function oppLink(name, url) {
  return url ? `<a href="${url}" target="_blank" rel="noopener">${name}</a>` : name;
}

function truncate(text, n) {
  if (!text) return '';
  const flat = text.replace(/[\r\n]+/g, ' ').trim();
  return flat.length > n ? flat.slice(0, n) + '…' : flat;
}

function presalesStageBadge(stage) {
  const cls = stage === '6 - Technical Win' ? 'badge-green' : 'badge-blue';
  return `<span class="badge ${cls}">${stage || '-'}</span>`;
}

function forecastStatusBadge(status) {
  const map = { Strong: 'badge-green', Forecasted: 'badge-blue', 'Forecasted Risk': 'badge-red' };
  return `<span class="badge ${map[status] || 'badge-muted'}">${status || '-'}</span>`;
}

function dealFlags(d) {
  return `
    ${d.notes_stale ? '<span class="badge badge-amber">No update this week</span>' : ''}
    ${!d.pre_sales_next_steps ? '<span class="badge badge-amber">No TW Strategy</span>' : ''}
    ${d.needs_lead_se ? '<span class="badge badge-amber">No Lead SE (sheet)</span>' : ''}
  `;
}

function seAssignSelect(d) {
  const options = [`<option value="" ${!d.effective_se_rep_id ? 'selected' : ''}>Unassigned</option>`]
    .concat(state.reps.map(r => `<option value="${r.id}" ${d.effective_se_rep_id === r.id ? 'selected' : ''}>${r.name}</option>`));
  return `<select class="se-assign-select" onchange="assignSe('${encodeURIComponent(d.sheet_key)}', this.value)">${options.join('')}</select>`;
}

async function assignSe(encodedSheetKey, value) {
  await API.post(`/api/tech-forecast/${encodedSheetKey}/assign-se`, { se_rep_id: value ? Number(value) : null });
  toast('SE assignment updated', 'success');
  renderTechForecast();
}

function notesCell(text, maxWidth) {
  const safe = (text || '').replace(/"/g, '&quot;');
  return `<td title="${safe}" style="max-width:${maxWidth}px;font-size:.78rem;color:var(--text-secondary)">${truncate(text, 90) || '-'}</td>`;
}

function inspectRow(d) {
  return `
    <tr>
      <td>${oppLink(d.opportunity_name, d.opportunity_url)}<div style="color:var(--text-muted);font-size:.72rem">AE: ${d.opportunity_owner || '-'}</div></td>
      <td>${d.sales_stage || '-'}</td>
      <td>${presalesStageBadge(d.presales_stage)}</td>
      <td>${forecastStatusBadge(d.forecast_status)}</td>
      <td>${d.technical_win_date || '-'}</td>
      <td>${fmtMoney(d.amount)}</td>
      <td>${seAssignSelect(d)}</td>
      <td><div class="pill-row">${dealFlags(d)}</div></td>
      ${notesCell(d.pre_sales_notes, 220)}
      ${notesCell(d.pre_sales_next_steps, 220)}
      ${notesCell(d.se_manager_notes, 220)}
    </tr>
  `;
}

function inspectTable(deals) {
  return `
    <div class="table-scroll">
      <table>
        <thead><tr>
          <th>Opportunity</th><th>Stage</th><th>Presales Stage</th><th>Forecast Status</th>
          <th>Tech win date</th><th>Amount</th><th>SE</th><th>Flags</th><th>Pre-sales notes</th><th>Pre-sales next steps</th><th>SE manager notes</th>
        </tr></thead>
        <tbody>${deals.map(d => inspectRow(d)).join('')}</tbody>
      </table>
    </div>
  `;
}

function needsLeadSeTable(rows) {
  return `
    <div class="table-scroll">
      <table>
        <thead><tr><th>Opportunity</th><th>AE</th><th>Presales Stage</th><th>Forecast Status</th><th>Amount</th></tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td>${oppLink(r.opportunity_name, r.opportunity_url)}</td>
              <td>${r.opportunity_owner || '-'}</td>
              <td>${presalesStageBadge(r.presales_stage)}</td>
              <td>${forecastStatusBadge(r.forecast_status)}</td>
              <td>${fmtMoney(r.amount)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

/* ── Look Back — Recent Technical Wins (grouped by quarter → SE) ────────── */
function groupBy(arr, keyFn) {
  // Sequential grouping — relies on `arr` already being sorted by the same
  // key (as recent_wins is, from the backend), so a single pass is enough.
  const groups = [];
  let current = null;
  for (const item of arr) {
    const key = keyFn(item);
    if (!current || current.key !== key) {
      current = { key, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }
  return groups;
}

function recentWinFlags(w) {
  return `${w.source === 'open' && w.notes_stale ? '<span class="badge badge-amber">No new notes</span>' : ''}`;
}

function recentWinRow(w) {
  return `
    <tr>
      <td>${oppLink(w.opportunity_name, w.opportunity_url)}${w.source === 'open' ? `<div style="color:var(--text-muted);font-size:.72rem">AE: ${w.opportunity_owner || '-'}</div>` : ''}</td>
      <td>${w.win_date || '-'}</td>
      <td>${fmtMoney(w.amount)}</td>
      <td><span class="badge ${w.source === 'closed' ? 'badge-green' : 'badge-blue'}">${w.source === 'closed' ? 'Closed win' : 'Tech win (open)'}</span></td>
      <td><div class="pill-row">${recentWinFlags(w)}</div></td>
    </tr>
  `;
}

function renderRecentWinsGrouped(wins) {
  const quarterGroups = groupBy(wins, w => w.fiscal_quarter || 'Unknown');
  return quarterGroups.map((qg, qi) => {
    const qTotal = qg.items.reduce((s, w) => s + (w.amount || 0), 0);
    const seGroups = groupBy(qg.items, w => w.se_name);
    return `
      <details class="flyout wins-quarter${qi === 0 ? ' is-first' : ''}" open>
        <summary>${qg.key} · ${qg.items.length} win${qg.items.length === 1 ? '' : 's'} · ${fmtMoney(qTotal)}</summary>
        ${seGroups.map(sg => {
          const seTotal = sg.items.reduce((s, w) => s + (w.amount || 0), 0);
          const noSe = sg.items[0].no_se;
          return `
            <details class="flyout wins-se" open>
              <summary>${sg.key} · ${sg.items.length} win${sg.items.length === 1 ? '' : 's'} · ${fmtMoney(seTotal)} ${noSe ? '<span class="badge badge-amber">No SE</span>' : ''}</summary>
              <div class="table-scroll">
                <table>
                  <thead><tr><th>Opportunity</th><th>Win date</th><th>Amount</th><th>Status</th><th>Flags</th></tr></thead>
                  <tbody>${sg.items.map(recentWinRow).join('')}</tbody>
                </table>
              </div>
            </details>
          `;
        }).join('')}
      </details>
    `;
  }).join('');
}

async function renderTechForecast() {
  const data = await API.get('/api/tech-forecast');
  state.reps = await API.get('/api/reps');
  const winRateSummary = await API.get('/api/closed-deals/summary');
  const deals = data.deals;

  const totalArr = deals.reduce((sum, d) => sum + (d.amount || 0), 0);
  const riskDeals = deals.filter(d => d.forecast_status === 'Forecasted Risk');
  const staleDeals = deals.filter(d => d.notes_stale);
  const needsLeadSeDeals = deals.filter(d => d.needs_lead_se).sort((a, b) => (b.amount || 0) - (a.amount || 0));
  const inspectDeals = deals.filter(d => d.presales_stage !== '6 - Technical Win');
  const wrapUpDeals = deals
    .filter(d => d.presales_stage !== '6 - Technical Win' && (d.forecast_status === 'Forecasted Risk' || d.notes_stale))
    .sort((a, b) => b.amount - a.amount);

  const el = document.getElementById('tech-forecast-content');
  el.innerHTML = `
    <div class="section-header">
      <div>
        <h2>Technical Forecast</h2>
        <div class="sub" style="color:var(--text-secondary);font-size:.78rem">
          Last synced: ${data.last_synced_at ? new Date(data.last_synced_at).toLocaleString() : 'never'} — Presales Technical Win Process
        </div>
      </div>
      <div class="filter-row">
        <button class="btn" id="sync-now-btn">&#128260; Sync now</button>
        <button class="btn btn-primary" id="present-mode-btn">&#128225; Present mode</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Team Prep Message</div>
      <div class="filter-row">
        <button class="btn btn-primary" id="generate-slack-draft-btn">Generate draft</button>
        <button class="btn" id="copy-slack-draft-btn">Copy to clipboard</button>
      </div>
      <textarea id="slack-draft-text" placeholder="Click 'Generate draft' to build a Slack-ready message from this week's forecast for the team's Monday call..."></textarea>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="stat-value">${fmtMoney(totalArr)}</div><div class="stat-label">Total Tech Forecast ARR</div></div>
      <div class="stat-card"><div class="stat-value">${riskDeals.length}</div><div class="stat-label">Forecasted Risk</div></div>
      <div class="stat-card"><div class="stat-value">${staleDeals.length}</div><div class="stat-label">No update this week</div></div>
      <div class="stat-card"><div class="stat-value">${needsLeadSeDeals.length}</div><div class="stat-label">Needs Lead SE — ${fmtMoney(needsLeadSeDeals.reduce((s, d) => s + (d.amount || 0), 0))}</div></div>
    </div>

    <div class="card">
      <div class="card-title">Needs Lead SE (${needsLeadSeDeals.length})</div>
      ${needsLeadSeDeals.length ? needsLeadSeTable(needsLeadSeDeals) : '<div class="empty-state">Every deal in the sheet has a Lead SE set</div>'}
    </div>

    <div class="card">
      <div class="card-title">Win Rate — Closed Deals</div>
      ${renderWinRateSummary(winRateSummary)}
    </div>

    <div class="card">
      <div class="card-title">Look Back — Recent Technical Wins</div>
      ${data.recent_wins.length ? renderRecentWinsGrouped(data.recent_wins) : '<div class="empty-state">No recent wins on file</div>'}
    </div>

    <div class="card">
      <div class="card-title">Look Forward &amp; Inspect — Open Pipeline (${inspectDeals.length})</div>
      ${inspectDeals.length ? inspectTable(inspectDeals) : '<div class="empty-state">No open deals synced yet</div>'}
    </div>

    <div class="card">
      <div class="card-title">Wrap-Up &amp; Risk (${wrapUpDeals.length})</div>
      ${wrapUpDeals.length ? `
        <table>
          <thead><tr><th>Opportunity</th><th>Forecast Status</th><th>Amount</th><th>SE</th><th>Flags</th></tr></thead>
          <tbody>
            ${wrapUpDeals.map(d => `
              <tr>
                <td>${oppLink(d.opportunity_name, d.opportunity_url)}<div style="color:var(--text-muted);font-size:.72rem">AE: ${d.opportunity_owner || '-'}</div></td>
                <td>${forecastStatusBadge(d.forecast_status)}</td>
                <td>${fmtMoney(d.amount)}</td>
                <td>${seAssignSelect(d)}</td>
                <td><div class="pill-row">${dealFlags(d)}</div></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      ` : '<div class="empty-state">Nothing at risk right now</div>'}
    </div>
  `;

  document.getElementById('present-mode-btn').onclick = () => document.body.classList.add('present-mode');

  document.getElementById('sync-now-btn').onclick = async () => {
    await navigator.clipboard.writeText('Sync the tech forecast sheet.');
    toast('Copied — paste into a Claude Code chat to pull the latest sheet data', 'success');
  };

  document.getElementById('generate-slack-draft-btn').onclick = async () => {
    toast('Generating draft...');
    const res = await API.post('/api/tech-forecast/preread/draft', {});
    document.getElementById('slack-draft-text').value = res.draft;
    toast('Draft generated', 'success');
  };
  document.getElementById('copy-slack-draft-btn').onclick = async () => {
    await navigator.clipboard.writeText(document.getElementById('slack-draft-text').value);
    toast('Copied', 'success');
  };
}

/* ── Person detail ──────────────────────────────────────────────────────── */
async function renderPerson(repId) {
  const [rep, deals, notes] = await Promise.all([
    API.get('/api/reps').then(reps => reps.find(r => r.id === repId)),
    API.get(`/api/reps/${repId}/deals`),
    API.get(`/api/reps/${repId}/slack`),
  ]);
  state.currentRep = rep;

  const period = new Date().getFullYear() + '-H' + (new Date().getMonth() < 6 ? '1' : '2');
  const review = await API.get(`/api/reps/${repId}/reviews/${period}`);

  const el = document.getElementById('person-content');
  el.innerHTML = `
    <div class="section-header">
      <h2>${rep.name} ${rep.active ? '' : '<span class="badge badge-muted">Inactive / departed</span>'}</h2>
    </div>
    <div class="tabs">
      <button class="tab-btn active" data-tab="deals">Deals (${deals.length})</button>
      <button class="tab-btn" data-tab="slack">Slack activity (${notes.length})</button>
      <button class="tab-btn" data-tab="review">Review draft — ${period} ${reviewStatusBadge(review?.status)}</button>
    </div>
    <div id="tab-deals" class="tab-panel">
      <div class="card">
        <table>
          <thead><tr><th>Opportunity</th><th>Stage</th><th>Close date</th><th>Amount</th><th>Mgr notes</th></tr></thead>
          <tbody>
            ${deals.map(d => `<tr><td>${oppLink(d.opportunity_name, d.opportunity_url)}</td><td>${stageBadge(d.stage)}</td><td>${d.close_date || '-'}</td><td>${fmtMoney(d.amount)}</td><td>${d.se_manager_notes || '-'}</td></tr>`).join('') || '<tr><td colspan="5"><div class="empty-state">No deals on file</div></td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    <div id="tab-slack" class="tab-panel" style="display:none">
      ${notes.map(n => `<div class="slack-note"><div class="meta">#${n.channel_name || n.channel_id} · ${n.posted_at || ''}</div>${n.text || ''}</div>`).join('') || '<div class="empty-state">No Slack activity synced yet</div>'}
    </div>
    <div id="tab-review" class="tab-panel" style="display:none">
      <div class="card">
        <div class="card-title">ARR — full fiscal year vs target</div>
        ${arrGoalBar(rep.arr_total, rep.arr_target)}
      </div>
      <div class="filter-row">
        <button class="btn btn-primary" id="generate-review-btn">Generate draft from deals + Slack</button>
        <button class="btn" id="save-review-btn">Save draft</button>
        <button class="btn" id="mark-final-btn">Mark final</button>
      </div>
      <textarea id="review-text" placeholder="Click 'Generate draft' or write manually...">${review?.content || ''}</textarea>
    </div>
  `;

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).style.display = 'block';
    };
  });

  document.getElementById('generate-review-btn').onclick = async () => {
    toast('Generating draft...');
    const res = await API.post(`/api/reps/${repId}/reviews/${period}/generate`, {});
    if (res.error) { toast(res.error, 'error'); return; }
    document.getElementById('review-text').value = res.content;
    toast('Draft generated', 'success');
  };
  document.getElementById('save-review-btn').onclick = async () => {
    const content = document.getElementById('review-text').value;
    await API.post(`/api/reps/${repId}/reviews/${period}`, { content, status: 'draft' });
    toast('Saved', 'success');
  };
  document.getElementById('mark-final-btn').onclick = async () => {
    const content = document.getElementById('review-text').value;
    await API.post(`/api/reps/${repId}/reviews/${period}`, { content, status: 'final' });
    toast('Marked final', 'success');
    renderPerson(repId);
  };
}

/* ── Settings ────────────────────────────────────────────────────────────── */
async function renderSettings() {
  state.settings = await API.get('/api/settings');
  const s = state.settings;
  const el = document.getElementById('settings-content');

  el.innerHTML = `
    <div class="card">
      <div class="card-title">Google Sheets — Team Tracking Sheet</div>
      <p style="color:var(--text-secondary);font-size:.84rem;margin-bottom:10px">
        ${s.google_sheets_configured ? '<span class="badge badge-green">Configured</span>' : '<span class="badge badge-red">Not configured</span>'}
        — see SETUP.md for the service-account setup steps.
      </p>
      <p style="font-size:.78rem;color:var(--text-muted);margin-bottom:10px">Last synced: ${s.deals_last_synced_at || 'never'}</p>
      <button class="btn btn-primary" id="sync-sheets-btn">Sync deals now</button>
    </div>

    <div class="card">
      <div class="card-title">Slack</div>
      <p style="color:var(--text-secondary);font-size:.84rem;margin-bottom:10px">
        ${s.slack_configured ? '<span class="badge badge-green">Configured</span>' : '<span class="badge badge-red">Not configured</span>'}
        — requires a Slack user token (search.messages doesn't work with a bot token). See SETUP.md.
      </p>
      <button class="btn btn-primary" id="sync-slack-btn">Sync Slack activity now</button>
    </div>

    <div class="card">
      <div class="card-title">Review drafting (LiteLLM)</div>
      <p style="color:var(--text-secondary);font-size:.84rem">
        ${s.litellm_configured ? '<span class="badge badge-green">Configured</span>' : '<span class="badge badge-red">Not configured</span>'}
      </p>
    </div>

    <div class="card">
      <div class="card-title">Gong</div>
      <p style="color:var(--text-muted);font-size:.84rem">Coming soon — you're wiring this one up yourself.</p>
    </div>
  `;

  document.getElementById('sync-sheets-btn').onclick = async () => {
    toast('Syncing deals from Google Sheets...');
    const res = await API.post('/api/sync/sheets');
    if (res.error) { toast(res.error, 'error'); return; }
    toast(`Synced ${res.synced} deals`, 'success');
    renderSettings();
  };
  document.getElementById('sync-slack-btn').onclick = async () => {
    toast('Syncing Slack activity...');
    const res = await API.post('/api/sync/slack');
    if (res.error) { toast(res.error, 'error'); return; }
    toast('Slack sync complete', 'success');
    renderSettings();
  };
}

/* ── Theme toggle ────────────────────────────────────────────────────────── */
function applyTheme(light) {
  document.body.classList.toggle('light-mode', light);
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) btn.innerHTML = light ? '&#127769; Dark mode' : '&#9728; Light mode';
}

document.addEventListener('DOMContentLoaded', () => {
  applyTheme(localStorage.getItem('theme') === 'light');
  document.getElementById('theme-toggle-btn').onclick = () => {
    const light = !document.body.classList.contains('light-mode');
    localStorage.setItem('theme', light ? 'light' : 'dark');
    applyTheme(light);
  };
  navigate('dashboard');
});
