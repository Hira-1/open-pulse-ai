# 🔬 OpenPulse AI — Open-Source Ecosystem Intelligence Platform

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://open-pulse-ai-32rykiqberpte7pgb22nhy.streamlit.app/)

An autonomous monitoring platform that tracks, scores, and analyses the health of leading AI agent frameworks using live GitHub data and AI-powered insights.

> **Track 7 AI frameworks. Score them objectively. Surface risks before they matter.**

**[→ Live Dashboard](https://open-pulse-ai-32rykiqberpte7pgb22nhy.streamlit.app/)**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        OpenPulse AI                             │
├─────────────┬──────────────┬──────────────┬────────────────────┤
│  Collector  │  Analytics   │  AI Layer    │   Dashboard        │
│             │              │              │                    │
│ GitHub REST ─→ Health Score ─→ GPT-4o     ─→ Streamlit App    │
│ GitHub GQL  ─→ Risk Alerts  ─→ Fallback   ─→ Interactive UI   │
│ Rate Limiter─→ Trend Engine ─→ Templates  ─→ Plotly Charts    │
└──────┬──────┴──────┬───────┴──────┬───────┴────────┬──────────┘
       │             │              │                │
       └─────────────┴──────────────┴────────────────┘
                          SQLite DB
                      (data/openpulse.db)
```

## Tracked Repositories

| Framework | GitHub Repo | Category |
|-----------|-------------|----------|
| LangGraph | `langchain-ai/langgraph` | Agent orchestration |
| LangChain | `langchain-ai/langchain` | LLM framework |
| LlamaIndex | `run-llama/llama_index` | RAG framework |
| CrewAI | `crewAIInc/crewAI` | Multi-agent platform |
| AutoGen | `microsoft/autogen` | Multi-agent framework |
| Semantic Kernel | `microsoft/semantic-kernel` | Enterprise AI SDK |
| Haystack | `deepset-ai/haystack` | NLP/RAG pipeline |

## Health Score Methodology

Each repository is scored **0–100** using a weighted composite of five dimensions:

```
Health Score =
  Release Velocity     × 25%
+ Issue Resolution     × 25%
+ Contributor Activity × 20%
+ Docs Freshness       × 15%
+ Dependency Risk      × 15%
```

| Sub-Score | What It Measures |
|-----------|------------------|
| **Release Velocity** | Release frequency and days since last release |
| **Issue Resolution** | Average close time and stale issue ratio (>90 days) |
| **Contributor Activity** | Commits, total contributors, and new contributors (30d) |
| **Docs Freshness** | README/docs update recency |
| **Dependency Risk** | Known vulnerabilities and outdated packages |

| Score Range | Status |
|-------------|--------|
| 90–100 | Strong |
| 80–89 | Stable |
| 70–79 | Growing / Risky |
| 60–69 | Moderate Risk |
| 0–59 | High Risk |

## Features

- **Automated Data Collection** — GitHub REST + GraphQL API with retry logic and rate-limit handling
- **Composite Health Scoring** — Weighted multi-dimensional scoring with configurable weights
- **Risk Detection** — Evidence-based alerts with severity levels and metric citations
- **Trend Analysis** — Delta tracking and cross-repo rankings across snapshots
- **AI Insights** — GPT-4o powered analysis with template fallback (works without API key)
- **Interactive Dashboard** — Streamlit app with Plotly charts, leaderboard, radar comparisons, and deep dives
- **Actionable Recommendations** — Dynamic advice based on health tiers
- **Historical Trends** — Multi-day line charts for health, stars, issues, and commits
- **What-If Simulator** — Interactive weight sliders that recalculate all scores and rankings in real time

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/yourusername/openpulse-ai.git
cd openpulse-ai
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Try it instantly (Demo Mode)

No API keys needed — seeds 7 days of realistic synthetic data:

```bash
python demo_seed.py --reset
streamlit run dashboard/app.py
```

### 3. Use with live GitHub data

```bash
cp .env.example .env
# Edit .env → add your GITHUB_TOKEN (and optionally OPENAI_API_KEY)
python collect.py
streamlit run dashboard/app.py
```

### 4. Build historical trends

Run the collector daily (or via cron) to accumulate snapshots:

```bash
# Manual
python collect.py

# Cron (Linux/Mac) — every day at 6 AM
0 6 * * * cd /path/to/openpulse-ai && python collect.py
```

## Project Structure

```
openpulse-ai/
├── ai/
│   └── insight_generator.py    # GPT-4o insights + template fallback
├── analytics/
│   ├── health_score.py         # Composite health scorer
│   ├── risk_detector.py        # Evidence-based risk alerts
│   └── trend_engine.py         # Delta computation & rankings
├── collector/
│   ├── github_client.py        # GitHub API wrapper (REST + GraphQL)
│   ├── metrics_collector.py    # Raw metric extraction
│   └── snapshot_writer.py      # SQLite persistence
├── dashboard/
│   └── app.py                  # Streamlit dashboard (all sections)
├── database/
│   └── schema.py               # SQLite schema & connection management
├── tests/                      # Smoke tests for each component
├── config.py                   # Tracked repos, weights, thresholds
├── collect.py                  # CLI entry point for data collection
├── demo_seed.py                # Demo data generator (no API keys needed)
├── requirements.txt            # Pinned dependencies
├── .env.example                # Environment variable template
└── .gitignore
```

## Configuration

All scoring weights and thresholds are in `config.py`:

```python
SCORE_WEIGHTS = {
    "release_velocity":     0.25,
    "issue_resolution":     0.25,
    "contributor_activity": 0.20,
    "docs_freshness":       0.15,
    "dependency_risk":      0.15,
}
```

To track different repos, edit `TRACKED_REPOS` in `config.py`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | For live data | GitHub Personal Access Token (public_repo scope) |
| `OPENAI_API_KEY` | No | Enables GPT-4o insights (falls back to templates) |
| `OPENAI_MODEL` | No | Model name (default: `gpt-4o-mini`) |
| `DB_PATH` | No | SQLite path (default: `data/openpulse.db`) |

## Data Limitations

Scores are based on public GitHub activity and package metadata. They should be interpreted as **operational signals**, not final adoption recommendations. Some projects may use multiple repositories, private development, or external release channels not fully captured here.

## Tech Stack

- **Python 3.12+**
- **Streamlit** — Interactive dashboard
- **Plotly** — Charts and visualizations
- **SQLite** — Local data persistence
- **PyGithub + httpx** — GitHub API access
- **OpenAI SDK** — AI insight generation
- **Tenacity** — Retry logic with exponential backoff

## License

MIT

---

*Built by Hira Naz — Autonomous Open-Source Ecosystem Intelligence*
