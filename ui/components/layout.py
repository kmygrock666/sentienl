"""全域版面與 CSS 注入（機構級交易終端 HUD 暗色主題）。

設計語彙：石墨藍底、琥珀操作主調、台股紅漲綠跌、等寬數字（tabular-nums）、
卡片層次（內緣高光＋陰影）、終端提示符式區塊標題、節制的微動效。
"""

from __future__ import annotations

import streamlit as st

_TERMINAL_CSS = """
<style>
/* ── 字體引入：Chakra Petch（HUD 顯示字）＋ IBM Plex Sans TC（內文）＋ JetBrains Mono（數字）── */
@import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Sans+TC:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ── 色彩變數 ─────────────────────────────────── */
:root {
  --bg-0:    #0C1116;            /* 最深底 */
  --bg-1:    #131A21;            /* 卡片底 */
  --bg-2:    #1B242E;            /* 浮起層 */
  --line:    #263038;
  --line-hi: #33414C;
  --text-0:  #E8ECEF;
  --text-1:  #8E9BA8;
  --text-2:  #5C6B78;
  --up:      #E5484D;            /* 台股慣例：漲紅 */
  --up-dim:  rgba(229,72,77,0.12);
  --down:    #2FA46C;            /* 跌綠 */
  --down-dim:rgba(47,164,108,0.12);
  --warn:    #E0A94A;
  --accent:  #F0A03C;            /* 琥珀主調 */
  --accent-h:#FFB85C;
  --accent-dim: rgba(240,160,60,0.14);
  --cyan:    #4DB8C4;            /* 輔助資訊色 */
  --font-hud:  'Chakra Petch', 'IBM Plex Sans TC', sans-serif;
  --font-body: 'IBM Plex Sans TC', 'Noto Sans TC', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
}

/* ── 主背景：頂部琥珀微光暈 + 深石墨藍 ───────────── */
.stApp, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1200px 420px at 18% -8%, rgba(240,160,60,0.06), transparent 60%),
    radial-gradient(900px 380px at 85% -12%, rgba(77,184,196,0.05), transparent 55%),
    var(--bg-0) !important;
  font-family: var(--font-body) !important;
  color: var(--text-0) !important;
}
[data-testid="stMain"], .main .block-container {
  background: transparent !important;
  padding-top: 1.25rem !important;
  max-width: 1440px !important;
  animation: page-in 0.35s ease-out;
}
@keyframes page-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: none; }
}

/* ── 文字選取與捲軸 ───────────────────────────── */
::selection { background: var(--accent-dim); color: var(--accent-h); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--bg-0); }
::-webkit-scrollbar-thumb {
  background: var(--bg-2); border-radius: 6px; border: 2px solid var(--bg-0);
}
::-webkit-scrollbar-thumb:hover { background: var(--line-hi); }

/* ── Sidebar：品牌欄 ──────────────────────────── */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #10161C 0%, var(--bg-1) 100%) !important;
  border-right: 1px solid var(--line) !important;
}
[data-testid="stSidebar"] * { color: var(--text-0) !important; }
[data-testid="stSidebarNav"]::before {
  content: "SENTINEL ▮";
  display: block;
  padding: 1.1rem 1.2rem 0.6rem;
  font-family: var(--font-hud);
  font-size: 1.02rem;
  font-weight: 700;
  letter-spacing: 0.22em;
  color: var(--accent);
  text-shadow: 0 0 18px rgba(240,160,60,0.35);
}
[data-testid="stSidebarNav"] a {
  border-radius: 3px !important;
  padding: 0.32rem 0.65rem !important;
  font-size: 0.86rem !important;
  border-left: 2px solid transparent !important;
  transition: background 0.12s ease, border-color 0.12s ease !important;
}
[data-testid="stSidebarNav"] a:hover {
  background: var(--bg-2) !important;
  border-left-color: var(--line-hi) !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: var(--accent-dim) !important;
  border-left-color: var(--accent) !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"] span {
  color: var(--accent-h) !important;
}

/* ── 標題：HUD 顯示字 ─────────────────────────── */
h1, h2 {
  font-family: var(--font-hud) !important;
  color: var(--text-0) !important;
  font-weight: 600 !important;
  letter-spacing: 0.04em !important;
}
h1 {
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.35em;
  background: linear-gradient(90deg, var(--text-0) 65%, var(--text-1));
  -webkit-background-clip: text;
  background-clip: text;
}
h3, h4 {
  color: var(--text-0) !important;
  font-weight: 600 !important;
  letter-spacing: 0.02em !important;
  margin-top: 0.25rem !important;
}

/* ── 按鈕：琥珀操作色 ─────────────────────────── */
.stButton > button, .stFormSubmitButton > button {
  background: linear-gradient(180deg, rgba(255,255,255,0.05), transparent) var(--bg-2) !important;
  color: var(--accent-h) !important;
  border: 1px solid rgba(240,160,60,0.45) !important;
  border-radius: 3px !important;
  font-family: var(--font-body) !important;
  font-size: 0.85rem !important;
  font-weight: 500 !important;
  padding: 0.4rem 1.05rem !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 1px rgba(240,160,60,0.25), 0 0 18px rgba(240,160,60,0.12) !important;
  background: var(--accent-dim) !important;
}
.stButton > button[kind="primary"] {
  background: linear-gradient(180deg, #F7B254, var(--accent)) !important;
  color: #14100A !important;
  border: none !important;
  font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover {
  background: linear-gradient(180deg, #FFC470, var(--accent-h)) !important;
  box-shadow: 0 0 22px rgba(240,160,60,0.30) !important;
}

/* ── Metrics：左緣琥珀刻線卡片 ─────────────────── */
[data-testid="stMetric"] {
  position: relative;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.03), transparent 45%) var(--bg-1) !important;
  border: 1px solid var(--line) !important;
  border-left: 3px solid var(--accent) !important;
  border-radius: 3px !important;
  padding: 0.7rem 1rem !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.25) !important;
  transition: border-color 0.15s ease, transform 0.15s ease !important;
}
[data-testid="stMetric"]:hover {
  border-color: var(--line-hi) !important;
  border-left-color: var(--accent-h) !important;
  transform: translateY(-1px);
}
[data-testid="stMetricLabel"] {
  color: var(--text-1) !important;
  font-size: 0.72rem !important;
  text-transform: uppercase !important;
  letter-spacing: 0.1em !important;
}
[data-testid="stMetricValue"] {
  color: var(--text-0) !important;
  font-family: var(--font-mono) !important;
  font-variant-numeric: tabular-nums !important;
  font-size: 1.45rem !important;
  font-weight: 500 !important;
}
[data-testid="stMetricDelta"] {
  font-family: var(--font-mono) !important;
  font-size: 0.82rem !important;
}

/* ── Dataframe / 表格：資料密度與數字對齊 ───────── */
[data-testid="stDataFrame"] {
  border: 1px solid var(--line) !important;
  border-radius: 3px !important;
  overflow: hidden !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.3) !important;
}
.stDataFrame thead tr th {
  background: var(--bg-2) !important;
  color: var(--text-1) !important;
  font-size: 0.74rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  border-bottom: 1px solid var(--line-hi) !important;
}
.stDataFrame tbody tr td {
  font-variant-numeric: tabular-nums !important;
  font-size: 0.85rem !important;
}
.stDataFrame tbody tr:nth-child(even) td { background: rgba(255,255,255,0.015) !important; }
.stDataFrame tbody tr:hover td { background: var(--accent-dim) !important; }

/* ── Code / Command preview ───────────────────── */
code, pre, .stCode {
  font-family: var(--font-mono) !important;
  background: #0E1419 !important;
  color: #9ECE9E !important;
  border: 1px solid var(--line) !important;
  border-radius: 3px !important;
  font-size: 0.82rem !important;
}
.stCode code { font-size: 0.80rem !important; }

/* ── Alert boxes ──────────────────────────────── */
[data-testid="stAlert"] {
  background: var(--bg-1) !important;
  border: 1px solid var(--line) !important;
  border-left-width: 3px !important;
  border-radius: 3px !important;
}

/* ── Tabs：底線光痕 ───────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
  border-bottom: 1px solid var(--line) !important;
  background: transparent !important;
  gap: 0.25rem !important;
}
.stTabs [data-baseweb="tab"] {
  color: var(--text-1) !important;
  font-size: 0.86rem !important;
  padding: 0.45rem 1.05rem !important;
  border-radius: 3px 3px 0 0 !important;
  transition: color 0.12s ease, background 0.12s ease !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text-0) !important;
  background: var(--bg-1) !important;
}
.stTabs [aria-selected="true"] {
  color: var(--accent-h) !important;
  border-bottom: 2px solid var(--accent) !important;
  text-shadow: 0 0 14px rgba(240,160,60,0.35);
}

/* ── 分隔線 ───────────────────────────────────── */
hr {
  border: none !important;
  height: 1px !important;
  background: linear-gradient(90deg, var(--line), transparent) !important;
  margin: 0.85rem 0 !important;
}

/* ── Expander ─────────────────────────────────── */
[data-testid="stExpander"] {
  background: var(--bg-1) !important;
  border: 1px solid var(--line) !important;
  border-radius: 3px !important;
}
[data-testid="stExpander"] summary {
  font-size: 0.85rem !important;
  color: var(--text-1) !important;
}
[data-testid="stExpander"] summary:hover { color: var(--accent-h) !important; }

/* ── Input 欄位 ───────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {
  background: #0E1419 !important;
  color: var(--text-0) !important;
  border: 1px solid var(--line) !important;
  border-radius: 3px !important;
  font-family: var(--font-mono) !important;
  font-size: 0.88rem !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stDateInput"] input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent-dim) !important;
}
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div {
  background: #0E1419 !important;
  border: 1px solid var(--line) !important;
  border-radius: 3px !important;
  color: var(--text-0) !important;
}

/* ── Checkbox / Radio ─────────────────────────── */
[data-testid="stCheckbox"] label, [data-testid="stRadio"] label {
  color: var(--text-1) !important;
  font-size: 0.88rem !important;
}

/* ── Caption ──────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--text-2) !important;
  font-size: 0.79rem !important;
  letter-spacing: 0.01em !important;
}

/* ── 下載按鈕 ─────────────────────────────────── */
[data-testid="stDownloadButton"] button {
  background: var(--bg-2) !important;
  border: 1px solid var(--line) !important;
  color: var(--text-1) !important;
  font-size: 0.82rem !important;
  border-radius: 3px !important;
}
[data-testid="stDownloadButton"] button:hover {
  border-color: var(--accent) !important;
  color: var(--accent-h) !important;
}

/* ── 終端式區塊標題（section_header 使用）────────── */
.tk-section {
  display: flex; align-items: baseline; gap: 0.55rem;
  margin: 0.4rem 0 0.15rem;
}
.tk-section .tick {
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 0.95rem;
  text-shadow: 0 0 10px rgba(240,160,60,0.45);
}
.tk-section .title {
  font-family: var(--font-hud);
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-0);
}
.tk-section .rule {
  flex: 1; height: 1px; align-self: center;
  background: linear-gradient(90deg, var(--line-hi), transparent);
}
.tk-subtitle {
  color: var(--text-1); font-size: 0.81rem;
  margin: 0 0 0.6rem 1.45rem;
}

/* ── 狀態膠囊與漲跌 chip ───────────────────────── */
.tk-badge {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.12rem 0.6rem;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  border: 1px solid var(--line);
  background: var(--bg-2);
}
.tk-badge .dot { width: 7px; height: 7px; border-radius: 50%; }
.tk-badge.running .dot { background: var(--warn); animation: tk-pulse 1.4s ease-in-out infinite; }
.tk-badge.success .dot { background: var(--down); }
.tk-badge.failed  .dot { background: var(--up); }
.tk-badge.pending .dot, .tk-badge.stopped .dot, .tk-badge.unknown .dot { background: var(--text-2); }
@keyframes tk-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(224,169,74,0.5); }
  50%      { box-shadow: 0 0 0 5px rgba(224,169,74,0); }
}
.tk-chip {
  display: inline-block;
  padding: 0.05rem 0.5rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 0.84rem;
  font-weight: 600;
}
.tk-chip.up   { color: var(--up);   background: var(--up-dim); }
.tk-chip.down { color: var(--down); background: var(--down-dim); }
.tk-chip.flat { color: var(--text-1); background: var(--bg-2); }

/* ── Mobile（< 768px）─────────────────────────── */
@media (max-width: 768px) {
  .main .block-container { padding-left: 0.75rem !important; padding-right: 0.75rem !important; }
  h1 { font-size: 1.4rem !important; }
  [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
}
</style>
"""

