"""
Smoke test for Trend Engine.

Run with:
    python -m tests.test_trend_engine
"""

import logging

from utils.logger import setup_logging
setup_logging()

from analytics.trend_engine import compute_trends, compute_rankings
from config import TRACKED_REPOS
from database.schema import init_db

log = logging.getLogger(__name__)


def test_trends():
    init_db()

    log.info("=== Trend Deltas ===")
    for repo_cfg in TRACKED_REPOS:
        repo_key = f"{repo_cfg['owner']}/{repo_cfg['repo']}"
        trend = compute_trends(repo_key)

        status = "has_previous" if trend["has_previous"] else "first_snapshot"
        health_delta = trend["deltas"].get("health_score", {}).get("value", "N/A")
        stars_delta = trend["deltas"].get("stars", {}).get("value", "N/A")

        log.info(
            f"  {repo_cfg['display_name']:<20} | {status:<15} | "
            f"health_delta={health_delta} | stars_delta={stars_delta}"
        )


def test_rankings():
    log.info("=== Cross-Repo Rankings ===")
    rankings = compute_rankings()

    header = f"{'Repo':<20} {'Health':>7} {'H.Rank':>7} {'Stars':>8} {'S.Rank':>7} {'Commits30d':>11} {'C.Rank':>7}"
    log.info(header)
    log.info("-" * len(header))

    for r in rankings:
        log.info(
            f"{r['display_name']:<20} {r['health_score']:>7.1f} {r['health_score_rank']:>7} "
            f"{r['stars']:>8} {r['stars_rank']:>7} "
            f"{r['commits_30d']:>11} {r['commits_30d_rank']:>7}"
        )

    log.info("PASS  Trend engine complete")


if __name__ == "__main__":
    test_trends()
    test_rankings()
