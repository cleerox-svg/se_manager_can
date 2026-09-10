import { useEffect, useState } from 'react';
import { getSettings, syncSheets, syncSlack } from '../api.js';
import { toast } from '../toast.js';

function configBadge(configured) {
  return configured ? (
    <span className="badge badge-green">Configured</span>
  ) : (
    <span className="badge badge-red">Not configured</span>
  );
}

export default function Settings() {
  const [settings, setSettings] = useState(null);

  function refetch() {
    return getSettings().then(setSettings);
  }

  useEffect(() => {
    refetch();
  }, []);

  async function handleSyncSheets() {
    toast('Syncing deals from Google Sheets...');
    const res = await syncSheets();
    if (res.error) {
      toast(res.error, 'error');
      return;
    }
    toast(`Synced ${res.synced} deals`, 'success');
    refetch();
  }

  async function handleSyncSlack() {
    toast('Syncing Slack activity...');
    const res = await syncSlack();
    if (res.error) {
      toast(res.error, 'error');
      return;
    }
    toast('Slack sync complete', 'success');
    refetch();
  }

  if (!settings) {
    return (
      <>
        <div className="section-header">
          <h2>Settings</h2>
        </div>
        <div id="settings-content">
          <div className="empty-state">Loading...</div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="section-header">
        <h2>Settings</h2>
      </div>
      <div id="settings-content">
        <div className="card">
          <div className="card-title">Google Sheets — Team Tracking Sheet</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '.84rem', marginBottom: '10px' }}>
            {configBadge(settings.google_sheets_configured)} — see SETUP.md for the
            service-account setup steps.
          </p>
          <p style={{ fontSize: '.78rem', color: 'var(--text-muted)', marginBottom: '10px' }}>
            Last synced: {settings.deals_last_synced_at || 'never'}
          </p>
          <button className="btn btn-primary" onClick={handleSyncSheets}>
            Sync deals now
          </button>
        </div>

        <div className="card">
          <div className="card-title">Slack</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '.84rem', marginBottom: '10px' }}>
            {configBadge(settings.slack_configured)} — requires a Slack user token
            (search.messages doesn't work with a bot token). See SETUP.md.
          </p>
          <button className="btn btn-primary" onClick={handleSyncSlack}>
            Sync Slack activity now
          </button>
        </div>

        <div className="card">
          <div className="card-title">Review drafting (LiteLLM)</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '.84rem' }}>
            {configBadge(settings.litellm_configured)}
          </p>
        </div>

        <div className="card">
          <div className="card-title">Gong</div>
          <p style={{ color: 'var(--text-muted)', fontSize: '.84rem' }}>
            Coming soon — you're wiring this one up yourself.
          </p>
        </div>
      </div>
    </>
  );
}
