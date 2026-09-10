import { useEffect, useRef, useState } from 'react';
import { getDeals } from '../api.js';

function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function stageBadge(stage) {
  const map = { 'Closed Won': 'badge-green', 'Closed Lost': 'badge-red' };
  const cls = map[stage] || 'badge-blue';
  return <span className={`badge ${cls}`}>{stage || '-'}</span>;
}

export default function Dashboard() {
  const [deals, setDeals] = useState([]);
  const [quarters, setQuarters] = useState([]);
  const [currentQuarter, setCurrentQuarter] = useState(null);
  const [quarterFilter, setQuarterFilter] = useState('current');
  const [stageFilter, setStageFilter] = useState('');
  const [searchFilter, setSearchFilter] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const debounceRef = useRef();

  useEffect(() => {
    let active = true;
    getDeals({ quarter: quarterFilter, stage: stageFilter, search: searchFilter }).then((data) => {
      if (!active) return;
      setDeals(data.deals);
      setQuarters(data.quarters);
      setCurrentQuarter(data.current_quarter);
    });
    return () => {
      active = false;
    };
  }, [quarterFilter, stageFilter, searchFilter]);

  function handleSearchInput(e) {
    const value = e.target.value;
    setSearchInput(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearchFilter(value), 300);
  }

  const totalAmount = deals.reduce((sum, d) => sum + (d.amount || 0), 0);
  const pocCount = deals.filter((d) => d.poc).length;
  const needSeCount = deals.filter((d) => d.se_needed).length;
  const stages = [...new Set(deals.map((d) => d.stage).filter(Boolean))];

  return (
    <>
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{deals.length}</div>
          <div className="stat-label">Deals in view</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{fmtMoney(totalAmount)}</div>
          <div className="stat-label">Total pipeline</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{pocCount}</div>
          <div className="stat-label">Active POCs</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{needSeCount}</div>
          <div className="stat-label">SE needed</div>
        </div>
      </div>

      <div className="filter-row">
        <select value={quarterFilter} onChange={(e) => setQuarterFilter(e.target.value)}>
          <option value="current">Current quarter ({currentQuarter})</option>
          <option value="all">All quarters</option>
          {quarters.map((q) => (
            <option key={q} value={q}>
              {q}
            </option>
          ))}
        </select>
        <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}>
          <option value="">All stages</option>
          {stages.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          type="search"
          placeholder="Search opportunity..."
          value={searchInput}
          onChange={handleSearchInput}
        />
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Opportunity</th>
              <th>SE</th>
              <th>Stage</th>
              <th>Close date</th>
              <th>Amount</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {deals.length ? (
              deals.map((d) => (
                <tr key={d.id}>
                  <td>
                    {d.opportunity_name}
                    <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>{d.geo_seg || ''}</div>
                  </td>
                  <td>{d.lead_se}</td>
                  <td>{stageBadge(d.stage)}</td>
                  <td>{d.close_date || '-'}</td>
                  <td>{fmtMoney(d.amount)}</td>
                  <td>
                    <div className="pill-row">
                      {d.poc ? <span className="badge badge-purple">POC</span> : null}
                      {d.se_needed ? <span className="badge badge-amber">SE Needed</span> : null}
                    </div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6}>
                  <div className="empty-state">No deals match these filters</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
