# UI standards

The design system for the React frontend: what the tokens are, why they're
split the way they are, and the patterns built on top of them.

**This file holds the values. CLAUDE.md holds the rules and points here.** No
hex code should appear in both — the one thing this codebase has learned three
times over (stage strings, the attribution query, model ids) is that a value
written down twice drifts, and drifts silently.

**It is enforced, not just written.** `tests/test_ui_contrast.py` parses
`frontend/src/style.css` and fails if a token drops below AA, if a status hue is
declared for only one theme (or declared twice with the same value), if the
primary button's ground stops carrying white text at AA or lightens on hover, if
the focus indicator drops below the 3:1 non-text bar on any ground it sits on, if
light mode's surfaces collapse together, or if the stage ramp stops reading in
order. Change a colour and the suite tells you; you do not have to remember this
document exists.

---

## The two rules

Both describe failures that are **invisible in whichever theme you happen to
have open**, which is why they're the ones worth stating first.

### 1. Status hues are per-theme, not shared

`--green` / `--amber` / `--red` / `--purple` / `--teal` / `--blue` are declared
**twice** — once in `:root` (dark) and again in `body.light-mode` — with
different values.

They used to be declared once, stepped for the navy ground, and inherited by
light mode. On white, amber measured **2.03:1** while carrying the "No update
this week" flag; green 2.24:1; teal 2.51:1. Nothing errored. The flags were
simply almost invisible to anyone using the light theme.

Adding a status colour means adding it in both blocks. The same applies to
`--text-muted`, which failed in *both* themes before (2.98:1 light, 2.76:1 dark).

**Blue was missed the first time round.** The other five hues were split per
theme; blue had no status token at all, so everything blue kept pointing at the
brand chrome token `--okta-blue-lt` (`#00A4E0`) — a single value shared by both
themes, measuring **2.84:1** on a white card. That was every link in the app,
the `badge-blue` "Tech win (open)" chip, the active sidebar and tab labels, the
Look Back quarter/SE accordion summaries, the Actions page card icons and the
Tech Forecast sparkline. `--blue` now carries blue **ink** and is stepped per
theme like its five siblings; `--okta-blue` / `--okta-blue-lt` stay as brand
*chrome* — the filled-button ground, the tab underline, the ARR bar, the
scrollbar thumb — which is why `test_brand_chrome_blue_is_never_used_as_text_ink`
exists: using either as a `color:` is how the hue escaped the per-theme rule in
the first place.

### 2. Light mode's surfaces must stay distinct

`--bg-app`, `--bg-card`, `--bg-card-hover`, `--bg-input`, `--bg-tag` were all
`#FFFFFF`. That isn't only flat — two components stopped functioning:

- **Hover feedback** — the hover colour equalled the base colour, so nothing
  happened on hover.
- **The progress-bar track** — `--bg-tag` on a white card meant a rep at 0%
  rendered as empty space rather than an empty bar.

---

## Tokens

Measured against `--bg-card` in each theme. Every value below is ≥ AA (4.5:1).

| Token | Dark | | Light | |
|---|---|---|---|---|
| `--green` | `#00C58E` | 7.48:1 | `#067A55` | 5.35:1 |
| `--amber` | `#F5A623` | 8.26:1 | `#9A6000` | 5.19:1 |
| `--red` | `#FF6B6B` | 6.03:1 | `#C92A2A` | 5.46:1 |
| `--purple` | `#9B6BFA` | 4.69:1 | `#6C3FD4` | 6.36:1 |
| `--teal` | `#00B4C8` | 6.67:1 | `#00707E` | 5.80:1 |
| `--blue` | `#00A4E0` | 5.89:1 | `#0A6CA8` | 5.64:1 |
| `--text-primary` | `#E8EEF5` | — | `#142235` | — |
| `--text-secondary` | `#7B9CB5` | 5.79:1 | `#4C6478` | 6.17:1 |
| `--text-muted` | `#7E98B3` | 5.60:1 | `#57697C` | 5.65:1 |
| `--text-accent` | `#00A4E0` | 5.89:1 | `#0A6CA8` | 5.64:1 |

Surfaces:

| Token | Dark | Light |
|---|---|---|
| `--bg-app` | `#07111E` | `#F4F7FA` |
| `--bg-card` | `#0D1E35` | `#FFFFFF` |
| `--bg-card-hover` | `#102343` | `#EDF3F9` |
| `--bg-tag` | `#0F2040` | `#EAF0F6` |

