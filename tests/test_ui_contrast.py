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
_SEMANTIC = ("--green", "--amber", "--red", "--purple", "--teal", "--blue")
_INK = ("--text-primary", "--text-secondary", "--text-muted", "--text-accent")

# Light mode had every one of these set to #FFFFFF, which is not merely flat:
# hover feedback became invisible (hover colour == base colour) and the
# progress-bar track vanished, so a rep at 0% rendered as empty space.
_DISTINCT_SURFACES = ("--bg-app", "--bg-card", "--bg-card-hover", "--bg-tag")

# Grounds a focused input can sit on. The focus border replaces the UA outline,
# so it is the indicator and has to clear 3:1 against whatever is either side of
# it: the input's own fill inside, the surface the input sits on outside.
_FOCUS_GROUNDS = ("--bg-input", "--bg-card", "--bg-app", "--bg-nav", "--bg-modal")

# Tokens whose correct value depends on the ground the theme paints, so an
# identical value in both blocks means somebody copied instead of stepping.
# `--border-focus` is here because that is precisely how it stayed wrong: it was
# declared in :root AND body.light-mode, satisfying the declared-twice test,
# with #00A4E0 in both — 2.84:1 on a white input.
_MUST_DIFFER = _SEMANTIC + _INK + ("--border-focus",)

# The filled-button ground, which unlike the rest of the brand blue carries
# text (#fff, in both themes).
_BUTTON_GROUNDS = ("--btn-primary-bg", "--btn-primary-bg-hover")
_BUTTON_INK = "#FFFFFF"

_AA = 4.5  # WCAG 2.1 AA, normal-size text
_NON_TEXT = 3.0  # WCAG 2.2 SC 1.4.11, non-text contrast (focus indicators)


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


def _rule(selector):
    """The declaration body of the first rule whose selector list matches."""
    css = _CSS.read_text()
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    return match.group(1) if match else None


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


@pytest.mark.parametrize("token", _MUST_DIFFER)
def test_ground_sensitive_tokens_are_actually_re_stepped_not_just_re_declared(token):
    """Declaring a token twice is the mechanism, not the point — the point is
    that the two values are stepped for two different grounds.

    `--border-focus` is why this test exists. It was declared in both blocks,
    so the test above passed, but both declarations read #00A4E0: a hue stepped
    for navy, sitting on a white input at 2.84:1. Presence was checked;
    sameness was not. Every token listed here is one whose right value depends
    on the ground beneath it, so two identical values mean a copy rather than a
    step. If a token ever legitimately wants one value in both themes, it does
    not belong on this list — take it off deliberately rather than loosening
    the assertion.
    """
    dark, light = _token(DARK, token), _token(LIGHT, token)
    assert dark and light, f"{token} must be declared in both blocks"
    assert dark.lower() != light.lower(), (
        f"{token} is {dark} in both :root and body.light-mode. It is declared "
        "twice but stepped once, which reads as compliant while one theme runs "
        "on the other theme's ground."
    )


def test_brand_chrome_blue_is_never_used_as_text_ink():
    """`--okta-blue` / `--okta-blue-lt` are brand *chrome* — the filled-button
    ground, the active tab's underline, the scrollbar thumb. They are single
    values shared by both themes, so the moment one is used as `color:` it
    becomes ink that light mode never stepped: `--okta-blue-lt` measures
    2.84:1 on a white card, which is how every link, the blue badge and the
    active sidebar/tab labels failed AA in light mode. Blue ink is `--blue`,
    which is declared per theme like every other status hue.
    """
    css = _CSS.read_text()
    ink = re.findall(r"(?<![-\w])color:\s*var\(\s*(--okta-blue[\w-]*)\s*\)", css)
    assert not ink, (
        f"brand chrome token(s) used as text colour: {sorted(set(ink))}. "
        "Use --blue (declared in both :root and body.light-mode) for blue ink; "
        "--okta-blue* stay for grounds, borders and bars."
    )


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("token", _BUTTON_GROUNDS)
def test_primary_button_ground_carries_white_text_at_aa(theme, token):
    """`.btn-primary` is white text on brand blue at .82rem/600 — normal-size
    text, so the bar is 4.5:1, not the 3:1 large-text one.

    Resting sat on `--okta-blue` (#007DC1) at 4.46:1, just under. The hover
    step was worse and worse in the wrong direction: `--okta-blue-lt`
    (#00A4E0) measured 2.84:1, so the button became harder to read exactly
    while the pointer was on it. Both grounds now darken instead.
    """
    block, base = THEMES[theme]
    bg = _resolve(token, block, base)
    assert bg, f"{token} is not defined for the {theme} theme"
    ratio = _contrast(_BUTTON_INK, bg)
    assert ratio >= _AA, (
        f"{token} ({bg}) under white button text in {theme} mode is {ratio:.2f}:1, "
        f"below AA ({_AA}:1). Darken the ground — never lighten it under white ink."
    )


