function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export default function MacroView({ deals }) {
  const totalArr = deals.reduce((sum, d) => sum + (d.amount || 0), 0);
  const riskDeals = deals.filter((d) => d.forecast_status === 'Forecasted Risk');
  const staleDeals = deals.filter((d) => d.notes_stale);
  const needsLeadSeDeals = deals
    .filter((d) => d.needs_lead_se)
    .sort((a, b) => (b.amount || 0) - (a.amount || 0));
  const needsLeadSeAmount = needsLeadSeDeals.reduce((s, d) => s + (d.amount || 0), 0);

  return (
    <div className="stat-grid">
      <div className="stat-card">
        <div className="stat-value">{fmtMoney(totalArr)}</div>
        <div className="stat-label">Total Tech Forecast ARR</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{riskDeals.length}</div>
        <div className="stat-label">Forecasted Risk</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{staleDeals.length}</div>
        <div className="stat-label">No update this week</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{needsLeadSeDeals.length}</div>
        <div className="stat-label">Needs Lead SE — {fmtMoney(needsLeadSeAmount)}</div>
      </div>
    </div>
  );
}