Light mode's page ground is deliberately **not** white: once `--bg-app` is
`#F4F7FA`, a white card lifts off it on its own, the border can get lighter,
and the interface stops looking like a wireframe.

Chip fills come from the matching `--*-dim` token, never a hardcoded `rgba()`.
They were literal rgba values of the *dark* hues, so a badge background stayed
a dark-theme tint on a white card. `--blue-dim` (`rgba(0,164,224,.14)` dark,
`rgba(10,108,168,.12)` light) was the last one left doing that: as
`--okta-blue-dim` it was a single dark-navy tint reused on white behind the blue
badge, the active sidebar item and the Actions card icon.

Brand chrome sits outside this table on purpose. `--okta-blue` (`#007DC1`) and
`--okta-blue-lt` (`#00A4E0`) are grounds and borders — the active tab's
underline, the ARR bar, the sidebar rail, the scrollbar thumb, `--border-active`
— so they're measured against the mark they sit on, not against `--bg-card`, and
they are deliberately one value for both themes. They are not ink: see rule 1.

### The primary button's ground is its own token

| Token | Value | White text on it |
|---|---|---|
| `--btn-primary-bg` | `#0079BB` | 4.72:1 |
| `--btn-primary-bg-hover` | `#006CA8` | 5.66:1 |

One value each, shared by both themes — `.btn-primary` sets `color: #fff` in
dark *and* light, so there is no per-theme ground to step.

`.btn-primary` is the one brand-blue surface that carries text, which makes it a
contrast surface rather than decoration, and the rest of the brand blue was
never measured that way. White on `--okta-blue` was **4.46:1** — under AA, and
the button's label is `.82rem`/600, i.e. normal-size text, so 4.5:1 applies and
not the 3:1 large-text allowance. The hover step was the real fault: white on
`--okta-blue-lt` measured **2.84:1**, so pointing at the button made it *less*
readable than leaving it alone.

It gets a separate token rather than a re-stepped `--okta-blue` because the
other five brand-blue call sites carry no text at all. Darkening the brand token
to satisfy this button would drag the tab underline, the ARR bar, the sidebar
rail, the scrollbar thumb and `--border-active` along with it — five marks
changed to fix one, none of which had a problem. So the ground that carries ink
forks off and is measured against its ink; the chrome stays on the brand value
and is measured against the marks it sits on.

Hover and `:active` both **darken**. Under white ink that is the only safe
direction, and it is what `test_primary_button_hover_and_active_darken_rather_than_lighten`
holds: a lighter hover is not a smaller version of this bug, it *is* this bug.
`:active` names its ground explicitly instead of inheriting hover's, because a
keyboard press fires `:active` without `:hover` — left unset, the pressed colour
depended on whether a mouse was involved.

### The focus indicator

| Token | Dark | | Light | |
|---|---|---|---|---|
| `--border-focus` | `#00A4E0` | 6.76:1 | `#0A6CA8` | 5.64:1 |

Measured against `--bg-input`, the ground on each side of it; the bar is 3:1
(WCAG 2.2 SC 1.4.11, non-text), not 4.5:1. The weakest ground it sits on is
`--bg-tag` in light mode at 4.91:1, so it clears everywhere.

`--border-focus` was `#00A4E0` in **both** blocks — declared twice and stepped
once. That passed the declared-in-both test while measuring **2.84:1** on a
white input, which is the whole failure mode rule 1 describes, hiding behind the
test that was supposed to catch it. See "Adding a colour" below for the check
that now closes it.

The indicator has to be this good because `select:focus, input:focus,
textarea:focus` sets `outline: none` — there is no UA outline behind it to fall
back on. Its companion ring in `--depth-inset-focus` used to be
`rgba(0,125,193,.22)` / `.18`, which composites to **1.43:1** on a dark card and
**1.29:1** on a white one: decoration standing in for an outline, leaving a 1px
border to do the entire job. The ring now paints `var(--border-focus)` opaque at
2px, so it carries the indicator's contrast instead of hinting at it, and the
focused field reads as focused at a glance rather than on inspection.

---

## Charts

### The stage ramp is ordinal, not categorical

Presales stage runs Early Tech → Validate Solution → Final Due Diligence →
Technical Win. That's a **progression**, so it takes one hue stepped
light-to-dark rather than four unrelated colours — the stack then reads in
stage order without consulting the legend.

