"""
OpenPulse AI — Streamlit Dashboard

Launch with:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work when Streamlit
# runs this file from any working directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from database.schema import get_connection, init_db
from analytics.health_score import compute_health_score
from analytics.risk_detector import detect_risks
from analytics.trend_engine import compute_trends, compute_rankings
from ai.insight_generator import generate_repo_insight, generate_ecosystem_insight
from config import TRACKED_REPOS, SCORE_WEIGHTS, RISK_THRESHOLDS, get_status
from datetime import datetime
from fpdf import FPDF

# ── Page Config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="OpenPulse AI — Ecosystem Intelligence",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Remove top dead space */
    .stApp > header { display: none !important; }
    .stApp { margin-top: -3rem; }
    .main .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem;
        max-width: 1200px;
    }
    div[data-testid="stDecoration"] { display: none !important; }
    div[data-testid="stToolbar"] { display: none !important; }
    footer { display: none !important; }

    /* KPI metric cards */
    div[data-testid="stMetric"] {
        background: #1a1d24;
        border: 1px solid #2d3340;
        border-radius: 10px;
        padding: 14px 18px;
    }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; color: #f8fafc; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; text-transform: uppercase;
                                        letter-spacing: 0.03em; color: #94a3b8; }

    /* Health badge */
    .health-badge { display: inline-block; padding: 4px 14px; border-radius: 14px;
                    font-weight: 600; font-size: 0.85rem; color: #fff; vertical-align: middle; }

    /* Alert cards */
    .alert-critical { border-left: 4px solid #ef4444; background: rgba(239,68,68,0.12);
                      padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; }
    .alert-warning  { border-left: 4px solid #f59e0b; background: rgba(245,158,11,0.12);
                      padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; }
    .alert-info     { border-left: 4px solid #22c55e; background: rgba(34,197,94,0.12);
                      padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; }

    /* Tighten section gaps */
    .stMarkdown hr { margin-top: 0.6rem; margin-bottom: 0.6rem; border-color: #2d3340; }
</style>
""", unsafe_allow_html=True)


