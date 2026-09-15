import { useState } from 'react';
import { generatePrereadDraft, getSfdcUpdates } from '../api.js';
import { toast } from '../toast.js';

export default function Actions() {
  const [draft, setDraft] = useState('');
  const [sfdcUpdates, setSfdcUpdates] = useState([]);

  async function handleGenerateDraft() {
    toast('Generating draft...');
    const res = await generatePrereadDraft();
    setDraft(res.draft);
    toast('Draft generated', 'success');
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(draft);
    toast('Copied', 'success');
  }

  async function handleDraftSfdcUpdates() {
    toast('Drafting SFDC updates...');
    const res = await getSfdcUpdates();
    setSfdcUpdates(res.map((d) => ({ ...d, note: d.proposed_note })));
    toast('Drafted', 'success');
  }

  async function handleCopyNote(note) {
    await navigator.clipboard.writeText(note);
    toast('Copied', 'success');
  }

  return (
    <>
      <div className="section-header">
        <h2>Actions</h2>
      </div>

      <div className="card">
        <div className="card-title">Team Prep Message</div>
        <div className="filter-row">
          <button className="btn btn-primary" onClick={handleGenerateDraft}>Generate draft</button>
          <button className="btn" onClick={handleCopy}>Copy to clipboard</button>
        </div>
        <textarea
          placeholder="Click 'Generate draft' to build a Slack-ready message from this week's forecast for the team's Monday call..."
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </div>

      <div className="card">
        <div className="card-title">SFDC Updates</div>
        <div className="filter-row">
          <button className="btn btn-primary" onClick={handleDraftSfdcUpdates}>Draft</button>
        </div>
        {sfdcUpdates.length === 0 ? (
          <p className="muted">Click "Draft" to build a proposed SE Manager note for every open opportunity in the current + next quarter.</p>
        ) : (
          sfdcUpdates.map((d, i) => (
            <div className="sfdc-update-row" key={d.opportunity_url || i}>
              <div className="sfdc-update-header">
                <a href={d.opportunity_url} target="_blank" rel="noreferrer">{d.opportunity_name}</a>
                <button className="btn" onClick={() => handleCopyNote(d.note)}>Copy</button>
              </div>
              <textarea
                value={d.note}
                onChange={(e) => {
                  const next = [...sfdcUpdates];
                  next[i] = { ...next[i], note: e.target.value };
                  setSfdcUpdates(next);
                }}
              />
            </div>
          ))
        )}
      </div>
    </>
  );
}
