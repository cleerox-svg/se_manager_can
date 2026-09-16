# UI standards

The design system for the React frontend: what the tokens are, why they're
split the way they are, and the patterns built on top of them.

**This file holds the values. CLAUDE.md holds the rules and points here.** No
hex code should appear in both — the one thing this codebase has learned three
times over (stage strings, the attribution query, model ids) is that a value
written down twice drifts, and drifts silently.

**It is enforced, not just written.** `tests/test_ui_contrast.py` parses
`frontend/src/style.css` and fails if a token drops below AA, if a status hue
is declared for only one theme, if light mode's surfaces collapse together, or
if the stage ramp stops reading in order. Change a colour and the suite tells
you; you do not have to remember this document exists.

---

## The two rules

Both describe failures that are **invisible in whichever theme you happen to
have open**, which is why they're the ones worth stating first.

### 1. Status hues are per-theme, not shared

`--green` / `--amber` / `--red` / `--purple` / `--teal` are declared **twice** —
once in `:root` (dark) and again in `body.light-mode` — with different values.

They used to be declared once, stepped for the navy ground, and inherited by
light mode. On white, amber measured **2.03:1** while carrying the "No update
this week" flag; green 2.24:1; teal 2.51:1. Nothing errored. The flags were
simply almost invisible to anyone using the light theme.

Adding a status colour means adding it in both blocks. The same applies to
`--text-muted`, which failed in *both* themes before (2.98:1 light, 2.76:1 dark).

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
a dark-theme tint on a white card.

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

1. Declare it in **both** `:root` and `body.light-mode`, stepped for each ground.
2. Add a `--*-dim` companion if a chip uses it.
3. Add it to `_SEMANTIC` in `tests/test_ui_contrast.py`.
4. Run `python3 -m pytest tests/test_ui_contrast.py`.

Step 3 is the one that keeps this document true. A token that isn't in that
list isn't covered, and the standard silently stops applying to it.

## Re-measuring

The suite checks the thresholds. To see the actual ratios — after a change, or
to fill in this table again:

```bash
python3 -m pytest tests/test_ui_contrast.py -q          # pass/fail
python3 -m pytest tests/test_ui_contrast.py -v          # per-token
```

A failure prints the measured ratio, the two colours, and the theme, so the
message is usually enough on its own.
