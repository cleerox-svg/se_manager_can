import { Fragment, useEffect, useState } from 'react';
import { getReps, updateRep } from '../api.js';
import ReviewEditor from '../components/ReviewEditor.jsx';

function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function arrGoalBar(total, target) {
  const pct = target ? Math.min(100, Math.round((total / target) * 100)) : 0;
  const met = target ? total >= target : false;
  return (
    <div className="goal-bar-wrap">
      <div className="goal-bar">
        <div className={`goal-bar-fill${met ? ' met' : ''}`} style={{ width: `${pct}%` }} />
        {target ? <div className="goal-bar-tick" /> : null}
      </div>
      <div className="goal-bar-label">
        <span className={`pct${met ? ' met' : ''}`}>{pct}%</span>
      </div>
    </div>
  );
}

function reviewStatusBadge(status) {
  if (status === 'final') return <span className="badge badge-green">Final</span>;
  if (status === 'draft') return <span className="badge badge-blue">Draft</span>;
  return <span className="badge badge-muted">Not started</span>;
}

export default function Team({ onSelectPerson }) {
  const [reps, setReps] = useState([]);
  const [expandedId, setExpandedId] = useState(null);

  function refetch() {
    return getReps().then(setReps);
  }

  useEffect(() => {
    refetch();
  }, []);

  const period = reps[0]?.review_period;

  function toggleReviewRow(id) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  async function toggleRepActive(rep) {
    await updateRep(rep.id, { active: rep.active ? 0 : 1 });
    refetch();
  }

  async function updateRepTarget(rep, value) {
    await updateRep(rep.id, { arr_target: value === '' ? null : Number(value) });
    refetch();
  }

  return (
    <>
      <div id="team-content" className="card">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Title</th>
              <th>Deals</th>
              <th>Tech Forecast ARR</th>
              <th>ARR vs Target ({period})</th>
              <th>Review ({period})</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {reps.map((rep) => (
              <Fragment key={rep.id}>
                <tr
                  className={rep.active ? '' : 'inactive-flag'}
                  onClick={() => onSelectPerson && onSelectPerson(rep.id)}
                >
                  <td className="clickable">{rep.name}</td>
                  <td>{rep.title}</td>
                  <td>{rep.deal_count}</td>
                  <td>{fmtMoney(rep.tech_forecast_arr)}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {arrGoalBar(rep.arr_total, rep.arr_target)}
                    <input
                      type="number"
                      defaultValue={rep.arr_target ?? ''}
                      onBlur={(e) => updateRepTarget(rep, e.target.value)}
                    />
                  </td>
                  <td
                    className="clickable"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleReviewRow(rep.id);
                    }}
                  >
                    {reviewStatusBadge(rep.review_status)}
                  </td>
                  <td>
                    {rep.active ? (
                      <span className="badge badge-green">Active</span>
                    ) : (
                      <span className="badge badge-muted">Inactive / departed</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleRepActive(rep);
                      }}
                    >
                      Mark {rep.active ? 'inactive' : 'active'}
                    </button>
                  </td>
                </tr>
                {expandedId === rep.id ? (
                  <tr>
                    <td colSpan={8}>
                      <ReviewEditor
                        repId={rep.id}
                        period={period}
                        initialContent={rep.review_content}
                        onSaved={refetch}
                      />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
