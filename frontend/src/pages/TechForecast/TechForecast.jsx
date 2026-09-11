import { useCallback, useEffect, useState } from 'react';
import { getReps, getTechForecast } from '../../api.js';
import { toast } from '../../toast.js';
import LookBack from './LookBack.jsx';
import LookForwardInspect from './LookForwardInspect.jsx';
import MacroView from './MacroView.jsx';
import TeamPrepMessage from './TeamPrepMessage.jsx';

export default function TechForecast() {
  const [data, setData] = useState(null);
  const [reps, setReps] = useState([]);

  const refresh = useCallback(() => {
    return getTechForecast().then((res) => setData(res));
  }, []);

  useEffect(() => {
    let active = true;
    getTechForecast().then((res) => {
      if (active) setData(res);
    });
    getReps().then((res) => {
      if (active) setReps(res);
    });
    return () => {
      active = false;
    };
  }, []);

  if (!data) {
    return (
      <>
        <div className="section-header">
          <h2>Technical Forecast</h2>
        </div>
        <div className="empty-state">Loading...</div>
      </>
    );
  }

  async function handleSyncNow() {
    await navigator.clipboard.writeText('Sync the tech forecast sheet.');
    toast('Copied — paste into a Claude Code chat to pull the latest sheet data', 'success');
  }

  function handlePresentMode() {
    document.body.classList.add('present-mode');
  }

  return (
    <>
      <div className="section-header">
        <div>
          <h2>Technical Forecast</h2>
          <div className="sub" style={{ color: 'var(--text-secondary)', fontSize: '.78rem' }}>
            Last synced: {data.last_synced_at ? new Date(data.last_synced_at).toLocaleString() : 'never'} — Presales Technical Win Process
          </div>
        </div>
        <div className="filter-row">
          <button className="btn" onClick={handleSyncNow}>&#128260; Sync now</button>
          <button className="btn btn-primary" onClick={handlePresentMode}>&#128225; Present mode</button>
        </div>
      </div>

      <TeamPrepMessage />

      <MacroView deals={data.deals} />

      <div className="card">
        <div className="card-title">Win Rate — Closed Deals</div>
        <div className="empty-state">Coming soon</div>
      </div>

      <LookBack wins={data.recent_wins} />

      <LookForwardInspect deals={data.deals} reps={reps} onAssigned={refresh} />

      <div className="card">
        <div className="card-title">Wrap-Up &amp; Risk</div>
        <div className="empty-state">Coming soon</div>
      </div>
    </>
  );
}
