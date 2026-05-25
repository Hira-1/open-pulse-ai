"""
Smoke test for Health Score Calculator.

Loads the latest snapshot for each repo from the DB, computes
scores, updates the DB, and prints a summary leaderboard.

Run with:
    python -m tests.test_health_score
"""

import logging

from utils.logger import setup_logging
setup_logging()

from analytics.health_score import compute_health_score
from config import get_status
from database.schema import get_connection, init_db

log = logging.getLogger(__name__)


def test_score_all_repos():
    init_db()
    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM repo_snapshots ORDER BY collected_at DESC"
    ).fetchall()

    assert len(rows) > 0, "No snapshots in DB — run collect.py first"

    results = []
    for row in rows:
        snapshot = dict(row)
        scores = compute_health_score(snapshot)

        # Update DB with computed scores
        conn.execute(
            """
            UPDATE repo_snapshots
               SET release_velocity_score     = ?,
                   issue_resolution_score     = ?,
                   contributor_activity_score = ?,
                   docs_freshness_score       = ?,
                   dependency_risk_score      = ?,
                   health_score               = ?
             WHERE repo_key = ? AND collected_at = ?
            """,
            (
                scores["release_velocity_score"],
                scores["issue_resolution_score"],
                scores["contributor_activity_score"],
                scores["docs_freshness_score"],
                scores["dependency_risk_score"],
                scores["health_score"],
                snapshot["repo_key"],
                snapshot["collected_at"],
            ),
        )

        label, color = get_status(scores["health_score"])
        results.append({
            "name": snapshot["display_name"],
            "health": scores["health_score"],
            "label": label,
            "release": scores["release_velocity_score"],
            "issue": scores["issue_resolution_score"],
            "contrib": scores["contributor_activity_score"],
            "docs": scores["docs_freshness_score"],
            "deps": scores["dependency_risk_score"],
        })

    conn.commit()
    conn.close()

    # Sort by health score descending
    results.sort(key=lambda r: r["health"], reverse=True)

    log.info("=" * 90)
    log.info(f"{'Repo':<20} {'Health':>7} {'Status':<15} {'Release':>8} {'Issue':>8} {'Contrib':>8} {'Docs':>8} {'Deps':>8}")
    log.info("-" * 90)
    for r in results:
        log.info(
            f"{r['name']:<20} {r['health']:>7.1f} {r['label']:<15} "
            f"{r['release']:>8.1f} {r['issue']:>8.1f} {r['contrib']:>8.1f} "
            f"{r['docs']:>8.1f} {r['deps']:>8.1f}"
        )
    log.info("=" * 90)
    log.info(f"PASS  Scored {len(results)} repos and updated DB")


if __name__ == "__main__":
    test_score_all_repos()
