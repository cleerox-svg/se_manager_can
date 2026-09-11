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

function pctBar(pct, opts = {}) {
  const { modifier = '', countLabel = '' } = opts;
  const p = Math.round((pct || 0) * 100);
  return (
    <div className="goal-bar-wrap">
      <div className="goal-bar">
        <div className={`goal-bar-fill ${modifier}`} style={{ width: `${p}%` }} />
      </div>
      <div className="goal-bar-label">
        <span>{countLabel}</span>
        <span className="pct">{p}%</span>
      </div>
    </div>
  );
}

function WinRateRepRow({ r }) {
  return (
    <div className="winrate-rep-row">
      <div className="winrate-rep-name">{r.rep_name}</div>
      <div className="winrate-rep-bars">
        <div className="winrate-rep-bar">
          <span className="winrate-rep-bar-label">Closed Won</span>
          {pctBar(r.closed_won_pct, { countLabel: `${r.closed_won}/${r.total}` })}
        </div>
        <div className="winrate-rep-bar">
          <span className="winrate-rep-bar-label">Tech Win</span>
          {pctBar(r.tech_win_pct, { modifier: 'accent', countLabel: `${r.tech_win}/${r.total}` })}
        </div>
      </div>
    </div>
  );
}

function WinRateSummary({ summary }) {
  const team = summary.team;
  return (
    <>
      <div className="winrate-team">
        <div className="winrate-team-metric">
          <div className="winrate-team-metric-label">Closed Won</div>
          {pctBar(team.closed_won_pct, { countLabel: `${team.closed_won}/${team.total}` })}
        </div>
        <div className="winrate-team-metric">
          <div className="winrate-team-metric-label">Tech Win</div>
          {pctBar(team.tech_win_pct, { modifier: 'accent', countLabel: `${team.tech_win}/${team.total}` })}
        </div>
      </div>
      <div className="winrate-reps">
        {summary.reps.map((r) => (
          <WinRateRepRow key={r.rep_id} r={r} />
        ))}
      </div>
    </>
  );
}

function WrapUpRow({ d, reps, onAssign }) {
  return (
    <tr>
      <td>
        {oppLink(d.opportunity_name, d.opportunity_url)}
        <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>AE: {d.opportunity_owner || '-'}</div>
      </td>
      <td>{forecastStatusBadge(d.forecast_status)}</td>
      <td>{fmtMoney(d.amount)}</td>
      <td>
        <SeAssignSelect d={d} reps={reps} onAssign={onAssign} />
      </td>
      <td>
        <DealFlags d={d} />
      </td>
    </tr>
  );
}

export function WinRateClosedDeals({ winRateSummary }) {
  return (
    <div className="card">
      <div className="card-title">Win Rate — Closed Deals</div>
      {winRateSummary ? <WinRateSummary summary={winRateSummary} /> : <div className="empty-state">Loading...</div>}
    </div>
  );
}

export default function WrapUpRisk({ deals, reps, onAssigned }) {
  const [busy, setBusy] = useState(false);

  const wrapUpDeals = deals
    .filter((d) => d.presales_stage !== '6 - Technical Win' && (d.forecast_status === 'Forecasted Risk' || d.notes_stale))
    .sort((a, b) => (b.amount || 0) - (a.amount || 0));

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
    <div className="card">
      <div className="card-title">Wrap-Up &amp; Risk ({wrapUpDeals.length})</div>
      {wrapUpDeals.length ? (
        <div className="table-scroll" style={busy ? { opacity: 0.6, pointerEvents: 'none' } : undefined}>
          <table>
            <thead>
              <tr>
                <th>Opportunity</th>
                <th>Forecast Status</th>
                <th>Amount</th>
                <th>SE</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {wrapUpDeals.map((d) => (
                <WrapUpRow key={d.sheet_key || d.opportunity_id} d={d} reps={reps} onAssign={handleAssign} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">Nothing at risk right now</div>
      )}
    </div>
  );
}
