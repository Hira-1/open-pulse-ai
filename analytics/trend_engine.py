"""
Trend Engine for OpenPulse AI.

Computes deltas between the latest snapshot and the previous snapshot
for each repo. When only one snapshot exists (first run), deltas are
reported as None — the dashboard renders these as "N/A (first snapshot)".

Also provides cross-repo comparison rankings for each metric.
"""

import logging
from database.schema import get_connection

logger = logging.getLogger(__name__)

# Metrics to track deltas for
DELTA_METRICS = [
    "stars", "forks", "open_issues",
    "closed_issues_30d", "avg_issue_close_days", "stale_issues_count",
    "contributors_total", "contributors_new_30d",
    "commits_30d", "commits_90d",
    "releases_30d", "releases_90d", "days_since_last_release",
    "health_score",
    "release_velocity_score", "issue_resolution_score",
    "contributor_activity_score", "docs_freshness_score",
    "dependency_risk_score",
]

# Metrics where lower is better (delta sign should be inverted for "good/bad")
LOWER_IS_BETTER = {
    "open_issues", "avg_issue_close_days", "stale_issues_count",
    "days_since_last_release", "dependency_risk_count",
}


def compute_trends(repo_key: str) -> dict:
    """
    Compute trend data for a single repo.

    Returns:
        {
            "repo_key": str,
            "has_previous": bool,
            "deltas": {metric: {"value": float|None, "pct": float|None, "direction": str}},
            "latest": dict (full latest snapshot),
            "previous": dict|None (full previous snapshot),
        }
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM repo_snapshots
        WHERE repo_key = ?
        ORDER BY collected_at DESC
        LIMIT 2
        """,
        (repo_key,),
    ).fetchall()
    conn.close()

    if not rows:
        logger.warning(f"[trend] No snapshots found for {repo_key}")
        return {"repo_key": repo_key, "has_previous": False, "deltas": {}, "latest": {}, "previous": None}

    latest = dict(rows[0])
    previous = dict(rows[1]) if len(rows) > 1 else None
    has_previous = previous is not None

    deltas = {}
    for metric in DELTA_METRICS:
        current_val = latest.get(metric) or 0
        if has_previous:
            prev_val = previous.get(metric) or 0
            abs_delta = round(current_val - prev_val, 2)
            pct_delta = round((abs_delta / prev_val) * 100, 2) if prev_val != 0 else None

            # Determine direction
            if abs_delta > 0:
                direction = "down" if metric in LOWER_IS_BETTER else "up"
            elif abs_delta < 0:
                direction = "up" if metric in LOWER_IS_BETTER else "down"
            else:
                direction = "flat"

            deltas[metric] = {"value": abs_delta, "pct": pct_delta, "direction": direction}
        else:
            deltas[metric] = {"value": None, "pct": None, "direction": "new"}

    logger.info(
        f"[trend] {latest.get('display_name', repo_key)} | "
        f"has_previous={has_previous} | "
        f"health_delta={deltas.get('health_score', {}).get('value', 'N/A')}"
    )

    return {
        "repo_key": repo_key,
        "has_previous": has_previous,
        "deltas": deltas,
        "latest": latest,
        "previous": previous,
    }


def compute_rankings() -> list[dict]:
    """
    Rank all repos on key metrics for cross-repo comparison.

    Returns a list of dicts with repo_key, display_name, and rank
    for each metric.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT s.repo_key, s.display_name, s.stars, s.forks, s.commits_30d,
               s.contributors_total, s.health_score, s.open_issues,
               s.releases_30d, s.avg_issue_close_days
        FROM repo_snapshots s
        INNER JOIN (
            SELECT repo_key, MAX(collected_at) AS max_date
            FROM repo_snapshots GROUP BY repo_key
        ) latest ON s.repo_key = latest.repo_key
                AND s.collected_at = latest.max_date
        ORDER BY s.health_score DESC
        """
    ).fetchall()
    conn.close()

    if not rows:
        return []

    repos = [dict(r) for r in rows]

    # Rank by each metric (higher is better, except for LOWER_IS_BETTER)
    rank_metrics = {
        "stars": False,
        "forks": False,
        "commits_30d": False,
        "contributors_total": False,
        "health_score": False,
        "releases_30d": False,
        "open_issues": True,           # lower is better
        "avg_issue_close_days": True,   # lower is better
    }

    for metric, lower_better in rank_metrics.items():
        sorted_repos = sorted(
            repos,
            key=lambda r: r.get(metric) or 0,
            reverse=not lower_better,
        )
        for rank, repo in enumerate(sorted_repos, start=1):
            repo[f"{metric}_rank"] = rank

    logger.info(f"[trend] Ranked {len(repos)} repos across {len(rank_metrics)} metrics")
    return repos
