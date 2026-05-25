"""
SnapshotWriter — persists MetricsCollector output to SQLite.

Handles:
  - Upsert of repo_snapshots (one row per repo per day)
  - Bulk insert of repo_releases (skips duplicates via INSERT OR IGNORE)
  - Bulk insert of repo_contributors (replaces on conflict)
"""

import json
import logging
from datetime import datetime, timezone

from database.schema import managed_connection

logger = logging.getLogger(__name__)


class SnapshotWriter:
    """
    Writes a single repo's collected metrics payload to the database.

    Designed to be called once per repo per collection run.
    All writes are wrapped in a single transaction per repo.
    """

    def write(self, payload: dict) -> None:
        """
        Persist a full collection payload to SQLite.

        Args:
            payload: dict returned by MetricsCollector.collect()
                     Keys: 'snapshot', 'releases', 'contributors'
        """
        snapshot     = payload["snapshot"]
        releases     = payload["releases"]
        contributors = payload["contributors"]
        repo_key     = snapshot["repo_key"]

        with managed_connection() as conn:
            self._upsert_snapshot(conn, snapshot)
            self._insert_releases(conn, releases)
            self._insert_contributors(conn, contributors)

        logger.info(
            f"[snapshot_writer] {repo_key} | saved "
            f"snapshot + {len(releases)} releases + {len(contributors)} contributors"
        )

    # ------------------------------------------------------------------
    # Private write methods
    # ------------------------------------------------------------------

    def _upsert_snapshot(self, conn, snapshot: dict) -> None:
        """
        Insert or replace the snapshot row for this repo + date.
        Uses INSERT OR REPLACE so re-running collection on the same day
        overwrites the previous entry with fresh data.
        """
        # Strip non-DB keys (e.g. readme_content fetched for AI layer)
        db_keys = {
            "repo_key", "display_name", "collected_at",
            "stars", "forks", "watchers", "open_issues",
            "closed_issues_30d", "avg_issue_close_days", "stale_issues_count",
            "contributors_total", "contributors_new_30d",
            "commits_30d", "commits_90d",
            "releases_30d", "releases_90d", "last_release_date", "days_since_last_release",
            "readme_length_chars", "has_changelog", "has_pyproject",
            "dependency_risk_count", "dependency_risk_flags",
            "release_velocity_score", "issue_resolution_score",
            "contributor_activity_score", "docs_freshness_score",
            "dependency_risk_score", "health_score",
        }
        row = {k: snapshot[k] for k in db_keys if k in snapshot}

        # Use only the date portion as the uniqueness key (one snapshot per day)
        row["collected_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        columns      = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))

        conn.execute(
            f"INSERT OR REPLACE INTO repo_snapshots ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )

    def _insert_releases(self, conn, releases: list[dict]) -> None:
        """
        Insert releases — skips any that already exist (INSERT OR IGNORE).
        This means the first time a release is collected it is stored;
        subsequent runs don't duplicate it.
        """
        if not releases:
            return

        conn.executemany(
            """
            INSERT OR IGNORE INTO repo_releases
                (repo_key, tag_name, release_name, published_at, is_prerelease, body_preview)
            VALUES
                (:repo_key, :tag_name, :release_name, :published_at, :is_prerelease, :body_preview)
            """,
            releases,
        )

    def _insert_contributors(self, conn, contributors: list[dict]) -> None:
        """
        Insert or replace contributor rows for this repo + collection date.
        Replaces on conflict so re-runs stay fresh.
        """
        if not contributors:
            return

        conn.executemany(
            """
            INSERT OR REPLACE INTO repo_contributors
                (repo_key, collected_at, login, contributions, rank)
            VALUES
                (:repo_key, :collected_at, :login, :contributions, :rank)
            """,
            contributors,
        )