@pytest.mark.parametrize("theme", THEMES)
def test_primary_button_hover_and_active_darken_rather_than_lighten(theme):
    """A hover that lightens a white-on-blue button reduces its contrast. The
    direction of travel is the rule; the ratio test above is the floor."""
    block, base = THEMES[theme]
    rest = _luminance(_resolve("--btn-primary-bg", block, base))
    hover = _luminance(_resolve("--btn-primary-bg-hover", block, base))
    assert hover < rest, (
        f"--btn-primary-bg-hover is lighter than --btn-primary-bg in {theme} mode "
        "(white ink loses contrast on hover, which is how #00A4E0 got to 2.84:1)."
    )


def test_primary_button_uses_its_own_ground_not_shared_brand_chrome():
    """The button ground is a separate token because it is the only brand-blue
    surface carrying text. Pointing it back at `--okta-blue*` re-couples it to
    the tab underline, the ARR bar and the scrollbar thumb — none of which can
    be darkened for the button's sake, and all of which would be dragged along
    if it were.

    `:active` is checked here too: it must name a ground, because a keyboard
    press fires `:active` without `:hover`, so an unset background made the
    pressed colour depend on whether a mouse was involved.
    """
    for selector in (".btn-primary", ".btn-primary:hover", ".btn-primary:active"):
        body = _rule(selector)
        assert body, f"{selector} rule not found in style.css"
        assert "--okta-blue" not in body, (
            f"{selector} points at brand chrome. Use --btn-primary-bg / "
            "--btn-primary-bg-hover, which are stepped for white text."
        )
        assert "--btn-primary-bg" in body, (
            f"{selector} sets no primary-button ground, so its background falls "
            "through to whatever state happens to also apply."
        )


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("ground", _FOCUS_GROUNDS)
def test_focus_indicator_clears_the_non_text_bar_on_every_ground(theme, ground):
    """The focus rule sets `outline: none`, so `--border-focus` *is* the
    indicator and owes 3:1 against the colours either side of it (WCAG 2.2
    SC 1.4.11). It was #00A4E0 in both themes — 2.84:1 on a white input."""
    block, base = THEMES[theme]
    fg = _resolve("--border-focus", block, base)
    bg = _resolve(ground, block, base)
    assert fg and bg, f"--border-focus/{ground} missing for the {theme} theme"
    ratio = _contrast(fg, bg)
    assert ratio >= _NON_TEXT, (
        f"--border-focus ({fg}) on {ground} ({bg}) in {theme} mode is {ratio:.2f}:1, "
        f"below the non-text bar ({_NON_TEXT}:1) that a focus indicator must clear."
    )


@pytest.mark.parametrize("theme", THEMES)
def test_the_focus_ring_is_a_real_indicator_not_a_faint_tint(theme):
    """`--depth-inset-focus` stands in for the outline the focus rule removes,
    so its outer ring has to carry the indicator's contrast rather than hint at
    it. It used to be rgba(0,125,193,.18)/.22 — composited, 1.29:1 on a white
    card and 1.43:1 on a dark one, i.e. decoration. It now paints the focus
    token itself, so it inherits whatever the test above guarantees."""
    block, base = THEMES[theme]
    shadow = _resolve("--depth-inset-focus", block, base)
    assert shadow, f"--depth-inset-focus missing for the {theme} theme"
    assert re.search(r"0\s+0\s+0\s+2px\s+var\(\s*--border-focus\s*\)", shadow), (
        f"the {theme} focus ring is {shadow!r}. Paint it with var(--border-focus) "
        "at 2px; a low-alpha rgba() ring reads as decoration and leaves the 1px "
        "border doing the whole job of the removed outline."
    )


def test_the_focus_rule_still_recolours_the_border_it_replaced_the_outline_with():
    body = _rule("select:focus, input:focus, textarea:focus")
    assert body, "the input focus rule was not found in style.css"
    if "outline: none" in body or "outline:none" in body:
        assert "var(--border-focus)" in body and "var(--depth-inset-focus)" in body, (
            "the focus rule drops the UA outline without painting both the "
            f"border and the ring that replace it: {body.strip()!r}"
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