_STATUS_BADGE = {
    "running": ("🟡", "#E0A94A"),
    "success": ("🟢", "#2FA46C"),
    "failed": ("🔴", "#E5484D"),
    "pending": ("⚪", "#8E9BA8"),
    "stopped": ("⏹️", "#8E9BA8"),
    "unknown": ("❓", "#8E9BA8"),
}

_BADGE_CLASSES = {"running", "success", "failed", "pending", "stopped", "unknown"}


def inject_css() -> None:
    """注入暗色交易終端 CSS。"""
    st.markdown(_TERMINAL_CSS, unsafe_allow_html=True)


def status_badge_html(status: str) -> str:
    """狀態膠囊（running 會有脈動圓點）。"""
    key = status.lower() if status.lower() in _BADGE_CLASSES else "unknown"
    return f'<span class="tk-badge {key}"><span class="dot"></span>{status.upper()}</span>'


def pnl_chip_html(value: float | None, suffix: str = "") -> str:
    """漲跌 chip：正值紅、負值綠（台股慣例）、零或缺值灰。"""
    if value is None:
        return '<span class="tk-chip flat">—</span>'
    cls = "up" if value > 0 else ("down" if value < 0 else "flat")
    sign = "+" if value > 0 else ""
    return f'<span class="tk-chip {cls}">{sign}{value:,.2f}{suffix}</span>'


def section_header(title: str, subtitle: str = "") -> None:
    """渲染終端提示符式區塊標題（含次標題）。"""
    st.markdown(
        f'<div class="tk-section"><span class="tick">▮</span>'
        f'<span class="title">{title}</span><span class="rule"></span></div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(f'<p class="tk-subtitle">{subtitle}</p>', unsafe_allow_html=True)
