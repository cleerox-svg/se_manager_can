import { useState } from 'react';
import { assignSe, assignBackupSe } from '../../api.js';
import { toast } from '../../toast.js';
import DealsTable from './DealsTable.jsx';
import OpportunityCard from './OpportunityCard.jsx';
import { fmtMoney, oppLink, presalesStageBadge } from './dealHelpers.jsx';

const QUARTER_BUCKETS = [
  { key: 'overdue', label: 'Overdue' },
  { key: 'current', label: 'Current Quarter' },
  { key: 'next', label: 'Next Quarter' },
  { key: 'later', label: 'Later / Unscheduled' },
];

function bucketDeals(deals) {
  const byBucket = new Map(QUARTER_BUCKETS.map((b) => [b.key, []]));
  for (const d of deals) {
    const key = byBucket.has(d.quarter_bucket) ? d.quarter_bucket : 'later';
    byBucket.get(key).push(d);
  }
  return QUARTER_BUCKETS.map((b) => ({
    ...b,
    items: byBucket.get(b.key).sort((a, c) => (c.amount || 0) - (a.amount || 0)),
  })).filter((b) => b.items.length);
}

function opportunityCell(d) {
  return (
    <>
      {oppLink(d.opportunity_name, d.opportunity_url)}
      <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>AE: {d.opportunity_owner || '-'}</div>
    </>
  );
}

function buildNeedsLeadSeColumns() {
  return [
    { key: 'opportunity', header: 'Opportunity', render: opportunityCell },
    { key: 'presales_stage', header: 'Presales Stage', render: (d) => presalesStageBadge(d.presales_stage) },
    { key: 'confidence', header: 'Confidence', render: (d) => d.confidence || '-' },
    { key: 'billing_state_province', header: 'Billing State/Province', render: (d) => d.billing_state_province || '-' },
    { key: 'amount', header: 'Amount', render: (d) => fmtMoney(d.amount) },
  ];
}

export default function LookForwardInspect({ deals, reps, onAssigned }) {
  const [busy, setBusy] = useState(false);

  const needsLeadSeDeals = deals
    .filter((d) => d.needs_lead_se)
    .sort((a, b) => (b.amount || 0) - (a.amount || 0));
  const inspectBuckets = bucketDeals(deals.filter((d) => d.presales_stage !== '6 - Technical Win'));
  const inspectCount = inspectBuckets.reduce((s, b) => s + b.items.length, 0);

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

  const needsLeadSeColumns = buildNeedsLeadSeColumns();

  return (
    <>
      <div className="card" id="needs-lead-se-section">
        <div className="card-title">Needs Lead SE ({needsLeadSeDeals.length})</div>
        {needsLeadSeDeals.length ? (
          <div className="table-scroll">
            <DealsTable deals={needsLeadSeDeals} columns={needsLeadSeColumns} />
          </div>
        ) : (
          <div className="empty-state">Every deal in the sheet has a Lead SE set</div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Look Forward &amp; Inspect — Open Pipeline ({inspectCount})</div>
        {inspectCount ? (
          <div style={busy ? { opacity: 0.6, pointerEvents: 'none' } : undefined}>
            {inspectBuckets.map((b, bi) => {
              const bTotal = b.items.reduce((s, d) => s + (d.amount || 0), 0);
              const sectionId =
                b.key === 'current' ? 'current-quarter-section' : b.key === 'next' ? 'next-quarter-section' : undefined;
              return (
                <details
                  key={b.key}
                  id={sectionId}
                  className={`flyout wins-quarter${bi === 0 ? ' is-first' : ''}`}
                >
                  <summary>
                    {b.label} · {b.items.length} deal{b.items.length === 1 ? '' : 's'} · {fmtMoney(bTotal)}
                  </summary>
                  <div className="opp-card-list">
                    {b.items.map((d) => (
                      <OpportunityCard
                        key={d.sheet_key || d.opportunity_id}
                        d={d}
                        reps={reps}
                        onAssign={handleAssign}
                        onAssignBackup={handleAssignBackup}
                      />
                    ))}
                  </div>
                </details>
              );
            })}
          </div>
        ) : (
          <div className="empty-state">No open deals synced yet</div>
        )}
      </div>
    </>
  );
}
