export function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function oppLink(name, url) {
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {name}
    </a>
  ) : (
    name
  );
}

export function truncate(text, n) {
  if (!text) return text;
  return text.length > n ? text.slice(0, n) + '...' : text;
}

export function presalesStageBadge(stage) {
  const cls = stage === '6 - Technical Win' ? 'badge-green' : 'badge-blue';
  return <span className={`badge ${cls}`}>{stage || '-'}</span>;
}

export function salesStageBadge(stage) {
  const map = { '10 - Closed/Won': 'badge-green', '11- Closed/Lost': 'badge-red' };
  return <span className={`badge ${map[stage] || 'badge-blue'}`}>{stage || '-'}</span>;
}

export function forecastStatusBadge(status) {
  const map = { Strong: 'badge-green', Forecasted: 'badge-blue', 'Forecasted Risk': 'badge-red' };
  return <span className={`badge ${map[status] || 'badge-muted'}`}>{status || '-'}</span>;
}

export function DealFlags({ d }) {
  return (
    <div className="pill-row">
      {d.notes_stale && <span className="badge badge-amber">No update this week</span>}
      {!d.pre_sales_next_steps && <span className="badge badge-amber">No TW Strategy</span>}
      {d.needs_lead_se && <span className="badge badge-amber">No Lead SE (sheet)</span>}
    </div>
  );
}

export function SeAssignSelect({ d, reps, onAssign }) {
  return (
    <select
      className="se-assign-select"
      value={d.effective_se_rep_id || ''}
      onChange={(e) => onAssign(d.sheet_key, e.target.value)}
    >
      <option value="">Unassigned</option>
      {reps.map((r) => (
        <option key={r.id} value={r.id}>
          {r.name}
        </option>
      ))}
    </select>
  );
}
