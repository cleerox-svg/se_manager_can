"""Canonical SFDC stage strings and sheet markers.

These values arrive verbatim in sheet exports and drive revenue math, so a typo
or a missed filter silently corrupts totals rather than raising. CLAUDE.md
records two shipped bugs of exactly that kind. Import from here instead of
re-typing a literal.
"""

# Salesforce sales stage marking a commercially won deal.
#
# `closed_deals` holds BOTH Won and Lost rows — the tab is "closed deals", not
# "closed-won deals" — so every revenue query against that table must filter on
# this value or it double-counts Lost amounts as revenue.
STAGE_CLOSED_WON = "10 - Closed/Won"

# Presales stage marking a technical win.
#
# Independent of sales stage: a deal can be a technical win and still close
# Lost, which is why `tech_win = 1` alone is not a revenue filter.
PRESALES_TECH_WIN = "6 - Technical Win"

# Deal Forecast Status value flagging a deal as at risk.
FORECAST_RISK = "Forecasted Risk"
