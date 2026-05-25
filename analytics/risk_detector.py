"""
Risk Detector for OpenPulse AI.

Analyses a repo snapshot and returns a list of risk alerts.
Each alert has a severity (critical / warning / info), a short title,
and a human-readable description with cited metric values.

Uses thresholds from config.RISK_THRESHOLDS.
"""

import logging
from dataclasses import dataclass, asdict

from config import RISK_THRESHOLDS

logger = logging.getLogger(__name__)


@dataclass
class RiskAlert:
    severity: str       # "critical" | "warning" | "info"
    title: str
    description: str
    metric_key: str     # DB column that triggered this alert
    metric_value: float


def detect_risks(snapshot: dict) -> list[dict]:
    """
    Run all risk checks against a snapshot.
    Returns a list of alert dicts (serialisable for DB / dashboard).
    """
    alerts: list[RiskAlert] = []
    name = snapshot.get("display_name", snapshot.get("repo_key", "unknown"))

    # -- 1. Low health score
    health = snapshot.get("health_score", 0)
    threshold = RISK_THRESHOLDS["low_health_score"]
    if health < 60:
        alerts.append(RiskAlert(
            severity="critical",
            title="Health score critically low",
            description=f"{name} health score is {health:.1f}/100 — well below the {threshold} threshold.",
            metric_key="health_score",
            metric_value=health,
        ))
    elif health < threshold:
        alerts.append(RiskAlert(
            severity="warning",
            title="Health score below threshold",
            description=f"{name} health score is {health:.1f}/100 (threshold: {threshold}).",
            metric_key="health_score",
            metric_value=health,
        ))

    # -- 2. Stale issues
    stale = snapshot.get("stale_issues_count", 0)
    if stale > 200:
        alerts.append(RiskAlert(
            severity="critical",
            title="Massive stale issue backlog",
            description=f"{name} has {stale} issues untouched for 90+ days.",
            metric_key="stale_issues_count",
            metric_value=stale,
        ))
    elif stale > 50:
        alerts.append(RiskAlert(
            severity="warning",
            title="Growing stale issue backlog",
            description=f"{name} has {stale} stale issues (>90 days without update).",
            metric_key="stale_issues_count",
            metric_value=stale,
        ))

    # -- 3. No recent commits
    commits_30d = snapshot.get("commits_30d", 0)
    if commits_30d == 0:
        alerts.append(RiskAlert(
            severity="critical",
            title="No commits in 30 days",
            description=f"{name} had zero commits in the last 30 days — maintenance activity appears reduced in the selected 30-day window.",
            metric_key="commits_30d",
            metric_value=commits_30d,
        ))
    elif commits_30d < 10:
        alerts.append(RiskAlert(
            severity="warning",
            title="Low commit activity",
            description=f"{name} had only {commits_30d} commits in the last 30 days.",
            metric_key="commits_30d",
            metric_value=commits_30d,
        ))

    # -- 4. No recent releases
    releases_30d = snapshot.get("releases_30d", 0)
    days_since = snapshot.get("days_since_last_release", 999)
    if days_since > 180:
        alerts.append(RiskAlert(
            severity="critical",
            title="No release in 6+ months",
            description=f"{name} last released {days_since} days ago.",
            metric_key="days_since_last_release",
            metric_value=days_since,
        ))
    elif releases_30d == 0 and days_since > 60:
        alerts.append(RiskAlert(
            severity="warning",
            title="Release cadence slowing",
            description=f"{name} has had no releases in 30 days (last release {days_since} days ago).",
            metric_key="releases_30d",
            metric_value=releases_30d,
        ))

    # -- 5. Slow issue resolution
    avg_close = snapshot.get("avg_issue_close_days", 0)
    if avg_close > 60:
        alerts.append(RiskAlert(
            severity="warning",
            title="Slow issue resolution",
            description=f"{name} average issue close time is {avg_close:.1f} days.",
            metric_key="avg_issue_close_days",
            metric_value=avg_close,
        ))

    # -- 6. No new contributors
    new_30d = snapshot.get("contributors_new_30d", 0)
    if new_30d == 0 and commits_30d > 0:
        alerts.append(RiskAlert(
            severity="info",
            title="No new contributors",
            description=f"{name} had {commits_30d} commits but 0 new contributors in 30 days — possible bus factor risk.",
            metric_key="contributors_new_30d",
            metric_value=new_30d,
        ))

    # -- 7. Dependency risks
    dep_risk = snapshot.get("dependency_risk_count", 0)
    if dep_risk >= 3:
        alerts.append(RiskAlert(
            severity="warning",
            title="Multiple dependency risks",
            description=f"{name} has {dep_risk} flagged dependency risks.",
            metric_key="dependency_risk_count",
            metric_value=dep_risk,
        ))

    # -- Positive signal (no alerts = healthy)
    if not alerts:
        alerts.append(RiskAlert(
            severity="info",
            title="No risks detected",
            description=f"{name} shows healthy metrics across all dimensions.",
            metric_key="health_score",
            metric_value=health,
        ))

    logger.info(
        f"[risk] {name} | "
        f"{sum(1 for a in alerts if a.severity == 'critical')} critical, "
        f"{sum(1 for a in alerts if a.severity == 'warning')} warning, "
        f"{sum(1 for a in alerts if a.severity == 'info')} info"
    )

    return [asdict(a) for a in alerts]
