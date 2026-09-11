import { useCallback, useEffect, useState } from 'react';
import { getClosedDealsSummary, getReps, getTechForecast } from '../../api.js';
import { toast } from '../../toast.js';
import { enterPresentMode, exitPresentMode } from '../../theme.js';
import LookBack from './LookBack.jsx';
import LookForwardInspect from './LookForwardInspect.jsx';
import MacroView from './MacroView.jsx';
import WrapUpRisk, { WinRateClosedDeals } from './WrapUpRisk.jsx';

export default function TechForecast() {
  const [data, setData] = useState(null);
  const [reps, setReps] = useState([]);
  const [winRateSummary, setWinRateSummary] = useState(null);

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
    getClosedDealsSummary().then((res) => {
      if (active) setWinRateSummary(res);
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

  return (
    <>
      <button className="present-exit-btn" onClick={exitPresentMode}>&#10005; Exit present mode</button>

      <div className="section-header">
        <div>
          <h2>Technical Forecast</h2>
          <div className="sub" style={{ color: 'var(--text-secondary)', fontSize: '.78rem' }}>
            Last synced: {data.last_synced_at ? new Date(data.last_synced_at).toLocaleString() : 'never'} — Presales Technical Win Process
          </div>
        </div>
        <div className="filter-row">
          <button className="btn" onClick={handleSyncNow}>&#128260; Sync now</button>
          <button className="btn btn-primary" onClick={enterPresentMode}>&#128225; Present mode</button>
        </div>
      </div>

      <MacroView deals={data.deals} />

      <WinRateClosedDeals winRateSummary={winRateSummary} />

      <LookBack wins={data.recent_wins} />

      <LookForwardInspect deals={data.deals} reps={reps} onAssigned={refresh} />

      <WrapUpRisk deals={data.deals} reps={reps} onAssigned={refresh} />
    </>
  );
}
