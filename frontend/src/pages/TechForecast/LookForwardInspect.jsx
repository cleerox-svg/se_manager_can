import { useState } from 'react';
import { assignSe } from '../../api.js';
import { toast } from '../../toast.js';

function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function oppLink(name, url) {
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {name}
    </a>
  ) : (
    name
  );
}

function truncate(text, n) {
  if (!text) return text;
  return text.length > n ? text.slice(0, n) + '...' : text;
}

function presalesStageBadge(stage) {
  const cls = stage === '6 - Technical Win' ? 'badge-green' : 'badge-blue';
  return <span className={`badge ${cls}`}>{stage || '-'}</span>;
}

function forecastStatusBadge(status) {
  const map = { Strong: 'badge-green', Forecasted: 'badge-blue', 'Forecasted Risk': 'badge-red' };
  return <span className={`badge ${map[status] || 'badge-muted'}`}>{status || '-'}</span>;
}

function DealFlags({ d }) {
  return (
    <div className="pill-row">
      {d.notes_stale && <span className="badge badge-amber">No update this week</span>}
      {!d.pre_sales_next_steps && <span className="badge badge-amber">No TW Strategy</span>}
      {d.needs_lead_se && <span className="badge badge-amber">No Lead SE (sheet)</span>}
    </div>
  );
}

function NotesCell({ text, maxWidth }) {
  return (
    <td title={text || ''} style={{ maxWidth, fontSize: '.78rem', color: 'var(--text-secondary)' }}>
      {truncate(text, 90) || '-'}
    </td>
  );
}

function SeAssignSelect({ d, reps, onAssign }) {
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

function InspectRow({ d, reps, onAssign }) {
  return (
    <tr>
      <td>
        {oppLink(d.opportunity_name, d.opportunity_url)}
        <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>AE: {d.opportunity_owner || '-'}</div>
      </td>
      <td>{d.sales_stage || '-'}</td>
      <td>{presalesStageBadge(d.presales_stage)}</td>
      <td>{forecastStatusBadge(d.forecast_status)}</td>
      <td>{d.technical_win_date || '-'}</td>
      <td>{fmtMoney(d.amount)}</td>
      <td>
        <SeAssignSelect d={d} reps={reps} onAssign={onAssign} />
      </td>
      <td>
        <DealFlags d={d} />
      </td>
      <NotesCell text={d.pre_sales_notes} maxWidth={220} />
      <NotesCell text={d.pre_sales_next_steps} maxWidth={220} />
      <NotesCell text={d.se_manager_notes} maxWidth={220} />
    </tr>
  );
}

function NeedsLeadSeRow({ r }) {
  return (
    <tr>
      <td>{oppLink(r.opportunity_name, r.opportunity_url)}</td>
      <td>{r.opportunity_owner || '-'}</td>
      <td>{presalesStageBadge(r.presales_stage)}</td>
      <td>{forecastStatusBadge(r.forecast_status)}</td>
      <td>{fmtMoney(r.amount)}</td>
    </tr>
  );
}

export default function LookForwardInspect({ deals, reps, onAssigned }) {
  const [busy, setBusy] = useState(false);

  const needsLeadSeDeals = deals
    .filter((d) => d.needs_lead_se)
    .sort((a, b) => (b.amount || 0) - (a.amount || 0));
  const inspectDeals = deals.filter((d) => d.presales_stage !== '6 - Technical Win');

  async function handleAssign(sheetKey, value) {
    setBusy(true);
    try {
      await assignSe(sheetKey, value ? Number(value) : null);
      toast('SE assignment updated', 'success');
      await onAssigned?.();
    } catch {
      toast('Failed to update SE assignment', 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-title">Needs Lead SE ({needsLeadSeDeals.length})</div>
        {needsLeadSeDeals.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Opportunity</th>
                  <th>AE</th>
                  <th>Presales Stage</th>
                  <th>Forecast Status</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {needsLeadSeDeals.map((r) => (
                  <NeedsLeadSeRow key={r.sheet_key || r.opportunity_id} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">Every deal in the sheet has a Lead SE set</div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Look Forward &amp; Inspect — Open Pipeline ({inspectDeals.length})</div>
        {inspectDeals.length ? (
          <div className="table-scroll" style={busy ? { opacity: 0.6, pointerEvents: 'none' } : undefined}>
            <table>
              <thead>
                <tr>
                  <th>Opportunity</th>
                  <th>Stage</th>
                  <th>Presales Stage</th>
                  <th>Forecast Status</th>
                  <th>Tech win date</th>
                  <th>Amount</th>
                  <th>SE</th>
                  <th>Flags</th>
                  <th>Pre-sales notes</th>
                  <th>Pre-sales next steps</th>
                  <th>SE manager notes</th>
                </tr>
              </thead>
              <tbody>
                {inspectDeals.map((d) => (
                  <InspectRow key={d.sheet_key || d.opportunity_id} d={d} reps={reps} onAssign={handleAssign} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">No open deals synced yet</div>
        )}
      </div>
    </>
  );
}
