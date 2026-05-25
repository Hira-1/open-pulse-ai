"""
Smoke test for SnapshotWriter.

Runs a real collection for one repo and writes it to the DB,
then reads it back to verify persistence.

Run with:
    python -m tests.test_snapshot_writer
"""

import logging

from utils.logger import setup_logging
setup_logging()

from collector.github_client import GitHubClient
from collector.metrics_collector import MetricsCollector
from collector.snapshot_writer import SnapshotWriter
from database.schema import get_connection, init_db

log = logging.getLogger(__name__)

TEST_OWNER        = "langchain-ai"
TEST_REPO         = "langgraph"
TEST_DISPLAY_NAME = "LangGraph"


def test_write_and_read():
    init_db()

    client    = GitHubClient()
    collector = MetricsCollector(client)
    writer    = SnapshotWriter()

    log.info(f"Collecting metrics for {TEST_OWNER}/{TEST_REPO}...")
    payload = collector.collect(TEST_OWNER, TEST_REPO, TEST_DISPLAY_NAME)

    log.info("Writing to database...")
    writer.write(payload)

    repo_key = f"{TEST_OWNER}/{TEST_REPO}"
    conn = get_connection()

    # -- Verify snapshot row
    row = conn.execute(
        "SELECT * FROM repo_snapshots WHERE repo_key = ? ORDER BY collected_at DESC LIMIT 1",
        (repo_key,)
    ).fetchone()
    assert row is not None, "No snapshot row found"
    assert row["stars"] > 0
    assert row["health_score"] == 0.0   # analytics layer fills this later
    log.info(f"  snapshot row: stars={row['stars']}, commits_30d={row['commits_30d']}, "
             f"releases_30d={row['releases_30d']}, contributors_total={row['contributors_total']}")

    # -- Verify releases
    release_count = conn.execute(
        "SELECT COUNT(*) FROM repo_releases WHERE repo_key = ?", (repo_key,)
    ).fetchone()[0]
    assert release_count > 0
    log.info(f"  releases stored: {release_count}")

    # -- Verify contributors
    contrib_count = conn.execute(
        "SELECT COUNT(*) FROM repo_contributors WHERE repo_key = ?", (repo_key,)
    ).fetchone()[0]
    assert contrib_count > 0
    top = conn.execute(
        "SELECT login, contributions FROM repo_contributors WHERE repo_key = ? ORDER BY rank LIMIT 1",
        (repo_key,)
    ).fetchone()
    log.info(f"  contributors stored: {contrib_count} | top: {top['login']} ({top['contributions']} commits)")

    conn.close()
    log.info("PASS  SnapshotWriter — data written and verified in DB")


if __name__ == "__main__":
    log.info(f"=== SnapshotWriter Smoke Test ({TEST_OWNER}/{TEST_REPO}) ===")
    test_write_and_read()
