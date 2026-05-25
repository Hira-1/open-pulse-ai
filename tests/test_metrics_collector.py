"""
Smoke test for MetricsCollector.

Run with:
    python -m tests.test_metrics_collector
"""

import logging

from utils.logger import setup_logging
setup_logging()

from collector.github_client import GitHubClient
from collector.metrics_collector import MetricsCollector

TEST_OWNER        = "langchain-ai"
TEST_REPO         = "langgraph"
TEST_DISPLAY_NAME = "LangGraph"


def test_collect():
    client    = GitHubClient()
    collector = MetricsCollector(client)

    result = collector.collect(TEST_OWNER, TEST_REPO, TEST_DISPLAY_NAME)

    snapshot     = result["snapshot"]
    releases     = result["releases"]
    contributors = result["contributors"]

    # -- snapshot shape
    assert snapshot["repo_key"]      == f"{TEST_OWNER}/{TEST_REPO}"
    assert snapshot["display_name"]  == TEST_DISPLAY_NAME
    assert snapshot["stars"]         > 0
    assert snapshot["collected_at"]  != ""

    # -- scores are 0 at this stage (analytics layer fills them)
    assert snapshot["health_score"]  == 0.0

    # -- releases list
    assert isinstance(releases, list)
    if releases:
        assert "tag_name"     in releases[0]
        assert "published_at" in releases[0]

    # -- contributors list
    assert isinstance(contributors, list)
    if contributors:
        assert "login"         in contributors[0]
        assert "contributions" in contributors[0]
        assert "rank"          in contributors[0]

    log = logging.getLogger(__name__)
    keys = [
        "stars", "forks", "open_issues", "closed_issues_30d",
        "avg_issue_close_days", "stale_issues_count",
        "contributors_total", "contributors_new_30d",
        "commits_30d", "commits_90d",
        "releases_30d", "releases_90d", "days_since_last_release",
        "readme_length_chars", "has_pyproject", "has_changelog",
        "dependency_risk_count",
    ]
    log.info("--- Snapshot summary ---")
    for k in keys:
        log.info(f"  {k:<30} {snapshot.get(k)}")

    log.info(f"releases fetched    : {len(releases)}")
    log.info(f"contributors fetched: {len(contributors)}")
    if contributors:
        log.info(
            f"top contributor     : {contributors[0]['login']} "
            f"({contributors[0]['contributions']} commits)"
        )
    log.info("PASS  MetricsCollector.collect()")


if __name__ == "__main__":
    logging.getLogger(__name__).info(f"=== MetricsCollector Smoke Test ({TEST_OWNER}/{TEST_REPO}) ===")
    test_collect()
