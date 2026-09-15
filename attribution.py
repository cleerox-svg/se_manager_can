"""Shared SE attribution precedence for `tech_forecast_deals` rows.

Three steps, highest priority first:

1. ``assigned_se_rep_id`` — the manual override set from the Tech Forecast page.
2. a case-insensitive match of the sheet's ``lead_se_name`` against ``se_reps.name``.
3. fallback — the ``se_rep_id`` of a ``deals`` row with the same opportunity name.

CLAUDE.md records a shipped bug (fixed 2026-09-11) where one query site
implemented only step 3, so reps attributed via steps 1-2 reported $0 while the
Tech Forecast page showed real ARR. Keeping one copy of the precedence is what
stops that recurring: import from here rather than re-writing the COALESCE.
"""

# Correlated scalar subquery resolving the effective SE rep id for a
# `tech_forecast_deals` row aliased `tf`. Embed in a SELECT list, e.g.
#     f"SELECT tf.*, {EFFECTIVE_SE_ID_SQL} AS effective_se_rep_id FROM ..."
# Safe to interpolate: it is a module constant with no caller-supplied input.
EFFECTIVE_SE_ID_SQL = """COALESCE(
    tf.assigned_se_rep_id,
    (SELECT r2.id FROM se_reps r2
        WHERE lower(r2.name) = lower(tf.lead_se_name) LIMIT 1),
    (SELECT d2.se_rep_id FROM deals d2
        WHERE d2.opportunity_name = tf.opportunity_name ORDER BY d2.id LIMIT 1)
)"""

# The component ids, for callers that want to show which step resolved a deal
# (the Tech Forecast page distinguishes a sheet-named SE from a fallback match).
LEAD_SE_ID_SQL = """(SELECT r.id FROM se_reps r
    WHERE lower(r.name) = lower(tf.lead_se_name) LIMIT 1)"""

ATTRIBUTED_SE_ID_SQL = """(SELECT d.se_rep_id FROM deals d
    WHERE d.opportunity_name = tf.opportunity_name ORDER BY d.id LIMIT 1)"""


def effective_se_id(row):
    """Resolve the same three-step precedence in Python.

    For rows already carrying `assigned_se_rep_id`, `lead_se_rep_id` and
    `attributed_se_id` — avoids a second round trip when the SELECT above has
    already produced the components. Returns None when no step resolves.
    """
    return (
        row["assigned_se_rep_id"]
        or row["lead_se_rep_id"]
        or row["attributed_se_id"]
    )
