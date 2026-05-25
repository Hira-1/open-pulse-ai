"""
Smoke test for AI Insight Generator.

Tests both LLM path (if OPENAI_API_KEY set) and fallback template path.

Run with:
    python -m tests.test_insight_generator
"""

import logging

from utils.logger import setup_logging
setup_logging()

from ai.insight_generator import generate_repo_insight, generate_ecosystem_insight
from analytics.risk_detector import detect_risks
from database.schema import get_connection, init_db

log = logging.getLogger(__name__)


def test_insights():
    init_db()
    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM repo_snapshots ORDER BY health_score DESC"
    ).fetchall()
    conn.close()

    assert len(rows) > 0, "No snapshots in DB — run collect.py first"

    all_snapshots = [dict(r) for r in rows]
    all_alerts = {}

    log.info("=== Per-Repo Insights ===")
    for snapshot in all_snapshots:
        alerts = detect_risks(snapshot)
        all_alerts[snapshot["repo_key"]] = alerts
        insight = generate_repo_insight(snapshot, alerts)
        log.info(f"\n--- {snapshot['display_name']} ---")
        log.info(insight)

    log.info("\n=== Ecosystem Overview ===")
    eco_insight = generate_ecosystem_insight(all_snapshots, all_alerts)
    log.info(eco_insight)

    log.info("\nPASS  Insight generation complete")


if __name__ == "__main__":
    test_insights()
