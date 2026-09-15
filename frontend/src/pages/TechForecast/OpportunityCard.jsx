import {
  fmtMoney,
  oppLink,
  presalesStageBadge,
  salesStageBadge,
  DealFlags,
  SeAssignSelect,
  BackupSeAssignSelect,
} from './dealHelpers.jsx';

export default function OpportunityCard({ d, reps, onAssign, onAssignBackup }) {
  return (
    <div className="opp-card">
      <div className="opp-card-header">
        <div className="opp-card-header-main">
          {oppLink(d.opportunity_name, d.opportunity_url)}
          {d.opportunity_owner && (
            <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>AE: {d.opportunity_owner}</div>
          )}
        </div>
        <div className="opp-card-header-fields">
          <span>
            <span className="opp-card-field-label">Presales Stage</span>
            {presalesStageBadge(d.presales_stage)}
          </span>
          <span>
            <span className="opp-card-field-label">Confidence</span>
            {d.confidence || '-'}
          </span>
          {d.billing_state_province && (
            <span>
              <span className="opp-card-field-label">Billing State/Province</span>
              {d.billing_state_province}
            </span>
          )}
          <span>
            <span className="opp-card-field-label">Amount</span>
            {fmtMoney(d.amount)}
          </span>
        </div>
      </div>

      <div className="opp-card-meta">
        <SeAssignSelect d={d} reps={reps} onAssign={onAssign} />
        <BackupSeAssignSelect d={d} reps={reps} onAssign={onAssignBackup} />
        <DealFlags d={d} />
        {salesStageBadge(d.sales_stage)}
        <span>
          <span className="opp-card-field-label">Tech win date</span>
          {d.technical_win_date || '-'}
        </span>
      </div>

      <div className="opp-card-notes">
        <div className="opp-note-box">
          <div className="opp-note-label">Pre-Sales Notes</div>
          <div className={`opp-note-text${d.pre_sales_notes ? '' : ' is-empty'}`}>{d.pre_sales_notes || 'No notes'}</div>
        </div>
        <div className="opp-note-box">
          <div className="opp-note-label">Pre-Sales Next Steps</div>
          <div className={`opp-note-text${d.pre_sales_next_steps ? '' : ' is-empty'}`}>
            {d.pre_sales_next_steps || 'No notes'}
          </div>
        </div>
        <div className="opp-note-box">
          <div className="opp-note-label">SE Manager Notes</div>
          <div className={`opp-note-text${d.se_manager_notes ? '' : ' is-empty'}`}>{d.se_manager_notes || 'No notes'}</div>
        </div>
      </div>
    </div>
  );
}
