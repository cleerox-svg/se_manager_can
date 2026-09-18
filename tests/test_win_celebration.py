"""The Look Back celebration banner's selection logic, enforced.

`frontend/src/pages/TechForecast/winCelebration.js` decides which recent wins
the banner celebrates. Two of its rules are the kind that fail silently in a
browser and would only be noticed by the wrong person reading the wrong number:

* a **closed_lost** row is a technical win on a deal that closed Lost — it
  belongs in the table below, never in a celebration;
* Closed Won $ and Technical Win $ are **two cohorts**, never one sum, because
  `revenue_amount` is 0 off a Closed/Won row and blending them would present
  forecast dollars as booked revenue (same rule as every dollar query against
  `closed_deals` filtering on ``constants.STAGE_CLOSED_WON``).

The module is plain ESM with no React or DOM in it, so it is exercised directly
under node rather than mirrored in Python — a mirror is the duplicated literal
this codebase has been bitten by three times.

All fixture data here is synthetic, as conftest requires, and "today" is always
injected so a test can't pass only during one fortnight.
"""
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend" / "src" / "pages" / "TechForecast" / "winCelebration.js"

TODAY = "2026-09-18"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to run the frontend module"
)


@pytest.fixture(scope="session")
def harness(tmp_path_factory):
    """A tiny ESM entry point: JSON in on argv, the selection result JSON out."""
    path = tmp_path_factory.mktemp("winceleb") / "harness.mjs"
    path.write_text(
        "import { selectCelebrationWins, qualifyingWins } from "
        f"{json.dumps(MODULE.as_uri())};\n"
        "const input = JSON.parse(process.argv[2]);\n"
        # JSON has no `undefined`, so an omitted window has to be dropped from
        # the options object rather than passed through as null — a destructured
        # default only fills in for undefined.
        "const opts = { today: input.today };\n"
        "if (input.windowDays != null) opts.windowDays = input.windowDays;\n"
        "process.stdout.write(JSON.stringify({\n"
        "  selection: selectCelebrationWins(input.wins, opts),\n"
        "  qualifying: qualifyingWins(input.wins, opts).map((w) => w.opportunity_id),\n"
        "}));\n"
    )
    return path


