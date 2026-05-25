"""
Health Score Calculator for OpenPulse AI.

Computes a 0–100 composite health score from five sub-scores,
each also on a 0–100 scale. Sub-scores are normalized using
realistic benchmarks derived from the AI agent framework ecosystem.

Sub-scores:
  1. Release Velocity      (25%) — release cadence and recency
  2. Issue Resolution      (25%) — close rate, speed, and backlog health
  3. Contributor Activity  (20%) — commit velocity, team size, growth
  4. Docs Freshness        (15%) — README length, changelog, pyproject
  5. Dependency Risk       (15%) — inverted risk flag count
"""

import logging

from config import SCORE_WEIGHTS

logger = logging.getLogger(__name__)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ------------------------------------------------------------------
# Sub-score calculators
# ------------------------------------------------------------------

def release_velocity_score(snapshot: dict) -> float:
    """
    Scoring logic:
      - releases_30d    : 40 pts  (0 → 0, 5+ → 40)
      - releases_90d    : 30 pts  (0 → 0, 15+ → 30)
      - days_since_last  : 30 pts  (0 → 30, 90+ → 0)
    """
    r30 = snapshot.get("releases_30d", 0)
    r90 = snapshot.get("releases_90d", 0)
    days = snapshot.get("days_since_last_release", 999)

    pts_r30  = _clamp(r30 / 5 * 40, 0, 40)
    pts_r90  = _clamp(r90 / 15 * 30, 0, 30)
    pts_days = _clamp((1 - days / 90) * 30, 0, 30)

    return round(_clamp(pts_r30 + pts_r90 + pts_days), 2)


def issue_resolution_score(snapshot: dict) -> float:
    """
    Scoring logic:
      - closed_30d / open_issues ratio : 40 pts
      - avg_close_days                 : 30 pts  (<7d → 30, >60d → 0)
      - stale_issues_count             : 30 pts  (0 → 30, 100+ → 0)
    """
    closed = snapshot.get("closed_issues_30d", 0)
    open_i = snapshot.get("open_issues", 1)
    avg_close = snapshot.get("avg_issue_close_days", 60)
    stale = snapshot.get("stale_issues_count", 0)

    ratio = closed / max(open_i, 1)
    pts_ratio = _clamp(ratio / 0.3 * 40, 0, 40)
    pts_speed = _clamp((1 - avg_close / 60) * 30, 0, 30)
    pts_stale = _clamp((1 - stale / 100) * 30, 0, 30)

    return round(_clamp(pts_ratio + pts_speed + pts_stale), 2)


def contributor_activity_score(snapshot: dict) -> float:
    """
    Scoring logic:
      - commits_30d          : 35 pts  (0 → 0, 100+ → 35)
      - contributors_total   : 35 pts  (0 → 0, 200+ → 35)
      - contributors_new_30d : 30 pts  (0 → 0, 10+ → 30)
    """
    c30   = snapshot.get("commits_30d", 0)
    total = snapshot.get("contributors_total", 0)
    new30 = snapshot.get("contributors_new_30d", 0)

    pts_commits = _clamp(c30 / 100 * 35, 0, 35)
    pts_total   = _clamp(total / 200 * 35, 0, 35)
    pts_new     = _clamp(new30 / 10 * 30, 0, 30)

    return round(_clamp(pts_commits + pts_total + pts_new), 2)


def docs_freshness_score(snapshot: dict) -> float:
    """
    Scoring logic:
      - readme_length_chars  : 40 pts  (0 → 0, 5000+ → 40)
      - has_pyproject        : 30 pts  (bool)
      - has_changelog        : 30 pts  (bool)
    """
    readme_len = snapshot.get("readme_length_chars", 0)
    has_pp     = snapshot.get("has_pyproject", 0)
    has_cl     = snapshot.get("has_changelog", 0)

    pts_readme = _clamp(readme_len / 5000 * 40, 0, 40)
    pts_pp     = 30.0 if has_pp else 0.0
    pts_cl     = 30.0 if has_cl else 0.0

    return round(_clamp(pts_readme + pts_pp + pts_cl), 2)


def dependency_risk_score(snapshot: dict) -> float:
    """
    Inverted score — fewer risk flags = higher score.
      - 0 flags → 100
      - 5+ flags → 0
    """
    flags = snapshot.get("dependency_risk_count", 0)
    return round(_clamp((1 - flags / 5) * 100, 0, 100), 2)


# ------------------------------------------------------------------
# Composite health score
# ------------------------------------------------------------------

def compute_health_score(snapshot: dict) -> dict:
    """
    Compute all sub-scores and the weighted composite health score.

    Returns a dict with keys:
      release_velocity_score, issue_resolution_score,
      contributor_activity_score, docs_freshness_score,
      dependency_risk_score, health_score
    """
    scores = {
        "release_velocity_score":     release_velocity_score(snapshot),
        "issue_resolution_score":     issue_resolution_score(snapshot),
        "contributor_activity_score": contributor_activity_score(snapshot),
        "docs_freshness_score":       docs_freshness_score(snapshot),
        "dependency_risk_score":      dependency_risk_score(snapshot),
    }

    health = round(
        scores["release_velocity_score"]     * SCORE_WEIGHTS["release_velocity"]
        + scores["issue_resolution_score"]   * SCORE_WEIGHTS["issue_resolution"]
        + scores["contributor_activity_score"] * SCORE_WEIGHTS["contributor_activity"]
        + scores["docs_freshness_score"]     * SCORE_WEIGHTS["docs_freshness"]
        + scores["dependency_risk_score"]    * SCORE_WEIGHTS["dependency_risk"],
        2,
    )

    scores["health_score"] = health

    logger.info(
        f"[health] {snapshot.get('display_name', snapshot.get('repo_key'))} | "
        f"health={health} | "
        f"release={scores['release_velocity_score']} "
        f"issue={scores['issue_resolution_score']} "
        f"contrib={scores['contributor_activity_score']} "
        f"docs={scores['docs_freshness_score']} "
        f"deps={scores['dependency_risk_score']}"
    )

    return scores
