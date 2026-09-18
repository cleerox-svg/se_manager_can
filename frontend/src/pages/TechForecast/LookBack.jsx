import { useMemo, useState } from 'react';
import { Trophy, X } from 'lucide-react';

import { agoLabel, selectCelebrationWins } from './winCelebration.js';

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
        {w.source === 'open' && w.opportunity_owner && (
          <div style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>
            AE: {w.opportunity_owner}
          </div>
        )}
      </td>
      <td>{w.win_date || '-'}</td>
      <td>{fmtMoney(w.amount)}</td>
      <td>
        <span className={`badge ${w.sales_stage === '10 - Closed/Won' ? 'badge-green' : 'badge-blue'}`}>
          {w.sales_stage === '10 - Closed/Won' ? 'Closed win' : 'Tech win (open)'}
        </span>
      </td>
      <td>
        <div className="pill-row">
          {/* `!!` because notes_stale is a SQLite integer — a bare 0 renders as
              a literal "0" in the cell (UI_STANDARDS.md, Components). */}
          {w.source === 'open' && !!w.notes_stale && (
            <span className="badge badge-amber">No new notes</span>
          )}
        </div>
      </td>
    </tr>
  );
}

// Per-device, and keyed by the qualifying set (see winCelebration.js): a
// refresh keeps the banner dismissed, a new win brings it back.
const DISMISS_KEY = 'seHub.lookBack.celebrationDismissed';

function readDismissed() {
  // localStorage throws outright in some privacy modes — a banner is not worth
  // taking the page down for.
  try {
    return window.localStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

function storeDismissed(signature) {
  try {
    window.localStorage.setItem(DISMISS_KEY, signature);
  } catch {
    /* no persistence available; the dismissal still holds for this render */
  }
}

/** One further win: status dot, opportunity, SE, amount. Never wraps. */
function CelebrationRow({ w }) {
  const won = w.win_status === 'closed_won';
  return (
    <li className="win-celebrate-row">
      <span className={`win-celebrate-dot ${won ? 'is-won' : 'is-tech'}`} aria-hidden="true" />
      <span className="win-celebrate-row-opp">{oppLink(w.opportunity_name, w.opportunity_url)}</span>
      <span className="win-celebrate-row-se">{w.se_name}</span>
      <span className="win-celebrate-row-amount">{fmtMoney(won ? w.revenue_amount : w.amount)}</span>
    </li>
  );
}

/**
 * Celebration banner for wins in the last CELEBRATION_WINDOW_DAYS days.
 * Renders nothing at all when nothing qualifies, so the card is unchanged.
 */
function WinCelebration({ wins }) {
  const celebration = useMemo(() => selectCelebrationWins(wins), [wins]);
  const [dismissed, setDismissed] = useState(readDismissed);

  if (!celebration || dismissed === celebration.signature) return null;

  const {
    hero, others, moreCount, restCount, windowDays,
    restClosedWonCount, restTechnicalCount,
    closedWonCount, technicalCount, closedWonAmount, technicalAmount,
  } = celebration;
  const heroWon = hero.win_status === 'closed_won';
  const heroAgo = agoLabel(hero.win_date);

  const restParts = [];
  if (restClosedWonCount) restParts.push(`${restClosedWonCount} closed won`);
  if (restTechnicalCount) restParts.push(`${restTechnicalCount} technical`);

  const dismiss = () => {
    storeDismissed(celebration.signature);
    setDismissed(celebration.signature);
  };

  return (
    <section className={`win-celebrate ${heroWon ? 'is-won' : 'is-tech'}`} aria-label="Recent wins">
      <button
        type="button"
        className="win-celebrate-dismiss"
        aria-label="Dismiss recent wins banner"
        onClick={dismiss}
      >
        <X size={14} strokeWidth={2} aria-hidden="true" />
      </button>

      <div className="win-celebrate-hero">
        <div className="win-celebrate-eyebrow">
          <Trophy size={13} strokeWidth={2} aria-hidden="true" />
          {heroWon ? 'Closed won' : 'Technical win'}
          {heroAgo && ` · ${heroAgo}`}
        </div>
        <div className="win-celebrate-figure">{fmtMoney(heroWon ? hero.revenue_amount : hero.amount)}</div>
        <div className="win-celebrate-opp">{oppLink(hero.opportunity_name, hero.opportunity_url)}</div>
        <div className="win-celebrate-se">{hero.se_name}</div>
      </div>

      {others.length > 0 && (
        <>
          <div className="win-celebrate-more-label">
            Plus {restCount} more in the last {windowDays} days
            {restParts.length > 0 && ` · ${restParts.join(', ')}`}
          </div>
          <ul className="win-celebrate-list">
            {others.map((w, i) => (
              <CelebrationRow key={w.opportunity_id || `celebrate-${i}`} w={w} />
            ))}
            {moreCount > 0 && (
              <li className="win-celebrate-overflow">
                +{moreCount} more win{moreCount === 1 ? '' : 's'}
              </li>
            )}
          </ul>
        </>
      )}

      {/* Two cohorts, never one blended figure: revenue_amount is 0 off a
          Closed/Won row, so adding them would present forecast dollars as
          booked revenue. */}
      <div className="win-celebrate-totals">
        {closedWonCount > 0 && (
          <span className="badge badge-green">
            {closedWonCount} closed won · {fmtMoney(closedWonAmount)}
          </span>
        )}
        {technicalCount > 0 && (
          <span className="badge badge-blue">
            {technicalCount} technical win{technicalCount === 1 ? '' : 's'} · {fmtMoney(technicalAmount)}
          </span>
        )}
      </div>
    </section>
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
      <WinCelebration wins={wins} />
      {quarterGroups.map((qg, qi) => {
        const qTotal = qg.items.reduce((s, w) => s + (w.amount || 0), 0);
        const seGroups = groupBy(qg.items, (w) => w.se_name);
        return (
          <details key={qg.key} className={`flyout wins-quarter${qi === 0 ? ' is-first' : ''}`}>
            <summary>
              {qg.key} · {qg.items.length} win{qg.items.length === 1 ? '' : 's'} · {fmtMoney(qTotal)}
            </summary>
            {seGroups.map((sg) => {
              const seTotal = sg.items.reduce((s, w) => s + (w.amount || 0), 0);
              const noSe = sg.items[0].no_se;
              return (
                <details key={sg.key} className="flyout wins-se">
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
