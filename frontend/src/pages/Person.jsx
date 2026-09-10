import { useEffect, useState } from 'react';
import { getReps, getRepDeals, getRepSlack, getReview } from '../api.js';
import ReviewEditor from '../components/ReviewEditor.jsx';

function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function stageBadge(stage) {
  const map = { 'Closed Won': 'badge-green', 'Closed Lost': 'badge-red' };
  const cls = map[stage] || 'badge-blue';
  return <span className={`badge ${cls}`}>{stage || '-'}</span>;
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

function arrGoalBar(total, target) {
  const pct = target ? Math.min(100, Math.round((total / target) * 100)) : 0;
  const met = target ? total >= target : false;
  return (
    <div className={`goal-bar ${met ? 'goal-bar-met' : ''}`}>
      <div className="goal-bar-track">
        <div className="goal-bar-fill" style={{ width: `${pct}%` }} />
        {target ? <div className="goal-bar-tick" /> : null}
      </div>
      <div className="goal-bar-label">{pct}%</div>
    </div>
  );
}

function reviewStatusBadge(status) {
  if (status === 'final') return <span className="badge badge-green">Final</span>;
  if (status === 'draft') return <span className="badge badge-blue">Draft</span>;
  return <span className="badge badge-muted">Not started</span>;
}

export default function Person({ repId }) {
  const [rep, setRep] = useState(null);
  const [deals, setDeals] = useState([]);
  const [notes, setNotes] = useState([]);
  const [review, setReview] = useState(null);
  const [activeTab, setActiveTab] = useState('deals');

  const period = new Date().getFullYear() + '-H' + (new Date().getMonth() < 6 ? '1' : '2');

  function refetch() {
    return Promise.all([
      getReps().then((reps) => reps.find((r) => r.id === repId)),
      getRepDeals(repId),
      getRepSlack(repId),
      getReview(repId, period),
    ]).then(([r, d, n, rv]) => {
      setRep(r);
      setDeals(d);
      setNotes(n);
      setReview(rv);
    });
  }

  useEffect(() => {
    setActiveTab('deals');
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repId]);

  if (!rep) return null;

  return (
    <>
      <div className="section-header">
        <h2>
          {rep.name} {rep.active ? '' : <span className="badge badge-muted">Inactive / departed</span>}
        </h2>
      </div>
      <div className="tabs">
        <button
          type="button"
          className={`tab-btn ${activeTab === 'deals' ? 'active' : ''}`}
          onClick={() => setActiveTab('deals')}
        >
          Deals ({deals.length})
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === 'slack' ? 'active' : ''}`}
          onClick={() => setActiveTab('slack')}
        >
          Slack activity ({notes.length})
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === 'review' ? 'active' : ''}`}
          onClick={() => setActiveTab('review')}
        >
          Review draft — {period} {reviewStatusBadge(review?.status)}
        </button>
      </div>

      <div className="tab-panel" style={{ display: activeTab === 'deals' ? 'block' : 'none' }}>
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Opportunity</th>
                <th>Stage</th>
                <th>Close date</th>
                <th>Amount</th>
                <th>Mgr notes</th>
              </tr>
            </thead>
            <tbody>
              {deals.length ? (
                deals.map((d) => (
                  <tr key={d.id}>
                    <td>{oppLink(d.opportunity_name, d.opportunity_url)}</td>
                    <td>{stageBadge(d.stage)}</td>
                    <td>{d.close_date || '-'}</td>
                    <td>{fmtMoney(d.amount)}</td>
                    <td>{d.se_manager_notes || '-'}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5}>
                    <div className="empty-state">No deals on file</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="tab-panel" style={{ display: activeTab === 'slack' ? 'block' : 'none' }}>
        {notes.length ? (
          notes.map((n) => (
            <div className="slack-note" key={n.id}>
              <div className="meta">
                #{n.channel_name || n.channel_id} · {n.posted_at || ''}
              </div>
              {n.text || ''}
            </div>
          ))
        ) : (
          <div className="empty-state">No Slack activity synced yet</div>
        )}
      </div>

      <div className="tab-panel" style={{ display: activeTab === 'review' ? 'block' : 'none' }}>
        <div className="card">
          <div className="card-title">ARR — full fiscal year vs target</div>
          {arrGoalBar(rep.arr_total, rep.arr_target)}
        </div>
        <ReviewEditor
          repId={repId}
          period={period}
          initialContent={review?.content}
          onSaved={refetch}
          generateLabel="Generate draft from deals + Slack"
        />
      </div>
    </>
  );
}
