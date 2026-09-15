import { useEffect, useState } from 'react';
import { MessageSquare, FileText, ListChecks, ArrowLeft } from 'lucide-react';
import {
  generatePrereadDraft,
  getSfdcUpdates,
  getTopItemsLatest,
  generateTopItemsScaffold,
  saveTopItems,
} from '../api.js';
import { toast } from '../toast.js';

const TOP_ITEMS_DOC_URL = 'https://docs.google.com/document/d/1IhfDQF2jMTGatVe01r6crQd9MvFEVA8K6gNGV3qEYfI/edit';

const MODULES = [
  {
    key: 'prep-message',
    Icon: MessageSquare,
    title: 'Team Prep Message',
    description: "Build a Slack-ready message from this week's forecast for the team's Monday call.",
  },
  {
    key: 'sfdc-updates',
    Icon: FileText,
    title: 'SFDC Updates',
    description: 'Draft a proposed SE Manager note for every open opportunity in the current + next quarter.',
  },
  {
    key: 'top-items',
    Icon: ListChecks,
    title: 'Top Items',
    description: 'Draft the weekly Top Items summary for hiring, customer meetings, and technical wins.',
  },
];

function ActionCardGrid({ onSelect }) {
  return (
    <div className="action-card-grid">
      {MODULES.map(({ key, Icon, title, description }) => (
        <button key={key} className="action-card" onClick={() => onSelect(key)}>
          <span className="action-card-icon">
            <Icon size={20} strokeWidth={2} />
          </span>
          <span className="action-card-title">{title}</span>
          <span className="action-card-desc">{description}</span>
        </button>
      ))}
    </div>
  );
}

function BackButton({ onBack }) {
  return (
    <button className="btn module-back-btn" onClick={onBack}>
      <ArrowLeft size={14} strokeWidth={2} /> Back
    </button>
  );
}

function PrepMessageModule({ onBack }) {
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
    <>
      <BackButton onBack={onBack} />
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
    </>
  );
}

function SfdcUpdatesModule({ onBack }) {
  const [sfdcUpdates, setSfdcUpdates] = useState([]);

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
      <BackButton onBack={onBack} />
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

function TopItemsModule({ onBack }) {
  const [content, setContent] = useState('');
  const [lastSavedDate, setLastSavedDate] = useState(null);

  useEffect(() => {
    getTopItemsLatest().then((res) => {
      if (res && res.content) {
        setContent(res.content);
        setLastSavedDate(res.entry_date || null);
      }
    });
  }, []);

  async function handleGenerate() {
    toast('Generating scaffold...');
    const res = await generateTopItemsScaffold();
    setContent(res.scaffold);
    toast('Scaffold generated', 'success');
  }

  async function handleSave() {
    const res = await saveTopItems(content);
    setLastSavedDate(res.entry_date || null);
    toast('Saved', 'success');
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(content);
    toast('Copied', 'success');
  }

  return (
    <>
      <BackButton onBack={onBack} />
      <div className="card">
        <div className="card-title">Top Items</div>
        <div className="filter-row">
          <button className="btn btn-primary" onClick={handleGenerate}>Generate</button>
          <button className="btn" onClick={handleSave}>Save</button>
          <button className="btn" onClick={handleCopy}>Copy to clipboard</button>
        </div>
        <textarea
          placeholder="Click 'Generate' to build a starter draft from this week's data..."
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <p className="muted" style={{ marginTop: 10 }}>
          Reference: <a href={TOP_ITEMS_DOC_URL} target="_blank" rel="noreferrer">Top Items Tracking doc</a>
          {lastSavedDate ? ` · Last saved: ${lastSavedDate}` : ''}
        </p>
      </div>
    </>
  );
}

export default function Actions() {
  const [activeModule, setActiveModule] = useState(null);

  return (
    <>
      <div className="section-header">
        <h2>Actions</h2>
      </div>

      {activeModule === null && <ActionCardGrid onSelect={setActiveModule} />}
      {activeModule === 'prep-message' && <PrepMessageModule onBack={() => setActiveModule(null)} />}
      {activeModule === 'sfdc-updates' && <SfdcUpdatesModule onBack={() => setActiveModule(null)} />}
      {activeModule === 'top-items' && <TopItemsModule onBack={() => setActiveModule(null)} />}
    </>
  );
}
