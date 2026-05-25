"""
Database schema and connection management for OpenPulse AI.

Tables:
  - repo_snapshots   : Daily health metrics per repository
  - repo_releases    : Release history per repository
  - repo_contributors: Top contributor data per collection run
"""

import os
import sqlite3
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/openpulse.db")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set to Row for dict-like access."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def managed_connection():
    """Context manager that commits on success and rolls back on error."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they do not already exist."""
    with managed_connection() as conn:
        conn.executescript("""
            -- ----------------------------------------------------------------
            -- repo_snapshots
            -- One row per repository per collection run.
            -- Stores all raw metrics + computed health scores.
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS repo_snapshots (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_key                    TEXT    NOT NULL,
                display_name                TEXT    NOT NULL,
                collected_at                TEXT    NOT NULL,

                -- Raw GitHub metrics
                stars                       INTEGER DEFAULT 0,
                forks                       INTEGER DEFAULT 0,
                watchers                    INTEGER DEFAULT 0,
                open_issues                 INTEGER DEFAULT 0,
                closed_issues_30d           INTEGER DEFAULT 0,
                avg_issue_close_days        REAL    DEFAULT 0.0,
                stale_issues_count          INTEGER DEFAULT 0,
                contributors_total          INTEGER DEFAULT 0,
                contributors_new_30d        INTEGER DEFAULT 0,
                commits_30d                 INTEGER DEFAULT 0,
                commits_90d                 INTEGER DEFAULT 0,
                releases_30d                INTEGER DEFAULT 0,
                releases_90d                INTEGER DEFAULT 0,
                last_release_date           TEXT,
                days_since_last_release     INTEGER DEFAULT 0,

                -- Documentation & dependency signals
                readme_length_chars         INTEGER DEFAULT 0,
                has_changelog               INTEGER DEFAULT 0,
                has_pyproject               INTEGER DEFAULT 0,
                dependency_risk_count       INTEGER DEFAULT 0,
                dependency_risk_flags       TEXT    DEFAULT '[]',

                -- Computed health sub-scores (0–100)
                release_velocity_score      REAL    DEFAULT 0.0,
                issue_resolution_score      REAL    DEFAULT 0.0,
                contributor_activity_score  REAL    DEFAULT 0.0,
                docs_freshness_score        REAL    DEFAULT 0.0,
                dependency_risk_score       REAL    DEFAULT 0.0,

                -- Composite health score (0–100)
                health_score                REAL    DEFAULT 0.0,

                UNIQUE (repo_key, collected_at)
            );

            -- ----------------------------------------------------------------
            -- repo_releases
            -- One row per GitHub release per repository.
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS repo_releases (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_key        TEXT    NOT NULL,
                tag_name        TEXT    NOT NULL,
                release_name    TEXT,
                published_at    TEXT,
                is_prerelease   INTEGER DEFAULT 0,
                body_preview    TEXT,

                UNIQUE (repo_key, tag_name)
            );

            -- ----------------------------------------------------------------
            -- repo_contributors
            -- Top contributors per repository per collection run.
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS repo_contributors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_key        TEXT    NOT NULL,
                collected_at    TEXT    NOT NULL,
                login           TEXT    NOT NULL,
                contributions   INTEGER DEFAULT 0,
                rank            INTEGER DEFAULT 0,

                UNIQUE (repo_key, collected_at, login)
            );

            -- ----------------------------------------------------------------
            -- Indexes for common query patterns
            -- ----------------------------------------------------------------
            CREATE INDEX IF NOT EXISTS idx_snapshots_repo_key
                ON repo_snapshots (repo_key);

            CREATE INDEX IF NOT EXISTS idx_snapshots_collected_at
                ON repo_snapshots (collected_at);

            CREATE INDEX IF NOT EXISTS idx_releases_repo_key
                ON repo_releases (repo_key);

            CREATE INDEX IF NOT EXISTS idx_releases_published_at
                ON repo_releases (published_at);

            CREATE INDEX IF NOT EXISTS idx_contributors_repo_key
                ON repo_contributors (repo_key);
        """)
    print(f"[database] Initialized at {DB_PATH}")


if __name__ == "__main__":
    init_db()
