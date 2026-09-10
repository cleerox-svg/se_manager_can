function fmtMoney(n) {
  if (n == null) return '-';
  return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
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

function groupBy(arr, keyFn) {
  const groups = [];
  let current = null;
  for (const item of arr) {
    const key = keyFn(item);
    if (!current || current.key !== key) {
      current = { key, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }
  return groups;
}

function RecentWinRow({ w }) {
  return (
    <tr>
      <td>
        {oppLink(w.opportunity_name, w.opportunity_url)}
        {w.source === 'open' && (
          <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>
            AE: {w.opportunity_owner || '-'}
          </div>
        )}
      </td>
      <td>{w.win_date || '-'}</td>
      <td>{fmtMoney(w.amount)}</td>
      <td>
        <span className={`badge ${w.source === 'closed' ? 'badge-green' : 'badge-blue'}`}>
          {w.source === 'closed' ? 'Closed win' : 'Tech win (open)'}
        </span>
      </td>
      <td>
        <div className="pill-row">
          {w.source === 'open' && w.notes_stale && (
            <span className="badge badge-amber">No new notes</span>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function LookBack({ wins }) {
  if (!wins.length) {
    return (
      <div className="card">
        <div className="card-title">Look Back — Recent Technical Wins</div>
        <div className="empty-state">No recent wins on file</div>
      </div>
    );
  }

  const quarterGroups = groupBy(wins, (w) => w.fiscal_quarter || 'Unknown');

  return (
    <div className="card">
      <div className="card-title">Look Back — Recent Technical Wins</div>
      {quarterGroups.map((qg, qi) => {
        const qTotal = qg.items.reduce((s, w) => s + (w.amount || 0), 0);
        const seGroups = groupBy(qg.items, (w) => w.se_name);
        return (
          <details key={qg.key} className={`flyout wins-quarter${qi === 0 ? ' is-first' : ''}`} open>
            <summary>
              {qg.key} · {qg.items.length} win{qg.items.length === 1 ? '' : 's'} · {fmtMoney(qTotal)}
            </summary>
            {seGroups.map((sg) => {
              const seTotal = sg.items.reduce((s, w) => s + (w.amount || 0), 0);
              const noSe = sg.items[0].no_se;
              return (
                <details key={sg.key} className="flyout wins-se" open>
                  <summary>
                    {sg.key} · {sg.items.length} win{sg.items.length === 1 ? '' : 's'} · {fmtMoney(seTotal)}{' '}
                    {noSe && <span className="badge badge-amber">No SE</span>}
                  </summary>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Opportunity</th>
                          <th>Win date</th>
                          <th>Amount</th>
                          <th>Status</th>
                          <th>Flags</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sg.items.map((w, i) => (
                          <RecentWinRow key={w.opportunity_id || `${sg.key}-${i}`} w={w} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              );
            })}
          </details>
        );
      })}
    </div>
  );
}
