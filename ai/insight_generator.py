"""
AI Insight Generator for OpenPulse AI.

Uses OpenAI GPT-4o to produce data-cited summaries for:
  1. Per-repo analysis — strengths, risks, recommendations
  2. Ecosystem overview — cross-repo comparison and market narrative

Falls back to a structured template when OPENAI_API_KEY is not set,
so the dashboard works without an API key (demo mode).
"""

import os
import json
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def _build_repo_prompt(snapshot: dict, alerts: list[dict], rankings: dict) -> str:
    """Build the prompt for a single-repo insight."""
    name = snapshot.get("display_name", snapshot.get("repo_key"))
    return f"""You are an open-source ecosystem analyst. Analyse the following GitHub repository data and produce a concise, professional insight report.

## Repository: {name} ({snapshot.get('repo_key')})

### Metrics (latest snapshot)
- Stars: {snapshot.get('stars', 0):,}  |  Forks: {snapshot.get('forks', 0):,}
- Open issues: {snapshot.get('open_issues', 0):,}  |  Closed in 30d: {snapshot.get('closed_issues_30d', 0)}
- Avg issue close time: {snapshot.get('avg_issue_close_days', 0):.1f} days
- Stale issues (90d+): {snapshot.get('stale_issues_count', 0)}
- Commits (30d): {snapshot.get('commits_30d', 0)}  |  Commits (90d): {snapshot.get('commits_90d', 0)}
- Contributors: {snapshot.get('contributors_total', 0)}  |  New in 30d: {snapshot.get('contributors_new_30d', 0)}
- Releases (30d): {snapshot.get('releases_30d', 0)}  |  Releases (90d): {snapshot.get('releases_90d', 0)}
- Days since last release: {snapshot.get('days_since_last_release', 0)}
- README length: {snapshot.get('readme_length_chars', 0):,} chars
- Has pyproject.toml: {bool(snapshot.get('has_pyproject', 0))}
- Has CHANGELOG: {bool(snapshot.get('has_changelog', 0))}

### Health Score: {snapshot.get('health_score', 0):.1f}/100
- Release Velocity: {snapshot.get('release_velocity_score', 0):.1f}
- Issue Resolution: {snapshot.get('issue_resolution_score', 0):.1f}
- Contributor Activity: {snapshot.get('contributor_activity_score', 0):.1f}
- Docs Freshness: {snapshot.get('docs_freshness_score', 0):.1f}
- Dependency Risk: {snapshot.get('dependency_risk_score', 0):.1f}

### Risk Alerts
{json.dumps(alerts, indent=2) if alerts else "No risks detected."}

### Instructions
Write a 3-paragraph analysis:
1. **Strengths** — what this repo does well, citing specific metrics
2. **Risks & Concerns** — problems or trends to watch, citing metrics
3. **Recommendations** — 2-3 actionable steps the maintainers should consider

Keep it under 200 words. Cite exact numbers. Use professional tone suitable for a portfolio report.
"""


def _build_ecosystem_prompt(all_snapshots: list[dict], all_alerts: dict) -> str:
    """Build the prompt for the ecosystem-wide overview."""
    summary_rows = []
    for s in all_snapshots:
        name = s.get("display_name", s.get("repo_key"))
        alert_count = len(all_alerts.get(s["repo_key"], []))
        summary_rows.append(
            f"- {name}: health={s.get('health_score', 0):.1f}, "
            f"stars={s.get('stars', 0):,}, "
            f"commits_30d={s.get('commits_30d', 0)}, "
            f"releases_30d={s.get('releases_30d', 0)}, "
            f"alerts={alert_count}"
        )

    return f"""You are an open-source ecosystem analyst. Below is a snapshot of 7 AI agent frameworks.

## Ecosystem Data
{chr(10).join(summary_rows)}

### Instructions
Write a 3-paragraph ecosystem overview:
1. **Market Leaders** — which repos are healthiest and why (cite numbers)
2. **At Risk** — which repos show concerning signals (cite numbers)
3. **Outlook** — overall ecosystem health and emerging patterns

Keep it under 200 words. Professional tone. Cite specific metrics.
"""


def _call_openai(prompt: str) -> str | None:
    """Call OpenAI API. Returns None on failure."""
    if not OPENAI_API_KEY:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a concise, data-driven open-source analyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning(f"[insight] OpenAI API error: {exc}")
        return None


def _fallback_repo_insight(snapshot: dict, alerts: list[dict]) -> str:
    """Template-based fallback when no API key is available."""
    name = snapshot.get("display_name", snapshot.get("repo_key"))
    health = snapshot.get("health_score", 0)

    strengths = []
    if snapshot.get("commits_30d", 0) > 50:
        strengths.append(f"strong commit velocity ({snapshot['commits_30d']} in 30d)")
    if snapshot.get("stars", 0) > 30000:
        strengths.append(f"high community traction ({snapshot['stars']:,} stars)")
    if snapshot.get("contributors_new_30d", 0) > 5:
        strengths.append(f"growing contributor base ({snapshot['contributors_new_30d']} new in 30d)")
    if not strengths:
        strengths.append("established project with active community")

    risks = [a["description"] for a in alerts if a["severity"] in ("critical", "warning")]
    if not risks:
        risks = ["No significant risks detected at this time."]

    return (
        f"**{name}** (Health: {health:.1f}/100) — "
        f"Strengths: {'; '.join(strengths)}. "
        f"Risks: {'; '.join(risks[:3])}. "
        f"Recommendation: Monitor key metrics and address any flagged concerns."
    )


def _fallback_ecosystem_insight(all_snapshots: list[dict]) -> str:
    """Template-based fallback for ecosystem overview."""
    sorted_repos = sorted(all_snapshots, key=lambda s: s.get("health_score", 0), reverse=True)
    top = sorted_repos[0]
    bottom = sorted_repos[-1]

    return (
        f"**Ecosystem Overview** — Analysing {len(all_snapshots)} AI agent frameworks. "
        f"**Market leader**: {top['display_name']} with a health score of {top['health_score']:.1f}/100, "
        f"{top.get('stars', 0):,} stars, and {top.get('commits_30d', 0)} commits in 30 days. "
        f"**At risk**: {bottom['display_name']} with a health score of {bottom['health_score']:.1f}/100. "
        f"The ecosystem shows diverse maturity levels — active frameworks maintain >100 monthly commits "
        f"while others show signs of reduced maintenance."
    )


def generate_repo_insight(snapshot: dict, alerts: list[dict], rankings: dict = None) -> str:
    """Generate insight for a single repo. Uses LLM if available, else falls back to template."""
    prompt = _build_repo_prompt(snapshot, alerts, rankings or {})
    result = _call_openai(prompt)

    if result:
        logger.info(f"[insight] {snapshot.get('display_name')} — LLM insight generated")
        return result

    logger.info(f"[insight] {snapshot.get('display_name')} — using fallback template (no API key)")
    return _fallback_repo_insight(snapshot, alerts)


def generate_ecosystem_insight(all_snapshots: list[dict], all_alerts: dict) -> str:
    """Generate ecosystem-wide overview. Uses LLM if available, else falls back to template."""
    prompt = _build_ecosystem_prompt(all_snapshots, all_alerts)
    result = _call_openai(prompt)

    if result:
        logger.info("[insight] Ecosystem overview — LLM insight generated")
        return result

    logger.info("[insight] Ecosystem overview — using fallback template (no API key)")
    return _fallback_ecosystem_insight(all_snapshots)
