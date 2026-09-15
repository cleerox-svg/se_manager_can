import { useState } from 'react';
import { assignSe, assignBackupSe } from '../../api.js';
import { toast } from '../../toast.js';
import DealsTable from './DealsTable.jsx';
import { DealFlags, SeAssignSelect, BackupSeAssignSelect, fmtMoney, oppLink, presalesStageBadge } from './dealHelpers.jsx';

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
  const teamCurrentQuarter = summary.team_current_quarter;
  return (
    <>
      <div className="winrate-team">
        <div className="winrate-team-metric">
          <div className="winrate-team-metric-label">Closed Won — All Time</div>
          {pctBar(team.closed_won_pct, { countLabel: `${team.closed_won}/${team.total}` })}
        </div>
        <div className="winrate-team-metric">
          <div className="winrate-team-metric-label">Tech Win — All Time</div>
          {pctBar(team.tech_win_pct, { modifier: 'accent', countLabel: `${team.tech_win}/${team.total}` })}
        </div>
        {teamCurrentQuarter && (
          <>
            <div className="winrate-team-metric">
              <div className="winrate-team-metric-label">
                Closed Won — This Quarter — {teamCurrentQuarter.fiscal_quarter}
              </div>
              {pctBar(teamCurrentQuarter.closed_won_pct, {
                countLabel: `${teamCurrentQuarter.closed_won}/${teamCurrentQuarter.total}`,
              })}
            </div>
            <div className="winrate-team-metric">
              <div className="winrate-team-metric-label">
                Tech Win — This Quarter — {teamCurrentQuarter.fiscal_quarter}
              </div>
              {pctBar(teamCurrentQuarter.tech_win_pct, {
                modifier: 'accent',
                countLabel: `${teamCurrentQuarter.tech_win}/${teamCurrentQuarter.total}`,
              })}
            </div>
          </>
        )}
      </div>
      <div className="winrate-reps">
        {summary.reps.map((r) => (
          <WinRateRepRow key={r.rep_id} r={r} />
        ))}
      </div>
    </>
  );
}

function opportunityCell(d) {
  return (
    <>
      {oppLink(d.opportunity_name, d.opportunity_url)}
      <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>AE: {d.opportunity_owner || '-'}</div>
    </>
  );
}

function buildWrapUpColumns(reps, onAssign, onAssignBackup) {
  return [
    { key: 'opportunity', header: 'Opportunity', render: opportunityCell },
    { key: 'presales_stage', header: 'Presales Stage', render: (d) => presalesStageBadge(d.presales_stage) },
    { key: 'confidence', header: 'Confidence', render: (d) => d.confidence || '-' },
    { key: 'billing_state_province', header: 'Billing State/Province', render: (d) => d.billing_state_province || '-' },
    { key: 'amount', header: 'Amount', render: (d) => fmtMoney(d.amount) },
    { key: 'se', header: 'SE', render: (d) => <SeAssignSelect d={d} reps={reps} onAssign={onAssign} /> },
    { key: 'backup_se', header: 'Backup SE', render: (d) => <BackupSeAssignSelect d={d} reps={reps} onAssign={onAssignBackup} /> },
    { key: 'flags', header: 'Flags', render: (d) => <DealFlags d={d} /> },
  ];
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

  async function handleAssignBackup(sheetKey, value) {
    setBusy(true);
    try {
      await assignBackupSe(sheetKey, value ? Number(value) : null, null);
      toast('Backup SE assignment updated', 'success');
      await onAssigned?.();
    } catch {
      toast('Failed to update backup SE assignment', 'error');
    } finally {
      setBusy(false);
    }
  }

  const wrapUpColumns = buildWrapUpColumns(reps, handleAssign, handleAssignBackup);

  return (
    <div className="card" id="risk-section">
      <span id="stale-section" />
      <div className="card-title">Wrap-Up &amp; Risk ({wrapUpDeals.length})</div>
      {wrapUpDeals.length ? (
        <div className="table-scroll" style={busy ? { opacity: 0.6, pointerEvents: 'none' } : undefined}>
          <DealsTable deals={wrapUpDeals} columns={wrapUpColumns} />
        </div>
      ) : (
        <div className="empty-state">Nothing at risk right now</div>
      )}
    </div>
  );
}