# ── Data Loading (cached) ────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data():
    """Load all snapshots, compute scores, risks, trends, and rankings."""
    init_db()
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.* FROM repo_snapshots s
           INNER JOIN (
               SELECT repo_key, MAX(collected_at) AS max_date
               FROM repo_snapshots GROUP BY repo_key
           ) latest ON s.repo_key = latest.repo_key
                    AND s.collected_at = latest.max_date
           ORDER BY s.health_score DESC"""
    ).fetchall()
    conn.close()

    if not rows:
        return None, None, None, None

    snapshots = []
    all_alerts = {}

    for row in rows:
        s = dict(row)
        # Recompute scores to stay fresh
        scores = compute_health_score(s)
        s.update(scores)
        alerts = detect_risks(s)
        all_alerts[s["repo_key"]] = alerts
        snapshots.append(s)

    snapshots.sort(key=lambda x: x["health_score"], reverse=True)
    rankings = compute_rankings()
    trends = {
        s["repo_key"]: compute_trends(s["repo_key"]) for s in snapshots
    }

    return snapshots, all_alerts, rankings, trends


# ── Load Data ────────────────────────────────────────────────────────
snapshots, all_alerts, rankings, trends = load_data()

if not snapshots:
    st.error("No data found. Run `python collect.py` first to collect repository data.")
    st.stop()


# ══════════════════════════════════════════════════════════════════════
# SECTION 1: Header
# ══════════════════════════════════════════════════════════════════════
# ── Pre-compute KPIs (used by header + PDF + cards) ──────────────────
avg_health = sum(s["health_score"] for s in snapshots) / len(snapshots)
total_stars = sum(s.get("stars", 0) for s in snapshots)
total_alerts = sum(
    len([a for a in all_alerts.get(s["repo_key"], []) if a["severity"] in ("critical", "warning")])
    for s in snapshots
)

_hdr_left, _hdr_right = st.columns([4, 1])
with _hdr_left:
    st.markdown(
        "<h1 style='margin-bottom:0;'>🔬 OpenPulse AI</h1>"
        "<p style='margin-top:0; opacity:0.65; font-size:1rem;'>"
        "Autonomous Open-Source Ecosystem Intelligence Platform</p>",
        unsafe_allow_html=True,
    )


# ── PDF Report Generator ────────────────────────────────────────────
def _pdf_safe(text):
    """Strip non-latin1 characters for Helvetica compatibility."""
    return text.encode("latin-1", errors="replace").decode("latin-1")

# Color constants for PDF (muted professional palette)
_C_BLACK = (33, 37, 41)
_C_DARK = (52, 58, 64)
_C_GRAY = (108, 117, 125)
_C_LIGHT = (233, 236, 239)
_C_ACCENT = (30, 58, 95)     # navy
_C_GREEN = (25, 135, 84)
_C_RED = (176, 42, 55)
_C_AMBER = (173, 107, 16)
_C_WHITE = (255, 255, 255)
_C_HDR_BG = (241, 243, 245)  # neutral light gray

def generate_pdf_report():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    LM = pdf.l_margin

    def _page_header(pdf, title=""):
        """Slim header bar on every page."""
        pdf.set_fill_color(*_C_HDR_BG)
        pdf.rect(0, 0, 210, 14, "F")
        pdf.set_fill_color(*_C_ACCENT)
        pdf.rect(0, 14, 210, 0.5, "F")
        pdf.set_xy(LM, 3)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(0, 4, "OpenPulse AI  -  Ecosystem Intelligence Report", align="L")
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*_C_GRAY)
        pdf.cell(0, 4, datetime.now().strftime("%Y-%m-%d"), new_x="LMARGIN", new_y="NEXT", align="R")
        if title:
            pdf.set_xy(LM, 17)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*_C_BLACK)
            pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        else:
            pdf.set_y(17)

    def _section(pdf, title):
        pdf.ln(3)
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*_C_ACCENT)
        pdf.line(LM, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)

    def _check_page(pdf, need=50):
        if pdf.get_y() > 297 - 15 - need:
            pdf.add_page()
            _page_header(pdf)

    # ── PAGE 1: Cover ──────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*_C_ACCENT)
    pdf.rect(0, 0, 210, 70, "F")
    pdf.set_text_color(*_C_WHITE)
    pdf.set_font("Helvetica", "B", 28)
    pdf.ln(18)
    pdf.cell(0, 12, "OpenPulse AI", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 7, "Ecosystem Intelligence Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    collected = str(snapshots[0].get("collected_at", "N/A"))[:16]
    pdf.cell(0, 5, _pdf_safe(f"Generated {datetime.now().strftime('%B %d, %Y')}  |  Data collected: {collected}"), new_x="LMARGIN", new_y="NEXT", align="C")

    # KPI summary boxes
    pdf.set_y(80)
    kpi_w = 44
    kpi_gap = 3
    kpi_start = (210 - 4 * kpi_w - 3 * kpi_gap) / 2
    kpis = [
        ("Repos Tracked", str(len(snapshots))),
        ("Avg Health", f"{avg_health:.1f}/100"),
        ("Total Stars", f"{total_stars:,}"),
        ("Active Alerts", str(total_alerts)),
    ]
    for idx, (kpi_label, kpi_val) in enumerate(kpis):
        x = kpi_start + idx * (kpi_w + kpi_gap)
        pdf.set_fill_color(*_C_HDR_BG)
        pdf.rect(x, 80, kpi_w, 22, "DF")
        pdf.set_xy(x, 82)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(kpi_w, 8, kpi_val, align="C")
        pdf.set_xy(x, 92)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*_C_GRAY)
        pdf.cell(kpi_w, 5, kpi_label, align="C")

    # Best / worst summary
    pdf.set_y(110)
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_C_DARK)
    best_s = snapshots[0]
    worst_s = snapshots[-1]
    pdf.multi_cell(0, 5, _pdf_safe(
        f"This report tracks {len(snapshots)} leading AI agent frameworks via GitHub API metrics. "
        f"The highest-scoring project is {best_s['display_name']} ({best_s['health_score']:.1f}/100), "
        f"while {worst_s['display_name']} ({worst_s['health_score']:.1f}/100) requires the most attention. "
        f"A total of {total_alerts} risk alert(s) were detected across the ecosystem."
    ))

    # ── PAGE 2: Leaderboard ────────────────────────────────────────
    pdf.add_page()
    _page_header(pdf, "Ecosystem Leaderboard")

    col_w = [10, 38, 20, 26, 22, 22, 22, 22]
    headers = ["#", "Repository", "Health", "Status", "Stars", "Commits", "Issues", "Releases"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*_C_ACCENT)
    pdf.set_text_color(*_C_WHITE)
    for w, h in zip(col_w, headers):
        pdf.cell(w, 7, h, border=0, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for i, s in enumerate(snapshots, 1):
        label, _ = get_status(s["health_score"])
        pdf.set_text_color(*_C_BLACK)
        if i % 2 == 0:
            pdf.set_fill_color(*_C_HDR_BG)
        else:
            pdf.set_fill_color(*_C_WHITE)
        row = [str(i), s["display_name"], f"{s['health_score']:.1f}", label,
               f"{s.get('stars', 0):,}", str(s.get("commits_30d", 0)),
               str(s.get("open_issues", 0)), str(s.get("releases_30d", 0))]
        for w, val in zip(col_w, row):
            pdf.cell(w, 6, _pdf_safe(val), border=0, fill=True, align="C")
        pdf.ln()

    # Ranking footnote
    pdf.ln(2)
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_C_GRAY)
    pdf.cell(0, 4, "Ranked by composite health score (highest first).", new_x="LMARGIN", new_y="NEXT")

    # ── Sub-score comparison table
    _section(pdf, "Sub-Score Breakdown")
    sub_headers = ["Repository", "RV", "IR", "CA", "DF", "DR"]
    sub_w = [48, 26, 26, 26, 26, 26]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*_C_ACCENT)
    pdf.set_text_color(*_C_WHITE)
    for w, h in zip(sub_w, sub_headers):
        pdf.cell(w, 7, h, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for i, s in enumerate(snapshots, 1):
        pdf.set_text_color(*_C_BLACK)
        if i % 2 == 0:
            pdf.set_fill_color(*_C_HDR_BG)
        else:
            pdf.set_fill_color(*_C_WHITE)
        row = [
            s["display_name"],
            f"{s.get('release_velocity_score', 0):.0f}",
            f"{s.get('issue_resolution_score', 0):.0f}",
            f"{s.get('contributor_activity_score', 0):.0f}",
            f"{s.get('docs_freshness_score', 0):.0f}",
            f"{s.get('dependency_risk_score', 0):.0f}",
        ]
        for w, val in zip(sub_w, row):
            pdf.cell(w, 6, _pdf_safe(val), fill=True, align="C")
        pdf.ln()
    pdf.ln(1)
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_C_GRAY)
    pdf.cell(0, 4, "RV=Release Velocity  IR=Issue Resolution  CA=Contributor Activity  DF=Docs Freshness  DR=Dependency Risk", new_x="LMARGIN", new_y="NEXT")

    # ── Repository Detail Pages (2 repos per page) ─────────────────
    # Each repo block ~ 95pt; A4 content area ~250pt → fits 2 comfortably
    COL_GAP = 5       # gap between left/right metric columns
    MC_W = 45         # metric name width per column
    MV_W = 25         # metric value width per column
    HALF = MC_W + MV_W + COL_GAP  # half-page column stride

    pdf.add_page()
    _page_header(pdf, "Repository Details")

    for repo_idx, s in enumerate(snapshots):
        # Need ~90pt; add new page if insufficient
        _check_page(pdf, 90)
        label, _ = get_status(s["health_score"])
        repo_alerts = all_alerts.get(s["repo_key"], [])
        parts = s.get("repo_key", "/").split("/")
        gh_url = f"https://github.com/{parts[0]}/{parts[1]}" if len(parts) > 1 else ""

        # Thin separator line between repos
        if repo_idx > 0:
            pdf.set_draw_color(*_C_LIGHT)
            pdf.line(LM, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)

        # Repo name + score on one line
        score = s["health_score"]
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_C_BLACK)
        pdf.cell(70, 6, _pdf_safe(s["display_name"]))
        if score >= 80:
            pdf.set_text_color(*_C_GREEN)
        elif score >= 50:
            pdf.set_text_color(*_C_AMBER)
        else:
            pdf.set_text_color(*_C_RED)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(18, 6, f"{score:.1f}")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_C_GRAY)
        pdf.cell(0, 6, _pdf_safe(f"/ 100  ({label})   {gh_url}"), new_x="LMARGIN", new_y="NEXT")

        # ── 2-column metrics layout ──────────────────────────────
        metrics_data = [
            ("Stars",               f"{s.get('stars', 0):,}"),
            ("Forks",               f"{s.get('forks', 0):,}"),
            ("Open Issues",         str(s.get("open_issues", 0))),
            ("Commits (30d)",       str(s.get("commits_30d", 0))),
            ("Contributors",        str(s.get("contributors_total", 0))),
            ("New Contrib. (30d)",  str(s.get("contributors_new_30d", 0))),
            ("Releases (30d)",      str(s.get("releases_30d", 0))),
            ("Days Since Release",  str(s.get("days_since_last_release", 0))),
            ("Avg Close (days)",    f"{s.get('avg_issue_close_days', 0):.1f}"),
            ("Stale Issues",        str(s.get("stale_issues_count", 0))),
        ]
        left_col  = metrics_data[:5]
        right_col = metrics_data[5:]

        # Column headers
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(*_C_ACCENT)
        pdf.set_text_color(*_C_WHITE)
        pdf.set_x(LM)
        pdf.cell(MC_W, 5, "Metric", fill=True)
        pdf.cell(MV_W, 5, "Value", fill=True, align="C")
        pdf.set_x(LM + HALF + COL_GAP)
        pdf.cell(MC_W, 5, "Metric", fill=True)
        pdf.cell(MV_W, 5, "Value", fill=True, align="C")
        pdf.ln()

        # Rows side by side
        pdf.set_font("Helvetica", "", 7)
        for row_i in range(max(len(left_col), len(right_col))):
            pdf.set_text_color(*_C_BLACK)
            fill_c = _C_HDR_BG if row_i % 2 == 0 else _C_WHITE
            pdf.set_fill_color(*fill_c)
            pdf.set_x(LM)
            if row_i < len(left_col):
                pdf.cell(MC_W, 4.5, left_col[row_i][0], fill=True)
                pdf.cell(MV_W, 4.5, _pdf_safe(left_col[row_i][1]), fill=True, align="C")
            else:
                pdf.cell(MC_W + MV_W, 4.5, "", fill=True)
            pdf.set_x(LM + HALF + COL_GAP)
            if row_i < len(right_col):
                pdf.cell(MC_W, 4.5, right_col[row_i][0], fill=True)
                pdf.cell(MV_W, 4.5, _pdf_safe(right_col[row_i][1]), fill=True, align="C")
            pdf.ln()

        # ── Sub-scores (horizontal bar row) ─────────────────────
        pdf.ln(1)
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(0, 4, "Sub-Scores", new_x="LMARGIN", new_y="NEXT")
        sub_items = [
            ("Release Vel.", s.get("release_velocity_score", 0), SCORE_WEIGHTS["release_velocity"]),
            ("Issue Res.",   s.get("issue_resolution_score", 0), SCORE_WEIGHTS["issue_resolution"]),
            ("Contrib. Act.",s.get("contributor_activity_score", 0), SCORE_WEIGHTS["contributor_activity"]),
            ("Docs Fresh.",  s.get("docs_freshness_score", 0), SCORE_WEIGHTS["docs_freshness"]),
            ("Dep. Risk",    s.get("dependency_risk_score", 0), SCORE_WEIGHTS["dependency_risk"]),
        ]
        pdf.set_font("Helvetica", "", 7)
        # Render 5 sub-scores in a single horizontal row
        sub_col_w = 38  # total width per sub-score slot
        pdf.set_x(LM)
        for sname, sval, sweight in sub_items:
            cx = pdf.get_x()
            cy = pdf.get_y()
            pdf.set_text_color(*_C_DARK)
            pdf.cell(sub_col_w, 4, _pdf_safe(f"{sname} ({int(sweight*100)}%)"))
        pdf.ln()
        pdf.set_x(LM)
        for sname, sval, sweight in sub_items:
            cx = pdf.get_x()
            cy = pdf.get_y()
            # Bar background
            pdf.set_fill_color(*_C_LIGHT)
            pdf.rect(cx, cy + 0.5, sub_col_w - 2, 2.5, "F")
            # Bar fill
            if sval >= 80:
                pdf.set_fill_color(*_C_GREEN)
            elif sval >= 50:
                pdf.set_fill_color(*_C_AMBER)
            else:
                pdf.set_fill_color(*_C_RED)
            pdf.rect(cx, cy + 0.5, max(0.5, (sval / 100) * (sub_col_w - 2)), 2.5, "F")
            pdf.set_text_color(*_C_BLACK)
            pdf.set_x(cx)
            pdf.cell(sub_col_w, 4, f"{sval:.0f}", align="R")
        pdf.ln()

        # ── Alerts (compact inline) ──────────────────────────────
        if repo_alerts:
            pdf.ln(1)
            pdf.set_x(LM)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*_C_RED)
            pdf.cell(0, 4, f"Alerts ({len(repo_alerts)}):", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 6.5)
            for a in repo_alerts:
                _check_page(pdf, 10)
                pdf.set_x(LM + 2)
                if a["severity"] == "critical":
                    pdf.set_text_color(*_C_RED)
                    prefix = "CRITICAL"
                elif a["severity"] == "warning":
                    pdf.set_text_color(*_C_AMBER)
                    prefix = "WARNING"
                else:
                    pdf.set_text_color(*_C_GRAY)
                    prefix = "INFO"
                pdf.multi_cell(0, 3.2, _pdf_safe(f"[{prefix}] {a['title']}: {a['description']}"))

    # ── METHODOLOGY PAGE ───────────────────────────────────────────
    pdf.add_page()
    _page_header(pdf, "Scoring Methodology")

    pdf.set_x(LM)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_C_DARK)
    pdf.multi_cell(0, 6, _pdf_safe(
        "Each repository receives a composite Health Score (0-100) calculated as a weighted sum of "
        "five sub-dimensions. Each sub-score is individually normalized to 0-100 before weighting."
    ))

    pdf.ln(2)
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_C_BLACK)
    pdf.cell(0, 5, "Formula:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(LM + 3)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_C_DARK)
    pdf.multi_cell(0, 5, _pdf_safe(
        f"Health = RV x {int(SCORE_WEIGHTS['release_velocity']*100)}% + "
        f"IR x {int(SCORE_WEIGHTS['issue_resolution']*100)}% + "
        f"CA x {int(SCORE_WEIGHTS['contributor_activity']*100)}% + "
        f"DF x {int(SCORE_WEIGHTS['docs_freshness']*100)}% + "
        f"DR x {int(SCORE_WEIGHTS['dependency_risk']*100)}%"
    ))

    pdf.ln(2)
    definitions = [
        ("Release Velocity (RV)", "Measures release frequency and recency. Higher scores for frequent, recent releases."),
        ("Issue Resolution (IR)", "Evaluates average issue close time and the proportion of stale issues (>90 days)."),
        ("Contributor Activity (CA)", "Assesses commit volume, total contributor base, and new contributor onboarding."),
        ("Docs Freshness (DF)", "Tracks how recently README and documentation files were updated."),
        ("Dependency Risk (DR)", "Flags known vulnerabilities, outdated packages, and supply chain concerns."),
    ]
    for dname, ddesc in definitions:
        _check_page(pdf, 15)
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(0, 5, dname, new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(LM + 3)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_C_DARK)
        pdf.multi_cell(0, 4, ddesc)
        pdf.ln(1)

    # Status tiers
    _section(pdf, "Health Status Tiers")
    tiers = [
        ("Excellent (80-100)", "Strong across all dimensions. Safe for production adoption.", _C_GREEN),
        ("Good (60-79)", "Stable with minor concerns. Monitor specific sub-scores.", _C_ACCENT),
        ("At Risk (40-59)", "Multiple weak dimensions. Evaluate before adopting.", _C_AMBER),
        ("Critical (<40)", "Significant gaps. Avoid for new projects without mitigation.", _C_RED),
    ]
    for tname, tdesc, tcolor in tiers:
        pdf.set_x(LM)
        pdf.set_fill_color(*tcolor)
        pdf.rect(LM, pdf.get_y() + 1, 3, 4, "F")
        pdf.set_x(LM + 5)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_C_BLACK)
        pdf.cell(40, 6, tname)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_C_DARK)
        pdf.cell(0, 6, tdesc, new_x="LMARGIN", new_y="NEXT")

    # ── RECOMMENDATIONS PAGE ───────────────────────────────────────
    pdf.add_page()
    _page_header(pdf, "Recommendations")

    _strong = [s for s in snapshots if s["health_score"] >= 80]
    _stable = [s for s in snapshots if 60 <= s["health_score"] < 80]
    _risky = [s for s in snapshots if s["health_score"] < 60]

    recs = []
    if _strong:
        names = ", ".join(s["display_name"] for s in _strong)
        recs.append(("For production workflows", f"Prioritize {names} - strong health across all dimensions."))
    if _stable:
        names = ", ".join(s["display_name"] for s in _stable)
        recs.append(("For reliable integrations", f"Consider {names} - stable with consistent activity and release cadence."))
    if _risky:
        names = ", ".join(s["display_name"] for s in _risky)
        recs.append(("Use with caution", f"{names} show elevated risk. Validate maintenance commitment before adopting."))
    recs.append(("For RAG-heavy apps", "Compare LlamaIndex and LangChain based on docs freshness and issue resolution."))
    recs.append(("For multi-agent orchestration", "Evaluate CrewAI and LangGraph for contributor diversity and release velocity."))

    for idx, (rtitle, rdesc) in enumerate(recs, 1):
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(0, 5, f"{idx}. {rtitle}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(LM + 4)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_C_DARK)
        pdf.multi_cell(0, 4, _pdf_safe(rdesc))
        pdf.ln(2)

    # ── DISCLAIMER ─────────────────────────────────────────────────
    _section(pdf, "Data Limitations & Disclaimer")
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*_C_GRAY)
    pdf.multi_cell(0, 5,
        "Scores are based on public GitHub activity and package metadata. They should be interpreted "
        "as operational signals, not final adoption recommendations. Some projects may use multiple "
        "repositories, private development, or external release channels not fully captured here. "
        "This report was auto-generated by OpenPulse AI and should be validated with domain expertise."
    )

    # Footer
    pdf.ln(6)
    pdf.set_x(LM)
    pdf.set_draw_color(*_C_LIGHT)
    pdf.line(LM, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*_C_GRAY)
    pdf.cell(0, 4, "OpenPulse AI v1.0  |  Data sourced from GitHub REST & GraphQL APIs  |  AI insights powered by GPT-4o", new_x="LMARGIN", new_y="NEXT", align="C")

    return bytes(pdf.output())

_pdf_data = generate_pdf_report()
with _hdr_right:
    st.markdown("<div style='padding-top:18px;'></div>", unsafe_allow_html=True)
    st.download_button(
        label="📄 Export PDF",
        data=_pdf_data,
        file_name=f"openpulse_report_{datetime.now().strftime('%Y%m%d')}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

# ── Chart theme (fixed dark) ─────────────────────────────────────────
CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e2e8f0"),
    template="plotly_dark",
)
CHART_FONT_COLOR = "#e2e8f0"

# ══════════════════════════════════════════════════════════════════════
# SECTION 2: KPI Cards
# ══════════════════════════════════════════════════════════════════════
top_repo = snapshots[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Repos Tracked", len(snapshots))
col2.metric("Avg Health Score", f"{avg_health:.1f}")
col3.metric("Total Stars", f"{total_stars:,}")
col4.metric("Active Alerts", total_alerts, delta=None)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 3: Leaderboard
# ══════════════════════════════════════════════════════════════════════
st.subheader("📊 Ecosystem Leaderboard")

leaderboard_data = []
for i, s in enumerate(snapshots, start=1):
    label, color = get_status(s["health_score"])
    leaderboard_data.append({
        "Rank": i,
        "Repository": s["display_name"],
        "Health": s["health_score"],
        "Status": label,
        "Stars": s.get("stars", 0),
        "Commits (30d)": s.get("commits_30d", 0),
        "Contributors": s.get("contributors_total", 0),
        "Releases (30d)": s.get("releases_30d", 0),
        "Open Issues": s.get("open_issues", 0),
    })

df_leaderboard = pd.DataFrame(leaderboard_data)
st.dataframe(
    df_leaderboard,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Health": st.column_config.ProgressColumn(
            "Health", min_value=0, max_value=100, format="%.1f"
        ),
        "Stars": st.column_config.NumberColumn("Stars", format="%d"),
    },
)

# ══════════════════════════════════════════════════════════════════════
# SECTION 3b: Data Freshness + Scoring Methodology
# ══════════════════════════════════════════════════════════════════════
collected_at = snapshots[0].get("collected_at", "N/A")
_sync_str = str(collected_at)[:16] if collected_at != "N/A" else "N/A"

st.markdown(
    f"""<div style="background:linear-gradient(135deg, #1a1d24 0%, #1e2230 100%);
    border:1px solid #2d3340; border-radius:12px; padding:20px 24px; margin-bottom:1.2rem;">
    <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:16px; text-align:center;">
        <div>
            <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-bottom:4px;">Last Sync</div>
            <div style="font-size:1rem; font-weight:600; color:#f8fafc;">{_sync_str}</div>
        </div>
        <div>
            <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-bottom:4px;">Data Window</div>
            <div style="font-size:1rem; font-weight:600; color:#f8fafc;">30 Days</div>
        </div>
        <div>
            <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-bottom:4px;">Sources</div>
            <div style="font-size:1rem; font-weight:600; color:#f8fafc;">REST + GraphQL</div>
        </div>
        <div>
            <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-bottom:4px;">Repos Tracked</div>
            <div style="font-size:1rem; font-weight:600; color:#f8fafc;">{len(snapshots)}</div>
        </div>
    </div>
    </div>""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""<div style="background:linear-gradient(135deg, #1a1d24 0%, #1e2230 100%);
    border:1px solid #2d3340; border-radius:12px; padding:20px 24px; margin-bottom:1rem;">
    <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-bottom:14px;">
    Scoring Methodology</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:24px;">
        <div>
            <div style="font-weight:600; font-size:0.95rem; margin-bottom:12px; color:#f8fafc;">Health Score Formula</div>
            <div style="display:grid; grid-template-columns:1fr auto; gap:6px 16px; font-size:0.88rem;">
                <span style="color:#cbd5e1;">Release Velocity</span><span style="color:#818cf8; font-weight:700;">{int(SCORE_WEIGHTS['release_velocity']*100)}%</span>
                <span style="color:#cbd5e1;">Issue Resolution</span><span style="color:#818cf8; font-weight:700;">{int(SCORE_WEIGHTS['issue_resolution']*100)}%</span>
                <span style="color:#cbd5e1;">Contributor Activity</span><span style="color:#818cf8; font-weight:700;">{int(SCORE_WEIGHTS['contributor_activity']*100)}%</span>
                <span style="color:#cbd5e1;">Docs Freshness</span><span style="color:#818cf8; font-weight:700;">{int(SCORE_WEIGHTS['docs_freshness']*100)}%</span>
                <span style="color:#cbd5e1;">Dependency Risk</span><span style="color:#818cf8; font-weight:700;">{int(SCORE_WEIGHTS['dependency_risk']*100)}%</span>
            </div>
            <div style="font-size:0.75rem; color:#64748b; margin-top:10px;">Each sub-score: 0–100 · Weighted sum = final composite</div>
        </div>
        <div>
            <div style="font-weight:600; font-size:0.95rem; margin-bottom:12px; color:#f8fafc;">What Each Metric Measures</div>
            <div style="font-size:0.85rem; line-height:1.8; color:#cbd5e1;">
                <div><strong style="color:#f8fafc;">Release Velocity</strong> — Release frequency & recency</div>
                <div><strong style="color:#f8fafc;">Issue Resolution</strong> — Avg close time & stale ratio</div>
                <div><strong style="color:#f8fafc;">Contributor Activity</strong> — Commits, total & new contributors</div>
                <div><strong style="color:#f8fafc;">Docs Freshness</strong> — README/docs last update</div>
                <div><strong style="color:#f8fafc;">Dependency Risk</strong> — Vulnerabilities & outdated deps</div>
            </div>
            <div style="font-size:0.75rem; color:#64748b; margin-top:10px;">
            Alerts: health &lt; {RISK_THRESHOLDS['low_health_score']} · stale issues &gt; {RISK_THRESHOLDS['stale_issue_days']}d · deps &gt; {RISK_THRESHOLDS['dependency_stale_months']}mo</div>
        </div>
    </div>
    </div>""",
    unsafe_allow_html=True,
)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 4: Health Score Comparison Chart
# ══════════════════════════════════════════════════════════════════════
st.subheader("🏥 Health Score Breakdown")

score_data = []
for s in snapshots:
    name = s["display_name"]
    score_data.extend([
        {"Repo": name, "Sub-Score": "Release Velocity", "Value": s.get("release_velocity_score", 0)},
        {"Repo": name, "Sub-Score": "Issue Resolution", "Value": s.get("issue_resolution_score", 0)},
        {"Repo": name, "Sub-Score": "Contributor Activity", "Value": s.get("contributor_activity_score", 0)},
        {"Repo": name, "Sub-Score": "Docs Freshness", "Value": s.get("docs_freshness_score", 0)},
        {"Repo": name, "Sub-Score": "Dependency Risk", "Value": s.get("dependency_risk_score", 0)},
    ])

df_scores = pd.DataFrame(score_data)
fig_bar = px.bar(
    df_scores,
    x="Repo",
    y="Value",
    color="Sub-Score",
    barmode="group",
    title="Sub-Score Comparison Across Repositories",
    color_discrete_sequence=px.colors.qualitative.Set2,
    height=450,
)
fig_bar.update_layout(
    yaxis_title="Score (0–100)",
    xaxis_title="",
    legend_title="Sub-Score",
    **CHART_LAYOUT,
)
st.plotly_chart(fig_bar, use_container_width=True, theme=None)

# ══════════════════════════════════════════════════════════════════════
# SECTION 5: Radar Chart — Top 3 vs Bottom 3
# ══════════════════════════════════════════════════════════════════════
st.subheader("🎯 Radar Comparison")

radar_cols = st.columns(2)
categories = ["Release Velocity", "Issue Resolution", "Contributor Activity", "Docs Freshness", "Dependency Risk"]

with radar_cols[0]:
    st.markdown("**Top Performers**")
    fig_top = go.Figure()
    for s in snapshots[:3]:
        values = [
            s.get("release_velocity_score", 0),
            s.get("issue_resolution_score", 0),
            s.get("contributor_activity_score", 0),
            s.get("docs_freshness_score", 0),
            s.get("dependency_risk_score", 0),
        ]
        fig_top.add_trace(go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            name=s["display_name"],
            fill="toself",
            opacity=0.6,
        ))
    fig_top.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        height=340,
        showlegend=True,
        **CHART_LAYOUT,
    )
    st.plotly_chart(fig_top, use_container_width=True, theme=None)

with radar_cols[1]:
    st.markdown("**Needs Attention**")
    fig_bottom = go.Figure()
    for s in snapshots[-3:]:
        values = [
            s.get("release_velocity_score", 0),
            s.get("issue_resolution_score", 0),
            s.get("contributor_activity_score", 0),
            s.get("docs_freshness_score", 0),
            s.get("dependency_risk_score", 0),
        ]
        fig_bottom.add_trace(go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            name=s["display_name"],
            fill="toself",
            opacity=0.6,
        ))
    fig_bottom.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        height=340,
        showlegend=True,
        **CHART_LAYOUT,
    )
    st.plotly_chart(fig_bottom, use_container_width=True, theme=None)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 6: Risk Alerts
# ══════════════════════════════════════════════════════════════════════
st.subheader("⚠️ Risk Alerts")

severity_icons = {"critical": "🔴", "warning": "🟡", "info": "🟢"}

has_alerts = False
for s in snapshots:
    alerts = all_alerts.get(s["repo_key"], [])
    actionable = [a for a in alerts if a["severity"] in ("critical", "warning")]
    if not actionable:
        continue

    has_alerts = True
    with st.expander(f"{s['display_name']} — {len(actionable)} alert(s)", expanded=s["health_score"] < 60):
        for a in alerts:
            icon = severity_icons.get(a["severity"], "")
            css_class = f"alert-{a['severity']}"
            evidence = ""
            mk = a.get("metric_key", "")
            mv = a.get("metric_value", "")
            if mk == "commits_30d":
                evidence = f"Evidence: {int(mv)} commits detected in the last 30-day window."
            elif mk == "stale_issues_count":
                evidence = f"Evidence: {int(mv)} issues have had no update for 90+ days."
            elif mk == "days_since_last_release":
                evidence = f"Evidence: last release was {int(mv)} days ago."
            elif mk == "health_score":
                evidence = f"Evidence: composite score is {mv:.1f}/100 (threshold: {RISK_THRESHOLDS['low_health_score']})."
            elif mk == "avg_issue_close_days":
                evidence = f"Evidence: average issue close time measured at {mv:.1f} days."
            elif mk == "dependency_risk_count":
                evidence = f"Evidence: {int(mv)} dependency risks flagged by analysis."

            st.markdown(
                f'<div class="{css_class}">{icon} <strong>{a["title"]}</strong><br/>'
                f'{a["description"]}<br/>'
                f'<small style="opacity:0.7;">{evidence}</small></div>',
                unsafe_allow_html=True,
            )

if not has_alerts:
    st.success("No critical or warning alerts across the ecosystem.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 7: Per-Repo Deep Dive
# ══════════════════════════════════════════════════════════════════════
st.subheader("🔍 Repository Deep Dive")

selected_repo = st.selectbox(
    "Select a repository",
    options=[s["display_name"] for s in snapshots],
    index=0,
)

repo_snapshot = next(s for s in snapshots if s["display_name"] == selected_repo)
repo_key = repo_snapshot["repo_key"]
repo_alerts = all_alerts.get(repo_key, [])
repo_trend = trends.get(repo_key, {})
label, color = get_status(repo_snapshot["health_score"])

# Health badge
st.markdown(
    f'### {selected_repo} &nbsp; '
    f'<span class="health-badge" style="background:{color};">'
    f'{repo_snapshot["health_score"]:.1f} — {label}</span>',
    unsafe_allow_html=True,
)

# Metrics grid
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Stars", f"{repo_snapshot.get('stars', 0):,}")
m2.metric("Forks", f"{repo_snapshot.get('forks', 0):,}")
m3.metric("Open Issues", repo_snapshot.get("open_issues", 0))
m4.metric("Commits (30d)", repo_snapshot.get("commits_30d", 0))
m5.metric("Contributors", repo_snapshot.get("contributors_total", 0))

m6, m7, m8, m9, m10 = st.columns(5)
m6.metric("Releases (30d)", repo_snapshot.get("releases_30d", 0))
m7.metric("Avg Close (days)", f"{repo_snapshot.get('avg_issue_close_days', 0):.1f}")
m8.metric("Stale Issues", repo_snapshot.get("stale_issues_count", 0))
m9.metric("New Contributors", repo_snapshot.get("contributors_new_30d", 0))
m10.metric("Days Since Release", repo_snapshot.get("days_since_last_release", 0))

# Source links
_repo_key_parts = repo_snapshot.get("repo_key", "/").split("/")
_owner = _repo_key_parts[0] if len(_repo_key_parts) > 0 else ""
_repo_name = _repo_key_parts[1] if len(_repo_key_parts) > 1 else ""
_gh_base = f"https://github.com/{_owner}/{_repo_name}"
st.markdown(
    f"🔗 &nbsp; [Repository]({_gh_base}) &nbsp;|&nbsp; "
    f"[Releases]({_gh_base}/releases) &nbsp;|&nbsp; "
    f"[Issues]({_gh_base}/issues) &nbsp;|&nbsp; "
    f"[Contributors]({_gh_base}/graphs/contributors) &nbsp;|&nbsp; "
    f"[Docs]({_gh_base}#readme)",
)

# Sub-score gauges
st.markdown("#### Sub-Scores")
g1, g2, g3, g4, g5 = st.columns(5)

sub_scores = [
    ("Release Velocity", repo_snapshot.get("release_velocity_score", 0)),
    ("Issue Resolution", repo_snapshot.get("issue_resolution_score", 0)),
    ("Contributor Activity", repo_snapshot.get("contributor_activity_score", 0)),
    ("Docs Freshness", repo_snapshot.get("docs_freshness_score", 0)),
    ("Dependency Risk", repo_snapshot.get("dependency_risk_score", 0)),
]

for col, (name, val) in zip([g1, g2, g3, g4, g5], sub_scores):
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=val,
        title={"text": name, "font": {"size": 12, "color": CHART_FONT_COLOR}},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#22c55e" if val >= 75 else "#f59e0b" if val >= 50 else "#ef4444"},
            "bgcolor": "rgba(0,0,0,0.05)",
        },
    ))
    fig_gauge.update_layout(height=200, margin=dict(t=40, b=10, l=20, r=20), **CHART_LAYOUT)
    col.plotly_chart(fig_gauge, use_container_width=True, theme=None)

# Risk alerts for this repo
if repo_alerts:
    st.markdown("#### Alerts")
    for a in repo_alerts:
        icon = severity_icons.get(a["severity"], "")
        css_class = f"alert-{a['severity']}"
        st.markdown(
            f'<div class="{css_class}">{icon} <strong>{a["title"]}</strong> — {a["description"]}</div>',
            unsafe_allow_html=True,
        )

# Trend data
if repo_trend and repo_trend.get("has_previous"):
    st.markdown("#### Trends (vs Previous Snapshot)")
    deltas = repo_trend["deltas"]
    trend_items = ["stars", "health_score", "commits_30d", "open_issues", "contributors_total"]
    tcols = st.columns(len(trend_items))
    for col, key in zip(tcols, trend_items):
        d = deltas.get(key, {})
        val = d.get("value")
        direction = d.get("direction", "new")
        arrow = "↑" if direction == "up" else "↓" if direction == "down" else "→"
        col.metric(key.replace("_", " ").title(), f"{arrow} {val:+.1f}" if val is not None else "N/A")
else:
    st.info("Trend data requires at least 2 collection snapshots. Run `python collect.py` again tomorrow.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 8: AI Insights
# ══════════════════════════════════════════════════════════════════════
st.subheader("🤖 AI-Powered Insights")

tab_eco, tab_repo = st.tabs(["Ecosystem Overview", "Per-Repo Analysis"])

with tab_eco:
    with st.spinner("Generating ecosystem insight..."):
        eco_insight = generate_ecosystem_insight(snapshots, all_alerts)
    st.markdown(eco_insight)

with tab_repo:
    insight_repo = st.selectbox(
        "Select repo for AI analysis",
        options=[s["display_name"] for s in snapshots],
        index=0,
        key="insight_repo_select",
    )
    insight_snapshot = next(s for s in snapshots if s["display_name"] == insight_repo)
    insight_alerts = all_alerts.get(insight_snapshot["repo_key"], [])

    with st.spinner(f"Generating insight for {insight_repo}..."):
        repo_insight = generate_repo_insight(insight_snapshot, insight_alerts)
    st.markdown(repo_insight)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 8b: AI Recommendations (Actionable)
# ══════════════════════════════════════════════════════════════════════
st.subheader("💡 Recommended Actions")

# Build dynamic recommendations based on actual data
_strong = [s for s in snapshots if s["health_score"] >= 90]
_stable = [s for s in snapshots if 80 <= s["health_score"] < 90]
_risky = [s for s in snapshots if s["health_score"] < 70]

rec_lines = []
if _strong:
    names = ", ".join(s["display_name"] for s in _strong)
    rec_lines.append(f"**For production agent workflows:** prioritize **{names}** — they show strong health across all dimensions.")
if _stable:
    names = ", ".join(s["display_name"] for s in _stable)
    rec_lines.append(f"**For reliable integrations:** consider **{names}** — stable with consistent activity and release cadence.")
if _risky:
    names = ", ".join(s["display_name"] for s in _risky)
    rec_lines.append(f"**Use with caution:** **{names}** show elevated risk. Validate maintenance commitment before adopting in production.")

rec_lines.append("**For RAG-heavy apps:** compare LlamaIndex and LangChain based on docs freshness and issue resolution scores above.")
rec_lines.append("**For multi-agent orchestration:** evaluate CrewAI and LangGraph — check contributor diversity and release velocity.")

for i, line in enumerate(rec_lines, 1):
    st.markdown(f"{i}. {line}")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 8c: Trend Charts (multi-snapshot)
# ══════════════════════════════════════════════════════════════════════
st.subheader("📈 Historical Trends")

conn = get_connection()
snapshot_dates = conn.execute(
    "SELECT DISTINCT collected_at FROM repo_snapshots ORDER BY collected_at"
).fetchall()
conn.close()

if len(snapshot_dates) >= 2:
    # Load historical data
    conn = get_connection()
    history_rows = conn.execute(
        "SELECT display_name, collected_at, health_score, stars, open_issues, commits_30d "
        "FROM repo_snapshots ORDER BY collected_at"
    ).fetchall()
    conn.close()

    df_history = pd.DataFrame([dict(r) for r in history_rows])
    df_history["collected_at"] = pd.to_datetime(df_history["collected_at"])

    trend_tab1, trend_tab2, trend_tab3, trend_tab4 = st.tabs([
        "Health Over Time", "Stars Growth", "Issue Backlog", "Commit Activity"
    ])

    with trend_tab1:
        fig_h = px.line(df_history, x="collected_at", y="health_score", color="display_name",
                        title="Health Score Over Time", markers=True)
        fig_h.update_layout(**CHART_LAYOUT)
        st.plotly_chart(fig_h, use_container_width=True, theme=None)

    with trend_tab2:
        fig_s = px.line(df_history, x="collected_at", y="stars", color="display_name",
                        title="Stars Growth Over Time", markers=True)
        fig_s.update_layout(**CHART_LAYOUT)
        st.plotly_chart(fig_s, use_container_width=True, theme=None)

    with trend_tab3:
        fig_i = px.line(df_history, x="collected_at", y="open_issues", color="display_name",
                        title="Open Issues Trend", markers=True)
        fig_i.update_layout(**CHART_LAYOUT)
        st.plotly_chart(fig_i, use_container_width=True, theme=None)

    with trend_tab4:
        fig_c = px.line(df_history, x="collected_at", y="commits_30d", color="display_name",
                        title="Commit Activity (30-day window)", markers=True)
        fig_c.update_layout(**CHART_LAYOUT)
        st.plotly_chart(fig_c, use_container_width=True, theme=None)
else:
    st.info(
        f"📊 Trend charts require at least 2 collection runs. "
        f"Currently: **{len(snapshot_dates)} snapshot(s)**. "
        f"Run `python collect.py` daily to build historical data."
    )

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# SECTION 9: Sidebar — About & Controls
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🔬 OpenPulse AI")
    st.caption("v1.0 — Ecosystem Intelligence")
    st.markdown("---")

    st.markdown("**Data Status**")
    st.markdown(f"- Repos tracked: **{len(snapshots)}**")
    st.markdown(f"- Last collected: **{snapshots[0].get('collected_at', 'N/A')}**")
    st.markdown(f"- Avg health: **{avg_health:.1f}**/100")
    st.markdown("---")

    st.markdown("**Controls**")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    st.markdown("**Repository Mapping**")
    for r in TRACKED_REPOS:
        st.markdown(f"- {r['display_name']} → `{r['owner']}/{r['repo']}`")

    st.markdown("---")
    st.caption(
        "Built with Python, Streamlit, Plotly & GPT-4o."
    )

# ══════════════════════════════════════════════════════════════════════
# SECTION 10: What-If Weight Simulator
# ══════════════════════════════════════════════════════════════════════
st.subheader("🎛️ What-If Weight Simulator")
st.caption("Drag the sliders to adjust scoring weights and watch rankings recalculate in real time.")

_sim_snapshot_data = [
    {
        "display_name": s["display_name"],
        "health_score": s.get("health_score", 0),
        "release_velocity_score": s.get("release_velocity_score", 0),
        "issue_resolution_score": s.get("issue_resolution_score", 0),
        "contributor_activity_score": s.get("contributor_activity_score", 0),
        "docs_freshness_score": s.get("docs_freshness_score", 0),
        "dependency_risk_score": s.get("dependency_risk_score", 0),
    }
    for s in snapshots
]

@st.fragment
def weight_simulator():
    sim_cols = st.columns(5)
    with sim_cols[0]:
        w_rv = st.slider("Release Velocity", 0, 100, int(SCORE_WEIGHTS["release_velocity"] * 100), key="sim_rv")
    with sim_cols[1]:
        w_ir = st.slider("Issue Resolution", 0, 100, int(SCORE_WEIGHTS["issue_resolution"] * 100), key="sim_ir")
    with sim_cols[2]:
        w_ca = st.slider("Contributor Activity", 0, 100, int(SCORE_WEIGHTS["contributor_activity"] * 100), key="sim_ca")
    with sim_cols[3]:
        w_df = st.slider("Docs Freshness", 0, 100, int(SCORE_WEIGHTS["docs_freshness"] * 100), key="sim_df")
    with sim_cols[4]:
        w_dr = st.slider("Dependency Risk", 0, 100, int(SCORE_WEIGHTS["dependency_risk"] * 100), key="sim_dr")

    _total_w = w_rv + w_ir + w_ca + w_df + w_dr
    if _total_w == 0:
        _total_w = 1

    sim_weights = {
        "release_velocity": w_rv / _total_w,
        "issue_resolution": w_ir / _total_w,
        "contributor_activity": w_ca / _total_w,
        "docs_freshness": w_df / _total_w,
        "dependency_risk": w_dr / _total_w,
    }

    sim_data = []
    for s in _sim_snapshot_data:
        sim_health = round(
            s["release_velocity_score"] * sim_weights["release_velocity"]
            + s["issue_resolution_score"] * sim_weights["issue_resolution"]
            + s["contributor_activity_score"] * sim_weights["contributor_activity"]
            + s["docs_freshness_score"] * sim_weights["docs_freshness"]
            + s["dependency_risk_score"] * sim_weights["dependency_risk"],
            1,
        )
        sim_data.append({
            "Repository": s["display_name"],
            "Original Score": s["health_score"],
            "Simulated Score": sim_health,
            "Change": round(sim_health - s["health_score"], 1),
        })

    sim_data.sort(key=lambda x: x["Simulated Score"], reverse=True)

    st.markdown(
        f"<div style='font-size:0.8rem; color:#64748b; margin-bottom:8px;'>"
        f"Normalized: RV {sim_weights['release_velocity']:.0%} · "
        f"IR {sim_weights['issue_resolution']:.0%} · "
        f"CA {sim_weights['contributor_activity']:.0%} · "
        f"DF {sim_weights['docs_freshness']:.0%} · "
        f"DR {sim_weights['dependency_risk']:.0%}</div>",
        unsafe_allow_html=True,
    )

    sim_chart_col, sim_table_col = st.columns([3, 2])

    with sim_chart_col:
        df_sim = pd.DataFrame(sim_data)
        fig_sim = go.Figure()
        fig_sim.add_trace(go.Bar(
            x=df_sim["Repository"], y=df_sim["Original Score"],
            name="Original Weights", marker_color="#f59e0b",
        ))
        fig_sim.add_trace(go.Bar(
            x=df_sim["Repository"], y=df_sim["Simulated Score"],
            name="Your Weights", marker_color="#22d3ee",
        ))
        fig_sim.update_layout(
            barmode="group", title="Original vs Simulated Scores",
            yaxis_title="Health Score", height=400,
            **CHART_LAYOUT,
        )
        st.plotly_chart(fig_sim, use_container_width=True, theme=None)

    with sim_table_col:
        for i, row in enumerate(sim_data):
            change = row["Change"]
            arrow = "🔼" if change > 0 else "🔽" if change < 0 else "➡️"
            change_color = "#22c55e" if change > 0 else "#ef4444" if change < 0 else "#94a3b8"
            st.markdown(
                f"<div style='background:#1a1d24; border:1px solid #2d3340; border-radius:8px; "
                f"padding:10px 14px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;'>"
                f"<div><span style='color:#94a3b8; font-size:0.75rem;'>#{i+1}</span> "
                f"<strong style='color:#f8fafc;'>{row['Repository']}</strong></div>"
                f"<div style='text-align:right;'>"
                f"<span style='font-size:1.1rem; font-weight:700; color:#f8fafc;'>{row['Simulated Score']}</span>"
                f"<span style='font-size:0.8rem; color:{change_color}; margin-left:8px;'>"
                f"{arrow} {change:+.1f}</span></div></div>",
                unsafe_allow_html=True,
            )

weight_simulator()

st.markdown("---")

# ── Data Limitations ────────────────────────────────────────────────
st.markdown(
    """<div style="background:linear-gradient(135deg, #1a1d24 0%, #1e2230 100%);
    border:1px solid #2d3340; border-radius:10px; padding:14px 20px; margin-bottom:1rem;">
    <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-bottom:6px;">
    Data Limitations</div>
    <div style="font-size:0.82rem; color:#94a3b8; line-height:1.6;">
    Scores are based on public GitHub activity and package metadata. They should be interpreted
    as operational signals, not final adoption recommendations. Some projects may use multiple
    repositories, private development, or external release channels not fully captured here.
    </div>
    </div>""",
    unsafe_allow_html=True,
)

# ── Footer ───────────────────────────────────────────────────────────
st.caption("OpenPulse AI v1.0 — Data sourced from GitHub REST & GraphQL APIs. AI insights powered by GPT-4o.")
