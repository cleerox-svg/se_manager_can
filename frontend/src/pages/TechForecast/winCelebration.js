/**
 * Look Back — which recent wins get celebrated, and how they roll up.
 *
 * Pure selection logic, kept out of the component so it can be exercised
 * directly (tests/test_win_celebration.py runs this module under node).
 * Everything here is derived from the `wins` array the page already holds —
 * there is no extra endpoint behind the banner.
 *
 * Two rules this module exists to hold in one place:
 *
 * - **A loss is never celebrated.** `win_status === 'closed_lost'` is a
 *   technical win on a deal that closed Lost. It stays in the table below,
 *   unchanged, but it never reaches the banner.
 * - **The two money cohorts never merge.** `revenue_amount` is 0 for anything
 *   that isn't Closed/Won, so summing it with `amount` would present forecast
 *   dollars as booked revenue. Closed Won $ comes from `revenue_amount`,
 *   Technical Win $ from `amount`, and they are reported side by side — the
 *   same rule as every dollar query against `closed_deals` filtering on
 *   STAGE_CLOSED_WON (see CLAUDE.md).
 */

/** The celebration window. One line to change to 7. */
export const CELEBRATION_WINDOW_DAYS = 14;

/** How many further wins list under the hero before they collapse to "+N more". */
export const CELEBRATION_LIST_LIMIT = 3;

/** Celebrated cohorts. `closed_lost` is deliberately absent. */
const CELEBRATED_STATUSES = ['closed_won', 'open'];

const MS_PER_DAY = 86400000;

/** ISO `YYYY-MM-DD` -> UTC midnight, or null when the cell isn't a date. */
function parseIsoDay(value) {
  if (typeof value !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!m) return null;
  const stamp = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(stamp) ? null : stamp;
}

/** `today` as UTC midnight, from an ISO string, a Date, or the wall clock. */
function resolveToday(today) {
  if (today == null) {
    const now = new Date();
    return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  }
  if (today instanceof Date) {
    return Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  }
  return parseIsoDay(today);
}

/**
 * Whole days between a win date and today. 0 = today, 1 = yesterday.
 * Negative for a future-dated win (an open deal can carry a forecast Tech Win
 * date), which is not "in the last N days" and so never qualifies.
 */
export function daysSince(winDate, today) {
  const day = parseIsoDay(winDate);
  const now = resolveToday(today);
  if (day == null || now == null) return null;
  return Math.round((now - day) / MS_PER_DAY);
}

/** "Today" / "1 day ago" / "5 days ago" — null when the date won't parse. */
export function agoLabel(winDate, today) {
  const n = daysSince(winDate, today);
  if (n == null || n < 0) return null;
  if (n === 0) return 'Today';
  return `${n} day${n === 1 ? '' : 's'} ago`;
}

/** Stable id for a win row; falls back to name+date when the sheet has no oid. */
function winKey(w) {
  return w.opportunity_id || `${w.opportunity_name || ''}@${w.win_date || ''}`;
}

/** djb2, hex — keeps the localStorage value short however many wins qualify. */
function hash(text) {
  let h = 5381;
  for (let i = 0; i < text.length; i += 1) h = ((h << 5) + h + text.charCodeAt(i)) >>> 0;
  return h.toString(16);
}

/**
 * The dismissal key: the qualifying set itself, plus the window length.
 * A refresh reproduces the same signature (banner stays dismissed); a new win
 * — or a shortened window — produces a different one, so the banner returns.
 */
export function celebrationSignature(qualifying, windowDays = CELEBRATION_WINDOW_DAYS) {
  const ids = qualifying.map(winKey).sort();
  return `w${windowDays}-${hash(ids.join('|'))}`;
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : Number(v) || 0);

/**
 * Wins inside the window, celebrated cohorts only, newest first.
 * Ties break on amount then name so the order is deterministic across renders.
 */
export function qualifyingWins(wins, { today = null, windowDays = CELEBRATION_WINDOW_DAYS } = {}) {
  return (Array.isArray(wins) ? wins : [])
    .filter((w) => {
      if (!w || !CELEBRATED_STATUSES.includes(w.win_status)) return false;
      const age = daysSince(w.win_date, today);
      return age != null && age >= 0 && age < windowDays;
    })
    .sort((a, b) => {
      const byDate = String(b.win_date).localeCompare(String(a.win_date));
      if (byDate) return byDate;
      const byAmount = num(b.amount) - num(a.amount);
      if (byAmount) return byAmount;
      return String(winKey(a)).localeCompare(String(winKey(b)));
    });
}

/**
 * Everything the banner renders, or `null` when nothing qualifies — in which
 * case the card must look exactly as it did before this feature existed.
 */
export function selectCelebrationWins(wins, { today = null, windowDays = CELEBRATION_WINDOW_DAYS } = {}) {
  const qualifying = qualifyingWins(wins, { today, windowDays });
  if (!qualifying.length) return null;

  // Hero = the biggest of them. Newest wins the tie, then the key, so two
  // equal amounts don't swap places between renders.
  const hero = qualifying.reduce((best, w) => {
    const d = num(w.amount) - num(best.amount);
    if (d) return d > 0 ? w : best;
    const byDate = String(w.win_date).localeCompare(String(best.win_date));
    if (byDate) return byDate > 0 ? w : best;
    return String(winKey(w)).localeCompare(String(winKey(best))) < 0 ? w : best;
  }, qualifying[0]);

  const rest = qualifying.filter((w) => w !== hero);
  const closedWon = qualifying.filter((w) => w.win_status === 'closed_won');
  const technical = qualifying.filter((w) => w.win_status === 'open');

  return {
    hero,
    others: rest.slice(0, CELEBRATION_LIST_LIMIT),
    moreCount: Math.max(0, rest.length - CELEBRATION_LIST_LIMIT),
    restCount: rest.length,
    total: qualifying.length,
    closedWonCount: closedWon.length,
    technicalCount: technical.length,
    // The "plus N more" line describes what is NOT the hero, so its breakdown
    // has to add up to restCount rather than to the full qualifying set.
    restClosedWonCount: rest.filter((w) => w.win_status === 'closed_won').length,
    restTechnicalCount: rest.filter((w) => w.win_status === 'open').length,
    // Booked revenue only — `revenue_amount` is 0 off a Closed/Won row.
    closedWonAmount: closedWon.reduce((s, w) => s + num(w.revenue_amount), 0),
    // Forecast/open dollars, reported separately and never added to the above.
    technicalAmount: technical.reduce((s, w) => s + num(w.amount), 0),
    windowDays,
    signature: celebrationSignature(qualifying, windowDays),
  };
}
