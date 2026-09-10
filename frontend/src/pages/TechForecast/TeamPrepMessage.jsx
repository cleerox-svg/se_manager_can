import { useState } from 'react';
import { generatePrereadDraft } from '../../api.js';
import { toast } from '../../toast.js';

export default function TeamPrepMessage() {
  const [draft, setDraft] = useState('');

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

  return (
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
  );
}
