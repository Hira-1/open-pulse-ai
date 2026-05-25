"""
Smoke test for Risk Detector.

Loads scored snapshots from DB and generates risk alerts for each repo.

Run with:
    python -m tests.test_risk_detector
"""

import logging

from utils.logger import setup_logging
setup_logging()

from analytics.risk_detector import detect_risks
from database.schema import get_connection, init_db

log = logging.getLogger(__name__)

SEVERITY_ICONS = {"critical": "🔴", "warning": "🟡", "info": "🟢"}


def test_detect_all():
    init_db()
    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM repo_snapshots ORDER BY health_score DESC"
    ).fetchall()
    conn.close()

    assert len(rows) > 0, "No snapshots in DB — run collect.py first"

    for row in rows:
        snapshot = dict(row)
        alerts = detect_risks(snapshot)

        log.info(f"--- {snapshot['display_name']} (health={snapshot['health_score']:.1f}) ---")
        for a in alerts:
            icon = SEVERITY_ICONS.get(a["severity"], "?")
            log.info(f"  {icon} [{a['severity'].upper()}] {a['title']}: {a['description']}")

    log.info("PASS  Risk detection complete for all repos")


if __name__ == "__main__":
    test_detect_all()
