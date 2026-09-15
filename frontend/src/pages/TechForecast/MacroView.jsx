import { fmtMoney } from './dealHelpers.jsx';

function scrollToSection(targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const details = el.matches('details') ? el : el.closest('details');
  if (details) details.open = true;
  el.scrollIntoView({ behavior: 'smooth' });
}

export default function MacroView({ deals, data }) {
  const riskDeals = deals.filter((d) => d.forecast_status === 'Forecasted Risk');
  const staleDeals = deals.filter((d) => d.notes_stale);
  const needsLeadSeDeals = deals
    .filter((d) => d.needs_lead_se)
    .sort((a, b) => (b.amount || 0) - (a.amount || 0));
  const needsLeadSeAmount = needsLeadSeDeals.reduce((s, d) => s + (d.amount || 0), 0);

  return (
    <div className="stat-grid">
      <div
        className="stat-card clickable"
        onClick={() => scrollToSection('current-quarter-section')}
      >
        <div className="stat-value">{fmtMoney(data.current_quarter_arr)}</div>
        <div className="stat-label">Current Quarter ARR — {data.current_quarter_label}</div>
      </div>
      <div
        className="stat-card clickable"
        onClick={() => scrollToSection('next-quarter-section')}
      >
        <div className="stat-value">{fmtMoney(data.next_quarter_arr)}</div>
        <div className="stat-label">Next Quarter ARR — {data.next_quarter_label}</div>
      </div>
      <div className="stat-card clickable" onClick={() => scrollToSection('risk-section')}>
        <div className="stat-value">{riskDeals.length}</div>
        <div className="stat-label">Forecasted Risk</div>
      </div>
      <div className="stat-card clickable" onClick={() => scrollToSection('stale-section')}>
        <div className="stat-value">{staleDeals.length}</div>
        <div className="stat-label">No update this week</div>
      </div>
      <div className="stat-card clickable" onClick={() => scrollToSection('needs-lead-se-section')}>
        <div className="stat-value">{needsLeadSeDeals.length}</div>
        <div className="stat-label">Needs Lead SE — {fmtMoney(needsLeadSeAmount)}</div>
      </div>
    </div>
  );
}
