"""
Demo data seeder for OpenPulse AI.

Generates 7 days of realistic synthetic snapshots so the dashboard
can be explored without a GitHub token or OpenAI key.

Usage:
    python demo_seed.py          # Seed 7 days of data
    python demo_seed.py --days 14  # Seed 14 days
    python demo_seed.py --reset  # Wipe DB first, then seed
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(__file__))

from database.schema import init_db, get_connection, managed_connection
from analytics.health_score import compute_health_score
from config import TRACKED_REPOS

# ---------------------------------------------------------------------------
# Realistic baseline profiles per repo (approximate real-world ranges)
# ---------------------------------------------------------------------------
PROFILES = {
    "langchain-ai/langgraph": {
        "stars": 12500, "forks": 2100, "watchers": 310,
        "open_issues": 280, "closed_issues_30d": 95, "avg_issue_close_days": 4.2,
        "stale_issues_count": 35, "contributors_total": 185, "contributors_new_30d": 12,
        "commits_30d": 120, "commits_90d": 340, "releases_30d": 3, "releases_90d": 8,
        "days_since_last_release": 5, "readme_length_chars": 18500,
        "has_changelog": 1, "has_pyproject": 1, "dependency_risk_count": 0,
    },
    "langchain-ai/langchain": {
        "stars": 98000, "forks": 15800, "watchers": 980,
        "open_issues": 620, "closed_issues_30d": 180, "avg_issue_close_days": 6.8,
        "stale_issues_count": 120, "contributors_total": 3200, "contributors_new_30d": 45,
        "commits_30d": 95, "commits_90d": 280, "releases_30d": 2, "releases_90d": 7,
        "days_since_last_release": 12, "readme_length_chars": 22000,
        "has_changelog": 1, "has_pyproject": 1, "dependency_risk_count": 1,
    },
    "run-llama/llama_index": {
        "stars": 38000, "forks": 5500, "watchers": 420,
        "open_issues": 350, "closed_issues_30d": 110, "avg_issue_close_days": 5.5,
        "stale_issues_count": 80, "contributors_total": 1100, "contributors_new_30d": 18,
        "commits_30d": 85, "commits_90d": 250, "releases_30d": 4, "releases_90d": 12,
        "days_since_last_release": 3, "readme_length_chars": 16000,
        "has_changelog": 1, "has_pyproject": 1, "dependency_risk_count": 0,
    },
    "crewAIInc/crewAI": {
        "stars": 25000, "forks": 3400, "watchers": 350,
        "open_issues": 180, "closed_issues_30d": 70, "avg_issue_close_days": 3.1,
        "stale_issues_count": 22, "contributors_total": 280, "contributors_new_30d": 25,
        "commits_30d": 140, "commits_90d": 380, "releases_30d": 5, "releases_90d": 14,
        "days_since_last_release": 2, "readme_length_chars": 14000,
        "has_changelog": 1, "has_pyproject": 1, "dependency_risk_count": 0,
    },
    "microsoft/autogen": {
        "stars": 35000, "forks": 5100, "watchers": 480,
        "open_issues": 520, "closed_issues_30d": 30, "avg_issue_close_days": 18.5,
        "stale_issues_count": 361, "contributors_total": 420, "contributors_new_30d": 3,
        "commits_30d": 8, "commits_90d": 45, "releases_30d": 0, "releases_90d": 1,
        "days_since_last_release": 95, "readme_length_chars": 12000,
        "has_changelog": 0, "has_pyproject": 1, "dependency_risk_count": 2,
    },
    "microsoft/semantic-kernel": {
        "stars": 22000, "forks": 3200, "watchers": 310,
        "open_issues": 210, "closed_issues_30d": 65, "avg_issue_close_days": 7.2,
        "stale_issues_count": 55, "contributors_total": 350, "contributors_new_30d": 8,
        "commits_30d": 60, "commits_90d": 170, "releases_30d": 2, "releases_90d": 6,
        "days_since_last_release": 18, "readme_length_chars": 15000,
        "has_changelog": 1, "has_pyproject": 0, "dependency_risk_count": 1,
    },
    "deepset-ai/haystack": {
        "stars": 18000, "forks": 1900, "watchers": 220,
        "open_issues": 150, "closed_issues_30d": 55, "avg_issue_close_days": 4.8,
        "stale_issues_count": 28, "contributors_total": 260, "contributors_new_30d": 10,
        "commits_30d": 75, "commits_90d": 210, "releases_30d": 2, "releases_90d": 7,
        "days_since_last_release": 8, "readme_length_chars": 13500,
        "has_changelog": 1, "has_pyproject": 1, "dependency_risk_count": 0,
    },
}


def _jitter(value, pct=0.08):
    """Add small random noise to a numeric value."""
    if isinstance(value, float):
        delta = value * random.uniform(-pct, pct)
        return round(max(0, value + delta), 2)
    elif isinstance(value, int):
        delta = int(value * random.uniform(-pct, pct))
        return max(0, value + delta)
    return value


def seed_demo_data(days: int = 7, reset: bool = False):
    """Insert synthetic snapshot data for `days` consecutive days."""
    if reset:
        db_path = os.getenv("DB_PATH", "data/openpulse.db")
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"[demo] Deleted existing database: {db_path}")

    init_db()

    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    with managed_connection() as conn:
        for day_offset in range(days - 1, -1, -1):
            date = today - timedelta(days=day_offset)
            collected_at = date.strftime("%Y-%m-%d")

            for repo_cfg in TRACKED_REPOS:
                repo_key = f"{repo_cfg['owner']}/{repo_cfg['repo']}"
                display_name = repo_cfg["display_name"]
                profile = PROFILES.get(repo_key)

                if not profile:
                    continue

                # Add day-over-day drift: stars grow, issues fluctuate, etc.
                snapshot = {}
                for key, base_val in profile.items():
                    if key == "stars":
                        snapshot[key] = base_val + (days - 1 - day_offset) * random.randint(20, 80)
                    elif key == "forks":
                        snapshot[key] = base_val + (days - 1 - day_offset) * random.randint(3, 15)
                    elif key == "contributors_total":
                        snapshot[key] = base_val + (days - 1 - day_offset) * random.randint(0, 2)
                    elif key == "days_since_last_release":
                        snapshot[key] = max(0, base_val + day_offset)
                    else:
                        snapshot[key] = _jitter(base_val)

                snapshot["repo_key"] = repo_key
                snapshot["display_name"] = display_name
                snapshot["collected_at"] = collected_at
                snapshot["last_release_date"] = (date - timedelta(days=snapshot["days_since_last_release"])).strftime("%Y-%m-%d")
                snapshot["dependency_risk_flags"] = json.dumps([])

                # Compute health scores and merge into snapshot
                scores = compute_health_score(snapshot)
                snapshot.update(scores)

                # Build column lists from snapshot dict
                columns = [k for k in snapshot.keys() if k != "id"]
                placeholders = ", ".join(f":{c}" for c in columns)
                col_names = ", ".join(columns)

                conn.execute(
                    f"INSERT OR REPLACE INTO repo_snapshots ({col_names}) VALUES ({placeholders})",
                    snapshot,
                )

            print(f"[demo] Seeded {collected_at} — {len(TRACKED_REPOS)} repos")

    print(f"\n[demo] Done! {days} days × {len(TRACKED_REPOS)} repos = {days * len(TRACKED_REPOS)} snapshots")
    print("[demo] Run: streamlit run dashboard/app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo data for OpenPulse AI")
    parser.add_argument("--days", type=int, default=7, help="Number of days to simulate (default: 7)")
    parser.add_argument("--reset", action="store_true", help="Delete existing DB before seeding")
    args = parser.parse_args()

    seed_demo_data(days=args.days, reset=args.reset)
