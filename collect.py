"""
OpenPulse AI — Data Collection Entry Point

Collects metrics for all tracked repositories and persists them to SQLite.
Run this manually or schedule it daily via cron / Task Scheduler.

Usage:
    python collect.py                  # collect all repos
    python collect.py --repo langgraph # collect one repo by display name
    python collect.py --dry-run        # collect but do not write to DB
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from utils.logger import setup_logging
setup_logging()

from config import TRACKED_REPOS
from collector.github_client import GitHubClient
from collector.metrics_collector import MetricsCollector
from collector.snapshot_writer import SnapshotWriter
from database.schema import init_db, get_connection, managed_connection
from analytics.health_score import compute_health_score
from analytics.risk_detector import detect_risks
from ai.insight_generator import generate_repo_insight, generate_ecosystem_insight

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenPulse AI — collect GitHub metrics for tracked repositories"
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Collect only this repo (match by display_name, e.g. 'LangGraph')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect metrics but do not write to the database",
    )
    return parser.parse_args()


def run(repos: list[dict], dry_run: bool = False) -> None:
    init_db()

    client    = GitHubClient()
    collector = MetricsCollector(client)
    writer    = SnapshotWriter()

    total     = len(repos)
    succeeded = 0
    failed    = 0

    log.info(f"Starting collection run | repos={total} | dry_run={dry_run}")
    run_start = time.time()

    for i, repo_cfg in enumerate(repos, start=1):
        owner        = repo_cfg["owner"]
        repo         = repo_cfg["repo"]
        display_name = repo_cfg["display_name"]

        log.info(f"[{i}/{total}] {display_name} ({owner}/{repo})")
        repo_start = time.time()

        try:
            payload = collector.collect(owner, repo, display_name)

            if dry_run:
                log.info(f"  dry-run: skipping DB write for {display_name}")
            else:
                writer.write(payload)

            elapsed = time.time() - repo_start
            log.info(f"  done in {elapsed:.1f}s")
            succeeded += 1

        except Exception as exc:
            log.error(f"  FAILED {display_name}: {exc}", exc_info=True)
            failed += 1

    total_elapsed = time.time() - run_start
    log.info(
        f"Collection run complete | "
        f"succeeded={succeeded} | failed={failed} | "
        f"total_time={total_elapsed:.1f}s"
    )

    if failed > 0:
        sys.exit(1)

    if not dry_run and succeeded > 0:
        _generate_and_store_insights()


def _generate_and_store_insights() -> None:
    """Generate AI insights from latest snapshots and persist to DB."""
    log.info("Generating AI insights...")
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.* FROM repo_snapshots s
           INNER JOIN (
               SELECT repo_key, MAX(collected_at) AS max_date
               FROM repo_snapshots GROUP BY repo_key
           ) latest ON s.repo_key = latest.repo_key
                    AND s.collected_at = latest.max_date"""
    ).fetchall()
    conn.close()

    if not rows:
        log.warning("No snapshots found — skipping insight generation.")
        return

    snapshots = []
    all_alerts = {}
    for row in rows:
        s = dict(row)
        s.update(compute_health_score(s))
        all_alerts[s["repo_key"]] = detect_risks(s)
        snapshots.append(s)

    collected_at = snapshots[0].get("collected_at", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    with managed_connection() as conn:
        eco_insight = generate_ecosystem_insight(snapshots, all_alerts)
        conn.execute(
            "INSERT OR REPLACE INTO ai_insights (scope, repo_key, collected_at, insight_text) "
            "VALUES (?, ?, ?, ?)",
            ("ecosystem", None, collected_at, eco_insight),
        )
        log.info("  ecosystem insight stored")

        for s in snapshots:
            alerts = all_alerts.get(s["repo_key"], [])
            repo_insight = generate_repo_insight(s, alerts)
            conn.execute(
                "INSERT OR REPLACE INTO ai_insights (scope, repo_key, collected_at, insight_text) "
                "VALUES (?, ?, ?, ?)",
                ("repo", s["repo_key"], collected_at, repo_insight),
            )
            log.info(f"  {s['display_name']} insight stored")

    log.info(f"AI insights stored for {collected_at}")


if __name__ == "__main__":
    args = parse_args()

    repos_to_collect = TRACKED_REPOS

    if args.repo:
        repos_to_collect = [
            r for r in TRACKED_REPOS
            if r["display_name"].lower() == args.repo.lower()
        ]
        if not repos_to_collect:
            log.error(
                f"No repo found with display_name '{args.repo}'. "
                f"Valid names: {[r['display_name'] for r in TRACKED_REPOS]}"
            )
            sys.exit(1)

    run(repos_to_collect, dry_run=args.dry_run)
