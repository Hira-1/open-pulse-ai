"""
MetricsCollector — orchestrates all GitHub API calls for a single repository
and returns a unified payload ready for database insertion.

Return shape:
    {
        "snapshot":     dict  — matches repo_snapshots columns
        "releases":     list  — rows for repo_releases
        "contributors": list  — rows for repo_contributors
    }

Scores (release_velocity, issue_resolution, etc.) are left at 0.0 here.
They are computed by the analytics layer after collection.
"""

import json
import logging
from datetime import datetime, timezone

from collector.github_client import GitHubClient

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Collects all measurable signals for one repository via the GitHub API.

    Each fetch method is called independently so that a failure in one area
    (e.g. Search API rate limit) does not abort the entire collection run.
    Partial data is always better than no data.
    """

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def collect(self, owner: str, repo: str, display_name: str) -> dict:
        """
        Run a full metrics collection pass for one repository.

        Args:
            owner:        GitHub owner/org (e.g. "langchain-ai")
            repo:         Repository name  (e.g. "langgraph")
            display_name: Human-friendly label (e.g. "LangGraph")

        Returns:
            {
                "snapshot":     dict,
                "releases":     list[dict],
                "contributors": list[dict],
            }
        """
        repo_key = f"{owner}/{repo}"
        collected_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"[collector] Starting collection for {repo_key}")

        snapshot = {
            "repo_key":                   repo_key,
            "display_name":               display_name,
            "collected_at":               collected_at,
            # raw metrics — filled below
            "stars":                      0,
            "forks":                      0,
            "watchers":                   0,
            "open_issues":                0,
            "closed_issues_30d":          0,
            "avg_issue_close_days":       0.0,
            "stale_issues_count":         0,
            "contributors_total":         0,
            "contributors_new_30d":       0,
            "commits_30d":                0,
            "commits_90d":                0,
            "releases_30d":               0,
            "releases_90d":               0,
            "last_release_date":          None,
            "days_since_last_release":    0,
            "readme_length_chars":        0,
            "has_changelog":              0,
            "has_pyproject":              0,
            "dependency_risk_count":      0,
            "dependency_risk_flags":      "[]",
            # scores — computed by analytics layer, stored later
            "release_velocity_score":     0.0,
            "issue_resolution_score":     0.0,
            "contributor_activity_score": 0.0,
            "docs_freshness_score":       0.0,
            "dependency_risk_score":      0.0,
            "health_score":               0.0,
        }
        releases:     list[dict] = []
        contributors: list[dict] = []

        # ------------------------------------------------------------------
        # 1. Basic repo info — stars, forks, watchers, open_issues
        # ------------------------------------------------------------------
        try:
            info = self._client.get_repo_info(owner, repo)
            snapshot.update(info)
            logger.info(f"[collector] {repo_key} | repo_info OK | stars={info['stars']}")
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | repo_info FAILED: {exc}")

        # ------------------------------------------------------------------
        # 2. Issue stats — closed_30d, avg_close_days, stale_count
        # ------------------------------------------------------------------
        try:
            issues = self._client.get_issues_stats(owner, repo, days=30)
            snapshot.update(issues)
            logger.info(
                f"[collector] {repo_key} | issues OK | "
                f"closed_30d={issues['closed_issues_30d']}, "
                f"avg_close={issues['avg_issue_close_days']}d, "
                f"stale={issues['stale_issues_count']}"
            )
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | issues FAILED: {exc}")

        # ------------------------------------------------------------------
        # 3. Commit activity — commits_30d, commits_90d
        # ------------------------------------------------------------------
        try:
            commits = self._client.get_commit_activity(owner, repo)
            snapshot.update(commits)
            logger.info(
                f"[collector] {repo_key} | commits OK | "
                f"30d={commits['commits_30d']}, 90d={commits['commits_90d']}"
            )
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | commits FAILED: {exc}")

        # ------------------------------------------------------------------
        # 4. Contributors — total, new_30d, top list
        # ------------------------------------------------------------------
        try:
            contrib = self._client.get_contributors(owner, repo, top_n=10)
            snapshot["contributors_total"]   = contrib["contributors_total"]
            snapshot["contributors_new_30d"] = contrib["contributors_new_30d"]
            contributors = [
                {
                    "repo_key":     repo_key,
                    "collected_at": collected_at,
                    "login":        c["login"],
                    "contributions": c["contributions"],
                    "rank":         c["rank"],
                }
                for c in contrib["top_contributors"]
            ]
            logger.info(
                f"[collector] {repo_key} | contributors OK | "
                f"total={contrib['contributors_total']}, "
                f"new_30d={contrib['contributors_new_30d']}"
            )
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | contributors FAILED: {exc}")

        # ------------------------------------------------------------------
        # 5. Releases — counts, last date, full release list
        # ------------------------------------------------------------------
        try:
            rel = self._client.get_releases(owner, repo)
            snapshot["releases_30d"]            = rel["releases_30d"]
            snapshot["releases_90d"]            = rel["releases_90d"]
            snapshot["last_release_date"]       = rel["last_release_date"]
            snapshot["days_since_last_release"] = rel["days_since_last_release"]
            releases = rel["release_list"]
            logger.info(
                f"[collector] {repo_key} | releases OK | "
                f"30d={rel['releases_30d']}, 90d={rel['releases_90d']}"
            )
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | releases FAILED: {exc}")

        # ------------------------------------------------------------------
        # 6. README — length for docs freshness scoring
        # ------------------------------------------------------------------
        try:
            readme = self._client.get_readme(owner, repo)
            snapshot["readme_length_chars"] = readme["readme_length_chars"]
            snapshot["readme_content"]      = readme.get("readme_content", "")
            logger.info(
                f"[collector] {repo_key} | readme OK | "
                f"length={readme['readme_length_chars']} chars"
            )
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | readme FAILED: {exc}")

        # ------------------------------------------------------------------
        # 7. Dependency info — pyproject, changelog, risk flags
        # ------------------------------------------------------------------
        try:
            deps = self._client.get_dependency_info(owner, repo)
            snapshot["has_pyproject"]         = deps["has_pyproject"]
            snapshot["has_changelog"]         = deps["has_changelog"]
            snapshot["dependency_risk_count"] = deps["dependency_risk_count"]
            snapshot["dependency_risk_flags"] = json.dumps(deps["dependency_risk_flags"])
            logger.info(
                f"[collector] {repo_key} | deps OK | "
                f"has_pyproject={deps['has_pyproject']}, "
                f"has_changelog={deps['has_changelog']}, "
                f"risk_flags={deps['dependency_risk_count']}"
            )
        except Exception as exc:
            logger.warning(f"[collector] {repo_key} | deps FAILED: {exc}")

        logger.info(f"[collector] {repo_key} | collection complete")

        return {
            "snapshot":     snapshot,
            "releases":     releases,
            "contributors": contributors,
        }
