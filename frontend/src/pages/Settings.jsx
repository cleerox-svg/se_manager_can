import { useEffect, useState } from 'react';
import { getReps, getSettings, syncSheets, syncSlack, updateRep } from '../api.js';
import { toast } from '../toast.js';

function configBadge(configured) {
  return configured ? (
    <span className="badge badge-green">Configured</span>
  ) : (
    <span className="badge badge-red">Not configured</span>
  );
}

const PRODUCT_OPTIONS = ['Okta', 'Auth0'];
const SEGMENT_OPTIONS = ['Enterprise/Strategic', 'Commercial', 'Emerging'];
const COVERAGE_ROLE_OPTIONS = ['TMR', 'Secondary'];

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [reps, setReps] = useState([]);

  function refetch() {
    return getSettings().then(setSettings);
  }

  function refetchReps() {
    return getReps().then(setReps);
  }

  useEffect(() => {
    refetch();
    refetchReps();
  }, []);

  async function updateRepCoverage(rep, field, value) {
    try {
      await updateRep(rep.id, { [field]: value || null });
      toast('Saved', 'success');
      refetchReps();
    } catch (err) {
      toast('Failed to save', 'error');
    }
  }

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
          <div className="card-title">Coverage Rules</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '.84rem', marginBottom: '10px' }}>
            Assign Product, Segment, Coverage Role, and Region per rep. Region is
            free text and mainly meaningful for Enterprise/Strategic reps.
          </p>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Product</th>
                <th>Segment</th>
                <th>Coverage Role</th>
                <th>Region</th>
              </tr>
            </thead>
            <tbody>
              {reps.map((rep) => (
                <tr key={rep.id}>
                  <td>{rep.name}</td>
                  <td>
                    <select
                      value={rep.product || ''}
                      onChange={(e) => updateRepCoverage(rep, 'product', e.target.value)}
                    >
                      <option value="">—</option>
                      {PRODUCT_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      value={rep.segment || ''}
                      onChange={(e) => updateRepCoverage(rep, 'segment', e.target.value)}
                    >
                      <option value="">—</option>
                      {SEGMENT_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      value={rep.coverage_role || ''}
                      onChange={(e) => updateRepCoverage(rep, 'coverage_role', e.target.value)}
                    >
                      <option value="">—</option>
                      {COVERAGE_ROLE_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="text"
                      defaultValue={rep.region || ''}
                      onBlur={(e) => updateRepCoverage(rep, 'region', e.target.value)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
