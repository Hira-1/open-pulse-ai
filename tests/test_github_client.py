"""
Smoke tests for GitHubClient.

Run with:
    python -m tests.test_github_client
or (after adding pytest):
    pytest tests/test_github_client.py -v
"""

from utils.logger import setup_logging
setup_logging()

from collector.github_client import GitHubClient

TEST_OWNER = "langchain-ai"
TEST_REPO  = "langgraph"


def test_authentication():
    client = GitHubClient()
    status = client.get_rate_limit_status()
    assert "remaining" in status
    assert "limit" in status
    assert status["remaining"] >= 0
    print(f"  PASS  rate limit: {status['remaining']}/{status['limit']}, resets {status['reset_at']}")
    return client


def test_repo_info(client: GitHubClient):
    info = client.get_repo_info(TEST_OWNER, TEST_REPO)
    assert "stars" in info
    assert info["stars"] > 0
    print(f"  PASS  stars={info['stars']}, forks={info['forks']}, open_issues={info['open_issues']}")


def test_releases(client: GitHubClient):
    rel = client.get_releases(TEST_OWNER, TEST_REPO)
    assert "releases_30d" in rel
    assert "last_release_date" in rel
    print(
        f"  PASS  releases_30d={rel['releases_30d']}, "
        f"releases_90d={rel['releases_90d']}, "
        f"last={rel['last_release_date']}, "
        f"days_since={rel['days_since_last_release']}, "
        f"total_fetched={len(rel['release_list'])}"
    )


def test_readme(client: GitHubClient):
    readme = client.get_readme(TEST_OWNER, TEST_REPO)
    assert "readme_length_chars" in readme
    assert readme["readme_length_chars"] > 0
    print(f"  PASS  readme_length={readme['readme_length_chars']} chars")


if __name__ == "__main__":
    print(f"\n=== GitHubClient Smoke Tests ({TEST_OWNER}/{TEST_REPO}) ===\n")
    client = test_authentication()
    test_repo_info(client)
    test_releases(client)
    test_readme(client)
    print("\nAll tests passed.")