| | `--stage-1` | `--stage-2` | `--stage-3` | `--stage-4` | `--stage-5` | `--stage-none` |
|---|---|---|---|---|---|---|
| Dark | `#123A5C` | `#1B5A8B` | `#2A86C2` | `#5BB0E0` | `#9BD4F5` | `#3A4A60` |
| Light | `#D3E7F4` | `#9CC9E6` | `#5AA2D3` | `#1E79B5` | `#0B5680` | `#A8B4C0` |

`--stage-none` is **Untagged** — the absence of a recorded stage. It is
deliberately the lowest-contrast fill on the chart: as a saturated grey it was
the heaviest mark on the dashboard while carrying the least meaning.

The previous five-hue set failed an automated palette check on three counts:
amber outside the lightness band, the grey below the chroma floor (it "reads
grey", so it should never have been a series), and three hues under 3:1 against
a white surface.

### Text never wears the series colour

Legend labels go through `legendLabel`, and tooltip rows pair a small swatch
with `--text-primary`. Recharts colours both with the series colour by default,
which is fine for contrasting hues and unreadable for a ramp — the palest step
is a **fill** colour, not a text colour. It made "Early Tech" nearly invisible
on white the moment the ramp landed.

### Marks

Stacked bars carry a 2px `--bg-card` stroke so adjacent segments separate, which
matters more now that neighbouring fills are one hue apart. Sparklines are 2px
with an emphasised endpoint, and render only with two or more points — one point
is a dot, not a trend.

---

## Components

**Tables.** Money columns set `numeric: true` in the column definition, which
applies `.col-num` (right-aligned plus `tabular-nums`). Both are needed: without
the tabular face the digits don't line up even when right-aligned, and two
amounts in a column can't be compared without reading each one.

**Flags carry severity.** An unowned deal is `badge-red`, stale notes
`badge-amber`, a missing strategy note `badge-muted`. They were all the same
amber, so the row that needed raising on Monday looked exactly like the row that
was merely untidy. `staleLabel` reads `notes_last_changed_at` to say "Stale 3
weeks" rather than the undated wording.

`notes_stale` is a SQLite **integer** — guard it with `!!` in JSX, or
`{0 && <span/>}` renders a literal `0` into the cell.

**Empty and absent states.** A chart with no data says what's missing and what
fills it, rather than rendering bare axes that read as a bug. Fields that are
blank until the sheet carries them (`AE:`, Billing State/Province) render
nothing rather than a `-` on every row.

**Page titles appear once.** The topbar names the page; pages don't repeat it in
an `<h1>`. Doing both cost ~60px above the fold on all five pages.

---

## Adding a colour

1. Declare it in **both** `:root` and `body.light-mode`, stepped for each ground
   — two **different** values, not the same one written twice.
2. Add a `--*-dim` companion if a chip uses it.
3. Add it to `_SEMANTIC` in `tests/test_ui_contrast.py`.
4. Run `python3 -m pytest tests/test_ui_contrast.py`.

Step 3 is the one that keeps this document true. A token that isn't in that
list isn't covered, and the standard silently stops applying to it.

Step 1's emphasis is new, and `--border-focus` is why.
`test_status_hues_are_declared_separately_for_each_theme` only asserted a token
was *present* in both blocks; `--border-focus` was present in both, identical in
both, and wrong in one. `_MUST_DIFFER` now carries every token whose correct
value depends on the ground beneath it — the status hues, the ink tokens and
`--border-focus` — and asserts the two declarations actually differ. If a token
ever genuinely wants one value in both themes, take it off that list on purpose;
don't loosen the assertion, or the next copied value reads as compliant too.

Non-text tokens (focus indicators, and any other mark the user has to *see*
rather than *read*) are held to 3:1, not 4.5:1 — `_NON_TEXT` in the same file.
A ground that carries text is held to the text bar even when it looks like
chrome: `--btn-primary-bg` is the worked example above.

## Re-measuring

The suite checks the thresholds. To see the actual ratios — after a change, or
to fill in this table again:

```bash
python3 -m pytest tests/test_ui_contrast.py -q          # pass/fail
python3 -m pytest tests/test_ui_contrast.py -v          # per-token
```

A failure prints the measured ratio, the two colours, and the theme, so the
message is usually enough on its own.
