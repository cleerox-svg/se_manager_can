"""The UI standard, enforced.

UI_STANDARDS.md documents the palette; this file is what stops it drifting.
Everything here is derived by parsing `frontend/src/style.css`, so a token
edited in the stylesheet is checked on the next test run rather than the next
time somebody happens to look at the light theme.

The rule these tests exist for: the status hues used to be declared once, in
`:root`, stepped for the navy ground, and inherited unchanged by light mode —
where amber measured 2.03:1 against white while carrying the "No update this
week" flag. The failure is invisible in whichever theme you are looking at,
which is exactly the kind a test should own.
"""
import re
from pathlib import Path

import pytest

_CSS = Path(__file__).resolve().parent.parent / "frontend" / "src" / "style.css"

# Foreground tokens that must stay legible against the card surface in BOTH
# themes. Each must be declared in both blocks — see the declared-twice test.
_SEMANTIC = ("--green", "--amber", "--red", "--purple", "--teal")
_INK = ("--text-primary", "--text-secondary", "--text-muted", "--text-accent")

# Light mode had every one of these set to #FFFFFF, which is not merely flat:
# hover feedback became invisible (hover colour == base colour) and the
# progress-bar track vanished, so a rep at 0% rendered as empty space.
_DISTINCT_SURFACES = ("--bg-app", "--bg-card", "--bg-card-hover", "--bg-tag")

_AA = 4.5  # WCAG 2.1 AA, normal-size text


def _blocks():
    css = _CSS.read_text()
    start = css.index(":root {")
    split = css.index("body.light-mode {")
    return css[start:split], css[split:]


def _token(block, name):
    match = re.search(rf"{re.escape(name)}:\s*([^;]+);", block)
    return match.group(1).strip() if match else None


def _resolve(name, block, base):
    """A light-mode value when overridden, else the :root value it inherits."""
    return _token(block, name) or _token(base, name)


def _luminance(hex_colour):
    hex_colour = hex_colour.lstrip("#")
    channels = (int(hex_colour[i:i + 2], 16) / 255 for i in (0, 2, 4))
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg, bg):
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


DARK, LIGHT = _blocks()
THEMES = {"dark": (DARK, DARK), "light": (LIGHT, DARK)}


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("token", _SEMANTIC + _INK)
def test_foreground_tokens_clear_aa_against_the_card_surface(theme, token):
    block, base = THEMES[theme]
    fg = _resolve(token, block, base)
    bg = _resolve("--bg-card", block, base)
    assert fg, f"{token} is not defined for the {theme} theme"
    ratio = _contrast(fg, bg)
    assert ratio >= _AA, (
        f"{token} ({fg}) on {bg} in {theme} mode is {ratio:.2f}:1, below AA ({_AA}:1). "
        "Re-step the hue for this ground rather than sharing one value across themes."
    )


@pytest.mark.parametrize("token", _SEMANTIC)
def test_status_hues_are_declared_separately_for_each_theme(token):
    """The core rule. A status colour present only in :root silently inherits
    into light mode on a ground it was never stepped for."""
    assert _token(DARK, token), f"{token} missing from :root"
    assert _token(LIGHT, token), (
        f"{token} is declared in :root but not in body.light-mode, so light mode "
        "inherits a hue stepped for the navy ground. Declare it in both."
    )


def test_light_mode_surfaces_stay_distinguishable():
    values = {t: _resolve(t, LIGHT, DARK) for t in _DISTINCT_SURFACES}
    assert len(set(values.values())) == len(values), (
        f"light-mode surfaces collapsed onto the same colour: {values}. "
        "Hover feedback and the progress-bar track both stop rendering."
    )


@pytest.mark.parametrize("theme", THEMES)
def test_the_stage_ramp_is_monotonic_in_lightness(theme):
    """Presales stage is ordinal, so the ramp has to read in order. A step out
    of sequence makes a later stage look earlier than an earlier one."""
    block, base = THEMES[theme]
    steps = [_resolve(f"--stage-{i}", block, base) for i in range(1, 6)]
    assert all(steps), f"stage ramp incomplete for {theme}: {steps}"
    lums = [_luminance(s) for s in steps]
    ordered = lums == sorted(lums) or lums == sorted(lums, reverse=True)
    assert ordered, f"stage ramp not monotonic in {theme} mode: {list(zip(steps, lums))}"


@pytest.mark.parametrize("theme", THEMES)
def test_untagged_recedes_behind_every_real_stage(theme):
    """'Untagged' means no stage recorded. As a saturated grey it was the
    heaviest mark on the dashboard while carrying the least meaning."""
    block, base = THEMES[theme]
    bg = _resolve("--bg-card", block, base)
    none_ratio = _contrast(_resolve("--stage-none", block, base), bg)
    strongest = max(
        _contrast(_resolve(f"--stage-{i}", block, base), bg) for i in range(1, 6)
    )
    assert none_ratio < strongest, (
        f"--stage-none ({none_ratio:.2f}:1) is as prominent as the strongest real "
        f"stage ({strongest:.2f}:1) in {theme} mode"
    )