@pytest.fixture(scope="session")
def select(harness):
    def _select(wins, today=TODAY, window_days=None):
        payload = {"wins": wins, "today": today, "windowDays": window_days}
        out = subprocess.run(
            ["node", str(harness), json.dumps(payload)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)

    return _select


def win(oid, *, days_ago, status="closed_won", amount=100_000, se="Sean Miller"):
    """A synthetic row shaped like `app.py`'s `recent_wins` entries.

    `revenue_amount` mirrors the route: the amount on a Closed/Won row, zero on
    anything else. Nothing here is real customer data.
    """
    day = date.fromisoformat(TODAY) - timedelta(days=days_ago)
    return {
        "opportunity_id": oid,
        "opportunity_name": f"Opportunity {oid}",
        "opportunity_url": f"https://example.invalid/{oid}",
        "win_date": day.isoformat(),
        "win_status": status,
        "amount": amount,
        "revenue_amount": amount if status == "closed_won" else 0,
        "se_name": se,
    }


def test_nothing_qualifies_means_no_banner_at_all(select):
    """The card has to look exactly as it did before the feature existed."""
    assert select([])["selection"] is None
    old = [win("A", days_ago=40), win("B", days_ago=99, status="open")]
    assert select(old)["selection"] is None


def test_closed_lost_is_never_celebrated(select):
    """A technical win on a lost deal stays in the table and out of the banner."""
    result = select([
        win("LOST", days_ago=2, status="closed_lost", amount=900_000),
        win("WON", days_ago=3, status="closed_won", amount=50_000),
    ])
    assert result["qualifying"] == ["WON"]
    # And the biggest row in the window did not become the hero by being a loss.
    assert result["selection"]["hero"]["opportunity_id"] == "WON"


def test_a_window_of_only_losses_renders_nothing(select):
    assert select([win("L1", days_ago=1, status="closed_lost")])["selection"] is None


def test_open_technical_wins_are_celebrated_alongside_closed_won(select):
    result = select([
        win("OPEN", days_ago=5, status="open", amount=40_000),
        win("WON", days_ago=6, status="closed_won", amount=30_000),
    ])
    assert sorted(result["qualifying"]) == ["OPEN", "WON"]
    assert result["selection"]["closedWonCount"] == 1
    assert result["selection"]["technicalCount"] == 1


@pytest.mark.parametrize(
    "days_ago,expected",
    [(0, True), (1, True), (13, True), (14, False), (15, False), (-1, False)],
)
def test_the_window_boundary(select, days_ago, expected):
    """14 calendar days ending today: day 0 through 13 are in, day 14 is out.

    A future-dated win (an open deal can carry a forecast Tech Win date) is not
    "in the last 14 days" either.
    """
    result = select([win("A", days_ago=days_ago)])
    assert (result["selection"] is not None) is expected


def test_the_window_length_is_a_single_knob(select):
    """Dropping 14 to 7 is the one-line change the constant exists for."""
    wins = [win("A", days_ago=3), win("B", days_ago=10)]
    assert sorted(select(wins)["qualifying"]) == ["A", "B"]
    assert select(wins, window_days=7)["qualifying"] == ["A"]


def test_the_two_dollar_cohorts_are_computed_separately(select):
    """Closed Won $ comes from revenue_amount, Technical $ from amount, and no
    field in the result adds the two together."""
    result = select([
        win("W1", days_ago=1, status="closed_won", amount=250_000),
        win("W2", days_ago=2, status="closed_won", amount=150_000),
        win("O1", days_ago=3, status="open", amount=900_000),
    ])["selection"]
    assert result["closedWonAmount"] == 400_000
    assert result["technicalAmount"] == 900_000
    blended = 400_000 + 900_000
    assert blended not in [v for v in result.values() if isinstance(v, (int, float))]


def test_open_rows_contribute_nothing_to_booked_revenue(select):
    """revenue_amount is 0 off a Closed/Won row — an open win must not book any."""
    result = select([win("O1", days_ago=1, status="open", amount=500_000)])["selection"]
    assert result["closedWonAmount"] == 0
    assert result["technicalAmount"] == 500_000


def test_hero_is_the_largest_and_the_rest_run_newest_first(select):
    result = select([
        win("SMALL_NEW", days_ago=0, amount=10_000),
        win("BIG_OLD", days_ago=9, amount=800_000),
        win("MID", days_ago=4, amount=60_000, status="open"),
    ])["selection"]
    assert result["hero"]["opportunity_id"] == "BIG_OLD"
    assert [w["opportunity_id"] for w in result["others"]] == ["SMALL_NEW", "MID"]
    assert result["moreCount"] == 0


def test_the_list_caps_at_three_and_the_remainder_is_counted(select):
    wins = [win(f"W{i}", days_ago=i, amount=1_000 * (10 - i)) for i in range(6)]
    result = select(wins)["selection"]
    assert result["hero"]["opportunity_id"] == "W0"
    assert len(result["others"]) == 3
    assert result["moreCount"] == 2
    assert result["restCount"] == 5
    # The "plus N more" line describes the non-hero wins, so its breakdown has
    # to add up to restCount rather than to the whole qualifying set.
    assert result["restClosedWonCount"] + result["restTechnicalCount"] == result["restCount"]


def test_the_dismissal_signature_tracks_the_qualifying_set(select):
    """A refresh keeps the banner dismissed; a new win brings it back."""
    wins = [win("A", days_ago=1), win("B", days_ago=2, status="open")]
    first = select(wins)["selection"]["signature"]
    assert select(list(reversed(wins)))["selection"]["signature"] == first

    with_new = select(wins + [win("C", days_ago=0)])["selection"]["signature"]
    assert with_new != first

    # A loss arriving must not disturb a dismissal — it was never in the set.
    with_loss = select(wins + [win("L", days_ago=0, status="closed_lost")])
    assert with_loss["selection"]["signature"] == first

    # Shortening the window is a different set, so the banner returns.
    assert select(wins, window_days=7)["selection"]["signature"] != first
