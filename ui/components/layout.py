"""全域版面與 CSS 注入（專業交易終端暗色主題）。"""

from __future__ import annotations

import streamlit as st

_TERMINAL_CSS = """
<style>
/* ── 字體引入 ─────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+TC:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── 色彩變數 ─────────────────────────────────── */
:root {
  --bg-0:    #111417;
  --bg-1:    #1A1F24;
  --bg-2:    #232B33;
  --line:    #2B343D;
  --text-0:  #E6E9EC;
  --text-1:  #9AA6B2;
  --up:      #D84B4B;
  --down:    #3FA66B;
  --warn:    #E0A94A;
  --accent:  #3D6E8F;
  --accent-h:#4D87AF;
}

/* ── 主背景 ───────────────────────────────────── */
.stApp, [data-testid="stAppViewContainer"] {
  background-color: var(--bg-0) !important;
  font-family: 'IBM Plex Sans TC', 'Noto Sans TC', sans-serif !important;
  color: var(--text-0) !important;
}

/* 主內容區域 */
[data-testid="stMain"], .main .block-container {
  background-color: var(--bg-0) !important;
  padding-top: 1.5rem !important;
  max-width: 1400px !important;
}

/* ── Sidebar ──────────────────────────────────── */
[data-testid="stSidebar"] {
  background-color: var(--bg-1) !important;
  border-right: 1px solid var(--line) !important;
}
[data-testid="stSidebar"] * {
  color: var(--text-0) !important;
}
[data-testid="stSidebarNav"] a {
  border-radius: 4px !important;
  padding: 0.3rem 0.6rem !important;
  font-size: 0.875rem !important;
}
[data-testid="stSidebarNav"] a:hover {
  background-color: var(--bg-2) !important;
}

/* ── 標題 ─────────────────────────────────────── */
h1, h2, h3, h4 {
  color: var(--text-0) !important;
  font-weight: 600 !important;
  letter-spacing: 0.02em !important;
}
h1 { border-bottom: 1px solid var(--line); padding-bottom: 0.4em; }
h3 { margin-top: 0.25rem !important; }

/* ── 按鈕 ─────────────────────────────────────── */
.stButton > button {
  background-color: var(--accent) !important;
  color: var(--text-0) !important;
  border: none !important;
  border-radius: 4px !important;
  font-family: 'IBM Plex Sans TC', sans-serif !important;
  font-size: 0.85rem !important;
  padding: 0.4rem 1rem !important;
  transition: background 0.15s ease !important;
}
.stButton > button:hover {
  background-color: var(--accent-h) !important;
}
.stButton > button[kind="primary"] {
  background-color: var(--up) !important;
}
.stButton > button[kind="primary"]:hover {
  background-color: #c03030 !important;
}
.stFormSubmitButton > button {
  background-color: var(--accent) !important;
  color: var(--text-0) !important;
  border-radius: 4px !important;
  font-size: 0.85rem !important;
}

/* ── Metrics ──────────────────────────────────── */
[data-testid="stMetric"] {
  background-color: var(--bg-1) !important;
  border: 1px solid var(--line) !important;
  border-radius: 4px !important;
  padding: 0.75rem 1rem !important;
}
[data-testid="stMetricLabel"] {
  color: var(--text-1) !important;
  font-size: 0.75rem !important;
  text-transform: uppercase !important;
  letter-spacing: 0.05em !important;
}
[data-testid="stMetricValue"] {
  color: var(--text-0) !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 1.5rem !important;
}

/* ── Dataframe / 表格 ─────────────────────────── */
[data-testid="stDataFrame"] {
  border: 1px solid var(--line) !important;
  border-radius: 4px !important;
  overflow: hidden !important;
}
.stDataFrame thead tr th {
  background-color: var(--bg-2) !important;
  color: var(--text-1) !important;
  font-size: 0.76rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
}
.stDataFrame tbody tr:hover td {
  background-color: var(--bg-2) !important;
}

/* ── Code / pre ───────────────────────────────── */
code, pre, .stCode {
  font-family: 'JetBrains Mono', monospace !important;
  background-color: var(--bg-1) !important;
  color: #A8D8A8 !important;
  border: 1px solid var(--line) !important;
  border-radius: 4px !important;
  font-size: 0.82rem !important;
}
/* Command preview 特別加粗 */
.stCode code { font-size: 0.80rem !important; }

/* ── Info / Success / Error / Warning box ──────── */
[data-testid="stAlert"] {
  border-radius: 4px !important;
  border-left-width: 3px !important;
}

/* ── Tabs ─────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
  border-bottom: 1px solid var(--line) !important;
  background-color: transparent !important;
}
.stTabs [data-baseweb="tab"] {
  color: var(--text-1) !important;
  font-size: 0.85rem !important;
  padding: 0.4rem 1rem !important;
}
.stTabs [aria-selected="true"] {
  color: var(--text-0) !important;
  border-bottom: 2px solid var(--accent) !important;
}

/* ── 分隔線 ───────────────────────────────────── */
hr { border-color: var(--line) !important; margin: 0.75rem 0 !important; }

/* ── Expander ─────────────────────────────────── */
[data-testid="stExpander"] {
  background-color: var(--bg-1) !important;
  border: 1px solid var(--line) !important;
  border-radius: 4px !important;
}
[data-testid="stExpander"] summary {
  font-size: 0.85rem !important;
  color: var(--text-1) !important;
}

/* ── Input 欄位 ───────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {
  background-color: var(--bg-1) !important;
  color: var(--text-0) !important;
  border: 1px solid var(--line) !important;
  border-radius: 4px !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 0.88rem !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px rgba(61,110,143,0.3) !important;
}
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div {
  background-color: var(--bg-1) !important;
  border: 1px solid var(--line) !important;
  border-radius: 4px !important;
  color: var(--text-0) !important;
}

/* ── Checkbox ─────────────────────────────────── */
[data-testid="stCheckbox"] label {
  color: var(--text-1) !important;
  font-size: 0.88rem !important;
}

/* ── Radio ────────────────────────────────────── */
[data-testid="stRadio"] label {
  color: var(--text-1) !important;
  font-size: 0.88rem !important;
}

/* ── Caption / 小字 ───────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--text-1) !important;
  font-size: 0.80rem !important;
}

/* ── 下載按鈕 ─────────────────────────────────── */
[data-testid="stDownloadButton"] button {
  background-color: var(--bg-2) !important;
  border: 1px solid var(--line) !important;
  color: var(--text-1) !important;
  font-size: 0.82rem !important;
  border-radius: 4px !important;
}
[data-testid="stDownloadButton"] button:hover {
  border-color: var(--accent) !important;
  color: var(--text-0) !important;
}

/* ── Mobile（< 768px）─────────────────────────── */
@media (max-width: 768px) {
  .main .block-container {
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
  }
  h1 { font-size: 1.4rem !important; }
  [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
}
</style>
"""

_STATUS_BADGE = {
    "running": ("🟡", "#E0A94A"),
    "success": ("🟢", "#3FA66B"),
    "failed": ("🔴", "#D84B4B"),
    "pending": ("⚪", "#9AA6B2"),
    "stopped": ("⏹️", "#9AA6B2"),
    "unknown": ("❓", "#9AA6B2"),
}


def inject_css() -> None:
    """注入暗色交易終端 CSS。"""
    st.markdown(_TERMINAL_CSS, unsafe_allow_html=True)


def status_badge_html(status: str) -> str:
    icon, color = _STATUS_BADGE.get(status.lower(), ("❓", "#9AA6B2"))
    return f'<span style="color:{color};font-weight:600">{icon} {status.upper()}</span>'


def section_header(title: str, subtitle: str = "") -> None:
    """渲染區塊標題（含次標題）。"""
    st.markdown(f"### {title}")
    if subtitle:
        st.markdown(
            f'<p style="color:var(--text-1);font-size:0.82rem;margin-top:-0.75rem;margin-bottom:0.5rem">'
            f"{subtitle}</p>",
            unsafe_allow_html=True,
        )
