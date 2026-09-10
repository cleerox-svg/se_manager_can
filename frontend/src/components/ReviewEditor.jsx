import { useState } from 'react';
import { generateReview, saveReview } from '../api.js';
import { toast } from '../toast.js';

export default function ReviewEditor({ repId, period, initialContent, onSaved }) {
  const [content, setContent] = useState(initialContent || '');
  const [busy, setBusy] = useState(false);

  async function handleGenerate() {
    toast('Generating draft...', 'info');
    setBusy(true);
    const res = await generateReview(repId, period);
    setBusy(false);
    if (res.error) {
      toast(res.error, 'error');
      return;
    }
    setContent(res.content);
  }

  async function handleSave(status) {
    setBusy(true);
    const res = await saveReview(repId, period, content, status);
    setBusy(false);
    if (res.error) {
      toast(res.error, 'error');
      return;
    }
    onSaved && onSaved();
  }

  return (
    <div className="review-inline-row">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={8}
        disabled={busy}
      />
      <div className="pill-row">
        <button type="button" onClick={handleGenerate} disabled={busy}>
          Generate draft
        </button>
        <button type="button" onClick={() => handleSave('draft')} disabled={busy}>
          Save draft
        </button>
        <button type="button" onClick={() => handleSave('final')} disabled={busy}>
          Mark final
        </button>
      </div>
    </div>
  );
}
