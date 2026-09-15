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
const BUCKET_COLORS = {
  'Technical Win': 'var(--green)',
  'Final Due Diligence': 'var(--okta-blue-lt)',
  'Validate Solution': 'var(--purple)',
  'Early Tech': 'var(--amber)',
  Untagged: 'var(--text-muted)',
};

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
      {payload.map((p) => (
        <div key={p.name} style={{ fontSize: '.8rem', color: p.color }}>
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
      <div className="section-header">
        <h2>Dashboard</h2>
      </div>

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
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={arrTrendData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" stroke="var(--text-secondary)" fontSize={12} />
            <YAxis stroke="var(--text-secondary)" fontSize={12} tickFormatter={moneyTick} />
            <Tooltip content={<TooltipCard />} />
            <Legend wrapperStyle={{ fontSize: '.78rem' }} />
            <Area type="monotone" dataKey="Technical Win" stackId="1" stroke="var(--green)" fill="var(--green)" fillOpacity={0.35} />
            <Area type="monotone" dataKey="In Flight" stackId="1" stroke="var(--okta-blue-lt)" fill="var(--okta-blue-lt)" fillOpacity={0.35} />
            <Area type="monotone" dataKey="Untagged" stackId="1" stroke="var(--text-muted)" fill="var(--text-muted)" fillOpacity={0.35} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <div className="card-title">Pipeline funnel by confidence</div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={funnelData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="confidence" stroke="var(--text-secondary)" fontSize={12} />
            <YAxis stroke="var(--text-secondary)" fontSize={12} tickFormatter={moneyTick} />
            <Tooltip content={<TooltipCard />} />
            <Legend wrapperStyle={{ fontSize: '.78rem' }} />
            {BUCKET_ORDER.map((bucket) => (
              <Bar key={bucket} dataKey={bucket} stackId="stage" fill={BUCKET_COLORS[bucket]} />
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
