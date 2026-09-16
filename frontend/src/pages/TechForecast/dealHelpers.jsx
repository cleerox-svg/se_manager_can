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
  // A deal that isn't staged yet gets a plain dash rather than an empty pill —
  // a badge with nothing in it reads as a rendering fault.
  if (!stage) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const cls = stage === '6 - Technical Win' ? 'badge-green' : 'badge-blue';
  return <span className={`badge ${cls}`}>{stage}</span>;
}

export function salesStageBadge(stage) {
  const map = { '10 - Closed/Won': 'badge-green', '11- Closed/Lost': 'badge-red' };
  return <span className={`badge ${map[stage] || 'badge-blue'}`}>{stage || '-'}</span>;
}

// How long a deal has actually been sitting, which is what decides whether it
// gets raised on the Monday call — "unchanged for a month" is a different
// conversation from "unchanged since Friday". Falls back to the undated wording
// for rows synced before notes_last_changed_at existed, where we genuinely
// don't know when the text last moved.
export function staleLabel(d) {
  const since = d.notes_last_changed_at;
  if (!since) return 'No update this week';
  const days = Math.floor((Date.now() - new Date(since).getTime()) / 86400000);
  if (!Number.isFinite(days) || days < 0) return 'No update this week';
  if (days < 14) return 'No update this week';
  const weeks = Math.floor(days / 7);
  return weeks < 9 ? `Stale ${weeks} weeks` : 'Stale 2+ months';
}

export function DealFlags({ d }) {
  // Flags carry a severity so the row that needs raising on Monday doesn't look
  // identical to the row that's merely untidy: nobody owning the deal is worse
  // than stale notes, which is worse than a missing strategy note.
  // `notes_stale` is a SQLite integer, so it needs the !! — a bare `0 && ...`
  // evaluates to 0 and React renders the character.
  return (
    <div className="pill-row">
      {!!d.lead_se_unmatched && (
        <span className="badge badge-red" title={`The sheet says "${d.lead_se_name}", which doesn't match anyone on the Team page`}>
          SE not on roster: {d.lead_se_name}
        </span>
      )}
      {!!d.needs_lead_se && !d.lead_se_unmatched && (
        <span className="badge badge-red">No Lead SE</span>
      )}
      {!!d.notes_stale && <span className="badge badge-amber">{staleLabel(d)}</span>}
      {!d.pre_sales_next_steps && <span className="badge badge-muted">No TW strategy</span>}
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

export function BackupSeAssignSelect({ d, reps, onAssign }) {
  return (
    <select
      className="backup-se-assign-select"
      title={d.backup_note || undefined}
      value={d.backup_se_rep_id || ''}
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

