"""
Authenticated GitHub API client for OpenPulse AI.

Responsibilities:
  - Single authenticated entry point for all GitHub API calls
  - Rate-limit awareness: pauses automatically when quota is low
  - Retry logic via tenacity for transient errors
  - Clean per-concern methods used by metrics_collector.py
"""

import os
import time
import logging
from datetime import datetime, timezone, timedelta

import httpx
from github import Github, GithubException, UnknownObjectException
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

RATE_LIMIT_BUFFER = 50


class GitHubClient:
    """
    Thin wrapper around PyGithub that adds:
      - Automatic rate-limit pausing
      - Retry on transient GithubException (5xx, timeouts)
      - Consistent return shapes consumed by MetricsCollector
    """

    def __init__(self) -> None:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN not found. Copy .env.example → .env and set your token."
            )
        self._gh = Github(token, per_page=100)
        logger.info("[github_client] Authenticated. Checking rate limit...")
        status = self.get_rate_limit_status()
        logger.info(
            f"[github_client] Rate limit: {status['remaining']}/{status['limit']} "
            f"resets at {status['reset_at']}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _core_rate_limit(self):
        """
        Return the core rate limit object regardless of PyGithub version.
        PyGithub 2.9+ changed the return type of get_rate_limit().
        """
        rate_obj = self._gh.get_rate_limit()
        if hasattr(rate_obj, 'core'):
            return rate_obj.core
        if hasattr(rate_obj, 'resources') and hasattr(rate_obj.resources, 'core'):
            return rate_obj.resources.core
        return rate_obj

    def _check_rate_limit(self) -> None:
        """Pause execution if remaining API calls fall below the safety buffer."""
        rl = self._core_rate_limit()
        if rl.remaining < RATE_LIMIT_BUFFER:
            reset_dt = rl.reset
            if reset_dt.tzinfo is None:
                reset_dt = reset_dt.replace(tzinfo=timezone.utc)
            wait_secs = (reset_dt - datetime.now(timezone.utc)).total_seconds() + 10
            wait_secs = max(wait_secs, 0)
            logger.warning(
                f"[github_client] Only {rl.remaining} requests left. "
                f"Sleeping {wait_secs:.0f}s until reset."
            )
            time.sleep(wait_secs)

    @retry(
        retry=retry_if_exception_type(GithubException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get_repo(self, owner: str, repo: str):
        """Fetch and return a PyGithub Repository object with retry."""
        self._check_rate_limit()
        return self._gh.get_repo(f"{owner}/{repo}")

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_rate_limit_status(self) -> dict:
        """Return current rate limit info — used for diagnostics and logging."""
        rl = self._core_rate_limit()
        reset_dt = rl.reset
        if reset_dt.tzinfo is None:
            reset_dt = reset_dt.replace(tzinfo=timezone.utc)
        return {
            "remaining": rl.remaining,
            "limit": rl.limit,
            "reset_at": reset_dt.isoformat(),
        }

    def get_repo_info(self, owner: str, repo: str) -> dict:
        """
        Basic repository metadata.

        Returns: stars, forks, watchers, open_issues
        """
        r = self._get_repo(owner, repo)
        return {
            "stars": r.stargazers_count,
            "forks": r.forks_count,
            "watchers": r.watchers_count,
            "open_issues": r.open_issues_count,
        }

    def get_issues_stats(self, owner: str, repo: str, days: int = 30) -> dict:
        """
        Issue health metrics using GitHub Search API (efficient, no pagination).

        Returns:
          closed_issues_30d      — issues closed in the last `days` days
          avg_issue_close_days   — average time to close (days)
          stale_issues_count     — open issues with no activity in 90+ days
        """
        self._check_rate_limit()
        now = datetime.now(timezone.utc)
        since_str = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        stale_str = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        repo_key = f"{owner}/{repo}"

        # Closed issues in window — Search API: 30 req/min authenticated
        closed_query = (
            f"repo:{repo_key} is:issue is:closed closed:>{since_str}"
        )
        closed_results = self._gh.search_issues(closed_query)
        closed_count = closed_results.totalCount

        # Average close time from the first page (up to 30 issues — representative sample)
        close_times = []
        for issue in closed_results[:30]:
            if issue.created_at and issue.closed_at:
                created = issue.created_at.replace(tzinfo=timezone.utc)
                closed = issue.closed_at.replace(tzinfo=timezone.utc)
                close_times.append((closed - created).total_seconds() / 86400)
        avg_close_days = round(sum(close_times) / len(close_times), 2) if close_times else 0.0

        # Stale open issues — no update in 90+ days
        stale_query = (
            f"repo:{repo_key} is:issue is:open updated:<{stale_str}"
        )
        stale_count = self._gh.search_issues(stale_query).totalCount

        return {
            "closed_issues_30d": closed_count,
            "avg_issue_close_days": avg_close_days,
            "stale_issues_count": stale_count,
        }

    def _graphql_query(self, query: str, variables: dict) -> dict | None:
        """
        Execute a GitHub GraphQL query via httpx.
        More reliable than REST stats endpoints — never returns 202.
        """
        token = os.getenv("GITHUB_TOKEN", "")
        try:
            resp = httpx.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": variables},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json().get("data")
            logger.warning(f"[github_client] GraphQL returned HTTP {resp.status_code}")
        except httpx.RequestError as exc:
            logger.warning(f"[github_client] GraphQL request error: {exc}")
        return None

    def get_commit_activity(self, owner: str, repo: str) -> dict:
        """
        Commit counts via GitHub GraphQL API.
        Reliable alternative to /stats/commit_activity which returns 202 indefinitely
        for large repositories.

        Returns: commits_30d, commits_90d
        """
        self._check_rate_limit()
        now = datetime.now(timezone.utc)

        QUERY = """
        query($owner: String!, $repo: String!, $since30: GitTimestamp!, $since90: GitTimestamp!) {
          repository(owner: $owner, name: $repo) {
            defaultBranchRef {
              target {
                ... on Commit {
                  history30: history(since: $since30) { totalCount }
                  history90: history(since: $since90) { totalCount }
                }
              }
            }
          }
        }
        """
        variables = {
            "owner": owner,
            "repo": repo,
            "since30": (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "since90": (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        data = self._graphql_query(QUERY, variables)
        try:
            target = data["repository"]["defaultBranchRef"]["target"]
            return {
                "commits_30d": target["history30"]["totalCount"],
                "commits_90d": target["history90"]["totalCount"],
            }
        except (TypeError, KeyError):
            logger.warning(f"[github_client] Could not parse commit counts for {owner}/{repo}")
            return {"commits_30d": 0, "commits_90d": 0}

    def get_contributors(self, owner: str, repo: str, top_n: int = 10) -> dict:
        """
        Contributor metrics via PyGithub paginated list.

        Returns:
          contributors_total    — total contributor count from API Link headers
          contributors_new_30d  — unique authors with commits in last 30 days
          top_contributors      — list of {login, contributions, rank}
        """
        self._check_rate_limit()
        try:
            gh_repo = self._gh.get_repo(f"{owner}/{repo}")
            contributors_paged = gh_repo.get_contributors()
            total = contributors_paged.totalCount

            top_raw = []
            for c in contributors_paged[:top_n]:
                top_raw.append(c)
        except Exception as exc:
            logger.warning(f"[github_client] PyGithub contributors error: {exc}")
            return {"contributors_total": 0, "contributors_new_30d": 0, "top_contributors": []}

        if total == 0:
            return {"contributors_total": 0, "contributors_new_30d": 0, "top_contributors": []}

        top = [
            {"login": c.login, "contributions": c.contributions, "rank": i + 1}
            for i, c in enumerate(top_raw)
        ]

        # Get unique commit authors in the last 30 days via GraphQL
        new_30d = self._count_recent_commit_authors(owner, repo)

        return {
            "contributors_total": total,
            "contributors_new_30d": new_30d,
            "top_contributors": top,
        }

    def _count_recent_commit_authors(self, owner: str, repo: str) -> int:
        """Count unique commit authors in the last 30 days via GraphQL."""
        now = datetime.now(timezone.utc)
        QUERY = """
        query($owner: String!, $repo: String!, $since: GitTimestamp!) {
          repository(owner: $owner, name: $repo) {
            defaultBranchRef {
              target {
                ... on Commit {
                  history(since: $since, first: 100) {
                    nodes {
                      author { user { login } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {
            "owner": owner,
            "repo": repo,
            "since": (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        data = self._graphql_query(QUERY, variables)
        try:
            nodes = data["repository"]["defaultBranchRef"]["target"]["history"]["nodes"]
            logins = {
                node["author"]["user"]["login"]
                for node in nodes
                if node.get("author") and node["author"].get("user")
            }
            return len(logins)
        except (TypeError, KeyError):
            return 0

    def get_releases(self, owner: str, repo: str) -> dict:
        """
        Release history and velocity metrics.

        Returns:
          releases_30d           — releases published in last 30 days
          releases_90d           — releases published in last 90 days
          last_release_date      — ISO timestamp of most recent release
          days_since_last_release
          release_list           — structured list for DB insertion
        """
        self._check_rate_limit()
        r = self._get_repo(owner, repo)
        now = datetime.now(timezone.utc)
        cutoff_30 = now - timedelta(days=30)
        cutoff_90 = now - timedelta(days=90)

        releases = list(r.get_releases())
        count_30 = 0
        count_90 = 0
        last_release_date = None
        release_list = []

        for rel in releases:
            pub = rel.published_at
            if not pub:
                continue
            pub = pub.replace(tzinfo=timezone.utc)
            if last_release_date is None:
                last_release_date = pub.isoformat()
            if pub >= cutoff_30:
                count_30 += 1
            if pub >= cutoff_90:
                count_90 += 1
            release_list.append({
                "repo_key": f"{owner}/{repo}",
                "tag_name": rel.tag_name,
                "release_name": rel.title or rel.tag_name,
                "published_at": pub.isoformat(),
                "is_prerelease": int(rel.prerelease),
                "body_preview": (rel.body or "")[:300].strip(),
            })

        days_since = 0
        if last_release_date:
            last_dt = datetime.fromisoformat(last_release_date)
            days_since = (now - last_dt).days

        return {
            "releases_30d": count_30,
            "releases_90d": count_90,
            "last_release_date": last_release_date,
            "days_since_last_release": days_since,
            "release_list": release_list,
        }

    def get_readme(self, owner: str, repo: str) -> dict:
        """
        Fetch README content for LLM context.

        Returns: readme_length_chars, readme_content (first 5000 chars)
        """
        self._check_rate_limit()
        r = self._get_repo(owner, repo)
        try:
            readme = r.get_readme()
            content = readme.decoded_content.decode("utf-8", errors="ignore")
            return {
                "readme_length_chars": len(content),
                "readme_content": content[:5000],
            }
        except UnknownObjectException:
            return {"readme_length_chars": 0, "readme_content": ""}

    def get_dependency_info(self, owner: str, repo: str) -> dict:
        """
        Scan root-level dependency files for risk signals.

        Checks: pyproject.toml, requirements.txt, setup.cfg
        Flags:  git+ dependencies, missing dependency files

        Returns: has_pyproject, has_changelog, dependency_risk_count, dependency_risk_flags
        """
        self._check_rate_limit()
        r = self._get_repo(owner, repo)

        has_pyproject = False
        risk_flags = []

        for filepath in ["pyproject.toml", "requirements.txt", "setup.cfg"]:
            try:
                file_obj = r.get_contents(filepath)
                content = file_obj.decoded_content.decode("utf-8", errors="ignore")
                if filepath == "pyproject.toml":
                    has_pyproject = True
                if "git+" in content:
                    risk_flags.append(f"git-pinned dependency in {filepath}")
                if "http://" in content:
                    risk_flags.append(f"insecure http:// dependency in {filepath}")
            except UnknownObjectException:
                continue

        has_changelog = self._has_changelog(r)

        return {
            "has_pyproject": int(has_pyproject),
            "has_changelog": int(has_changelog),
            "dependency_risk_count": len(risk_flags),
            "dependency_risk_flags": risk_flags,
        }

    def _has_changelog(self, repo_obj) -> bool:
        """Check if a CHANGELOG file exists at the repository root."""
        for name in ["CHANGELOG.md", "CHANGELOG.rst", "CHANGELOG", "CHANGES.md", "HISTORY.md"]:
            try:
                repo_obj.get_contents(name)
                return True
            except UnknownObjectException:
                continue
        return False
