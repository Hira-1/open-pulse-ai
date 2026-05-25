"""
Central configuration for OpenPulse AI.
Edit TRACKED_REPOS to add or remove repositories.
Edit SCORE_WEIGHTS to adjust the health score formula.
"""

TRACKED_REPOS = [
    {"owner": "langchain-ai", "repo": "langgraph",         "display_name": "LangGraph"},
    {"owner": "langchain-ai", "repo": "langchain",         "display_name": "LangChain"},
    {"owner": "run-llama",    "repo": "llama_index",       "display_name": "LlamaIndex"},
    {"owner": "crewAIInc",   "repo": "crewAI",            "display_name": "CrewAI"},
    {"owner": "microsoft",   "repo": "autogen",            "display_name": "AutoGen"},
    {"owner": "microsoft",   "repo": "semantic-kernel",    "display_name": "Semantic Kernel"},
    {"owner": "deepset-ai",  "repo": "haystack",           "display_name": "Haystack"},
]

SCORE_WEIGHTS = {
    "release_velocity":      0.25,
    "issue_resolution":      0.25,
    "contributor_activity":  0.20,
    "docs_freshness":        0.15,
    "dependency_risk":       0.15,
}

RISK_THRESHOLDS = {
    "low_health_score":          75,
    "issue_backlog_growth_pct":  15,
    "stale_issue_days":          90,
    "dependency_stale_months":   18,
}

ANALYSIS_WINDOW_DAYS = 30

STATUS_LABELS = {
    (90, 101): ("Strong",          "#22c55e"),
    (80,  90): ("Stable",          "#84cc16"),
    (70,  80): ("Growing / Risky", "#f59e0b"),
    (60,  70): ("Moderate Risk",   "#f97316"),
    (0,   60): ("High Risk",       "#ef4444"),
}

def get_status(score: float) -> tuple[str, str]:
    """Return (label, hex_color) for a given health score."""
    for (low, high), result in STATUS_LABELS.items():
        if low <= score < high:
            return result
    return ("Unknown", "#6b7280")
