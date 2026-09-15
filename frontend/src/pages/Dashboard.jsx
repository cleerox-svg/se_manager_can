import { useEffect, useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import {
  getClosedDealsSummary, getDashboardArrTrend, getDashboardFunnel, getDashboardTechWinTrend,
} from '../api.js';

function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function fmtPct(n) {
  if (n == null) return '-';
  return Math.round(n * 100) + '%';
}

function fmtDate(d) {
  const dt = new Date(d + 'T00:00:00');
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

const BUCKET_ORDER = ['Technical Win', 'Final Due Diligence', 'Validate Solution', 'Early Tech', 'Untagged'];
// Presales stage is a progression (Early Tech -> Validate Solution -> Final Due
// Diligence -> Technical Win), so these step along one hue instead of taking
// four unrelated ones: the stack then reads in stage order without consulting
// the legend. Untagged means "no stage recorded", so it takes the recessive
// neutral — as a saturated grey it was the heaviest mark on the chart despite
// carrying the least meaning.
const BUCKET_COLORS = {
  'Technical Win': 'var(--stage-4)',
  'Final Due Diligence': 'var(--stage-3)',
  'Validate Solution': 'var(--stage-2)',
  'Early Tech': 'var(--stage-1)',
  Untagged: 'var(--stage-none)',
};

// Recharts colours legend text with the series colour by default, which is
// unreadable once the series are steps of one ramp — the lightest step is a
// large-area fill, not a text colour. Identity stays with the swatch; the
// label wears the theme's text token.
function legendLabel(value) {
  return <span style={{ color: 'var(--text-secondary)' }}>{value}</span>;
}

function moneyTick(v) {
  if (v >= 1000000) return '$' + (v / 1000000).toFixed(1) + 'M';
  if (v >= 1000) return '$' + Math.round(v / 1000) + 'K';
  return '$' + v;
}

function TooltipCard({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="card" style={{ padding: '8px 12px', boxShadow: 'var(--depth-raised)' }}>
      <div style={{ fontSize: '.74rem', color: 'var(--text-secondary)', marginBottom: 4 }}>{label}</div>
      {/* A swatch carries the series identity; the text stays on the theme's
          ink, since the pale end of the stage ramp is a fill colour and not a
          legible text colour. */}
      {payload.map((p) => (
        <div key={p.name} style={{ fontSize: '.8rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: p.color, flex: '0 0 auto' }} />
          {p.name}: {fmtMoney(p.value)}
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [arrTrend, setArrTrend] = useState([]);
  const [funnel, setFunnel] = useState([]);
  const [techWinTrend, setTechWinTrend] = useState([]);

  useEffect(() => {
    getClosedDealsSummary().then((res) => setSummary(res.team));
    getDashboardArrTrend().then(setArrTrend);
    getDashboardFunnel().then(setFunnel);
    getDashboardTechWinTrend().then(setTechWinTrend);
  }, []);

  const arrTrendData = arrTrend.map((row) => ({
    date: fmtDate(row.snapshot_date),
    'Technical Win': row.tech_won_amount,
    'In Flight': row.in_flight_amount,
    Untagged: row.untagged_amount,
  }));

  const funnelStatuses = [...new Set(funnel.map((f) => f.confidence))]
    .filter(Boolean)
    .sort();
  const funnelData = funnelStatuses.map((status) => {
    const row = funnel.find((f) => f.confidence === status);
    const entry = { confidence: status };
    BUCKET_ORDER.forEach((b) => { entry[b] = 0; });
    (row?.stages || []).forEach((s) => { entry[s.bucket] = s.amount; });
    return entry;
  });

  const techWinData = techWinTrend.map((row) => ({
    quarter: row.fiscal_quarter,
    'Tech Win ARR': row.amount,
  }));

  return (
    <>
      {/* No page heading here — the topbar already names the page. Repeating
          it cost ~60px above the fold on every screen. */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{summary ? summary.total : '-'}</div>
          <div className="stat-label">Closed deals</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{summary ? summary.closed_won : '-'}</div>
          <div className="stat-label">Closed won ({summary ? fmtPct(summary.closed_won_pct) : '-'})</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{summary ? summary.tech_win : '-'}</div>
          <div className="stat-label">Technical wins ({summary ? fmtPct(summary.tech_win_pct) : '-'})</div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">ARR trend</div>
        {arrTrendData.length === 0 ? (
          <div className="chart-empty">
            <strong>No history yet</strong>
            <span>A point is recorded each time the tech forecast syncs. The first line appears after two syncs.</span>
          </div>
        ) : (
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={arrTrendData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" stroke="var(--text-secondary)" fontSize={12} />
            <YAxis stroke="var(--text-secondary)" fontSize={12} tickFormatter={moneyTick} />
            <Tooltip content={<TooltipCard />} />
            <Legend wrapperStyle={{ fontSize: '.78rem' }} formatter={legendLabel} />
            <Area type="monotone" dataKey="Technical Win" stackId="1" stroke="var(--stage-5)" fill="var(--stage-5)" fillOpacity={0.8} />
            <Area type="monotone" dataKey="In Flight" stackId="1" stroke="var(--stage-3)" fill="var(--stage-3)" fillOpacity={0.8} />
            <Area type="monotone" dataKey="Untagged" stackId="1" stroke="var(--stage-none)" fill="var(--stage-none)" fillOpacity={0.8} />
          </AreaChart>
        </ResponsiveContainer>
        )}
      </div>

      <div className="card">
        <div className="card-title">Pipeline funnel by confidence</div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={funnelData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="confidence" stroke="var(--text-secondary)" fontSize={12} />
            <YAxis stroke="var(--text-secondary)" fontSize={12} tickFormatter={moneyTick} />
            <Tooltip content={<TooltipCard />} />
            <Legend wrapperStyle={{ fontSize: '.78rem' }} formatter={legendLabel} />
            {BUCKET_ORDER.map((bucket) => (
              // 2px surface-coloured stroke separates adjacent stacked
              // segments, which matters more now the fills are neighbouring
              // steps of one hue rather than contrasting colours.
              <Bar key={bucket} dataKey={bucket} stackId="stage" fill={BUCKET_COLORS[bucket]}
                   stroke="var(--bg-card)" strokeWidth={2} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <div className="card-title">Technical win ARR by quarter</div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={techWinData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="quarter" stroke="var(--text-secondary)" fontSize={12} />
            <YAxis stroke="var(--text-secondary)" fontSize={12} tickFormatter={moneyTick} />
            <Tooltip content={<TooltipCard />} />
            <Bar dataKey="Tech Win ARR" fill="var(--okta-blue)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
