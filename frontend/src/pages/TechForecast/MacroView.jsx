import { fmtMoney } from './dealHelpers.jsx';

// A bare quarter number can't be judged without knowing where it came from.
// Both pieces render only when there is something real to say: the delta is
// null (not zero) when no prior snapshot exists, and the sparkline needs two
// points to be a shape rather than a dot.
function ArrDelta({ value }) {
  if (value == null || value === 0) return null;
  const up = value > 0;
  return (
    <div className={`stat-delta ${up ? 'is-up' : 'is-down'}`}>
      {up ? '▲' : '▼'} {fmtMoney(Math.abs(value))} since last sync
    </div>
  );
}

function Sparkline({ points }) {
  if (!points || points.length < 2) return null;
  const w = 76;
  const h = 26;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const step = w / (points.length - 1);
  const xy = points.map((v, i) => [i * step, h - ((v - min) / span) * (h - 4) - 2]);
  const d = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const [lx, ly] = xy[xy.length - 1];
  return (
    <svg className="stat-spark" viewBox={`0 0 ${w} ${h}`} width={w} height={h}
         role="img" aria-label={`Trend over the last ${points.length} syncs`}>
      <path d={d} fill="none" stroke="var(--okta-blue-lt)" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="2.6" fill="var(--okta-blue-lt)" />
    </svg>
  );
}

function scrollToSection(targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const details = el.matches('details') ? el : el.closest('details');
  if (details) details.open = true;
  el.scrollIntoView({ behavior: 'smooth' });
}

export default function MacroView({ deals, data }) {
  const history = data.arr_history || [];
  const currentSeries = history.map((h) => h.current_arr);
  const nextSeries = history.map((h) => h.next_arr);
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
        <div className="stat-head">
          <div>
            <div className="stat-value">{fmtMoney(data.current_quarter_arr)}</div>
            <div className="stat-label">Current Quarter ARR — {data.current_quarter_label}</div>
          </div>
          <Sparkline points={currentSeries} />
        </div>
        <ArrDelta value={data.current_quarter_arr_delta} />
      </div>
      <div
        className="stat-card clickable"
        onClick={() => scrollToSection('next-quarter-section')}
      >
        <div className="stat-head">
          <div>
            <div className="stat-value">{fmtMoney(data.next_quarter_arr)}</div>
            <div className="stat-label">Next Quarter ARR — {data.next_quarter_label}</div>
          </div>
          <Sparkline points={nextSeries} />
        </div>
        <ArrDelta value={data.next_quarter_arr_delta} />
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
