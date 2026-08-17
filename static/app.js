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
              <td class="pill-row">
                ${d.poc ? '<span class="badge badge-purple">POC</span>' : ''}
                ${d.se_needed ? '<span class="badge badge-amber">SE Needed</span>' : ''}
              </td>
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

  el.innerHTML = `
    <div class="card">
      <table>
        <thead><tr><th>Name</th><th>Title</th><th>Deals</th><th>Status</th><th></th></tr></thead>
        <tbody>
          ${state.reps.map(r => `
            <tr class="clickable ${r.active ? '' : 'inactive-flag'}" onclick="navigate('person', ${r.id})">
              <td>${r.name}</td>
              <td>${r.title || '-'}</td>
              <td>${r.deal_count}</td>
              <td>${r.active ? '<span class="badge badge-green">Active</span>' : '<span class="badge badge-muted">Inactive / departed</span>'}</td>
              <td><button class="btn" onclick="event.stopPropagation(); toggleRepActive(${r.id}, ${r.active ? 0 : 1})">${r.active ? 'Mark inactive' : 'Mark active'}</button></td>
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
      <button class="tab-btn" data-tab="review">Review draft — ${period}</button>
    </div>
    <div id="tab-deals" class="tab-panel">
      <div class="card">
        <table>
          <thead><tr><th>Opportunity</th><th>Stage</th><th>Close date</th><th>Amount</th><th>Mgr notes</th></tr></thead>
          <tbody>
            ${deals.map(d => `<tr><td>${d.opportunity_name}</td><td>${stageBadge(d.stage)}</td><td>${d.close_date || '-'}</td><td>${fmtMoney(d.amount)}</td><td>${d.se_manager_notes || '-'}</td></tr>`).join('') || '<tr><td colspan="5"><div class="empty-state">No deals on file</div></td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    <div id="tab-slack" class="tab-panel" style="display:none">
      ${notes.map(n => `<div class="slack-note"><div class="meta">#${n.channel_name || n.channel_id} · ${n.posted_at || ''}</div>${n.text || ''}</div>`).join('') || '<div class="empty-state">No Slack activity synced yet</div>'}
    </div>
    <div id="tab-review" class="tab-panel" style="display:none">
      <div class="filter-row">
        <button class="btn btn-primary" id="generate-review-btn">Generate draft from deals + Slack</button>
        <button class="btn" id="save-review-btn">Save draft</button>
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

document.addEventListener('DOMContentLoaded', () => navigate('dashboard'));
