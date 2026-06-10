"""Financial Calendar — 重要金融日曆（月曆格式）。

事件涵蓋：台指期結算、四巫日、FOMC、美國 CPI / NFP / PCE。
"""

from __future__ import annotations

import calendar as _cal
import pathlib
import sys
from datetime import date, timedelta
from typing import NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ui.components.layout import inject_css

st.set_page_config(page_title="Financial Calendar | Sentinel", layout="wide")
inject_css()

# ── 事件定義 ────────────────────────────────────────────────────────────────

CATEGORY_CFG: dict[str, dict] = {
    "tw_futures": {"label": "台指期月結算", "icon": "🇹🇼", "color": "#3b82f6"},
    "witching": {"label": "四巫日", "icon": "🎭", "color": "#8b5cf6"},
    "fomc": {"label": "FOMC 利率決議", "icon": "🏛️", "color": "#ef4444"},
    "ecb": {"label": "ECB 利率決議", "icon": "🇪🇺", "color": "#6366f1"},
    "boj": {"label": "日銀利率決議", "icon": "🏯", "color": "#f43f5e"},
    "us_cpi": {"label": "美國 CPI", "icon": "📊", "color": "#f59e0b"},
    "us_nfp": {"label": "美國 NFP", "icon": "📈", "color": "#10b981"},
    "us_pce": {"label": "美國 PCE", "icon": "📉", "color": "#f97316"},
    "us_gdp": {"label": "美國 GDP", "icon": "🏗️", "color": "#14b8a6"},
    "msci": {"label": "MSCI 再平衡", "icon": "📐", "color": "#64748b"},
    "global": {"label": "全球重大事件", "icon": "🌐", "color": "#a855f7"},
}


class Event(NamedTuple):
    date: date
    category: str
    name: str
    note: str = ""


def _nth_weekday(year: int, month: int, n: int, weekday: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last_day = _cal.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


# FOMC 2025 actual + 2026 estimated
_FOMC: list[tuple[date, str]] = [
    (date(2025, 1, 29), ""),
    (date(2025, 3, 19), ""),
    (date(2025, 5, 7), ""),
    (date(2025, 6, 18), ""),
    (date(2025, 7, 30), ""),
    (date(2025, 9, 17), ""),
    (date(2025, 10, 29), ""),
    (date(2025, 12, 10), ""),
    (date(2026, 1, 29), "預估"),
    (date(2026, 3, 18), "預估"),
    (date(2026, 5, 7), "預估"),
    (date(2026, 6, 18), "預估"),
    (date(2026, 7, 30), "預估"),
    (date(2026, 9, 17), "預估"),
    (date(2026, 10, 29), "預估"),
    (date(2026, 12, 10), "預估"),
]

# CPI 2025 actual BLS + 2026 approximate
_US_CPI: list[tuple[date, str]] = [
    (date(2025, 1, 15), ""),
    (date(2025, 2, 12), ""),
    (date(2025, 3, 12), ""),
    (date(2025, 4, 10), ""),
    (date(2025, 5, 13), ""),
    (date(2025, 6, 11), ""),
    (date(2025, 7, 15), ""),
    (date(2025, 8, 12), ""),
    (date(2025, 9, 10), ""),
    (date(2025, 10, 15), ""),
    (date(2025, 11, 13), ""),
    (date(2025, 12, 10), ""),
    (date(2026, 1, 14), "預估"),
    (date(2026, 2, 11), "預估"),
    (date(2026, 3, 11), "預估"),
    (date(2026, 4, 10), "預估"),
    (date(2026, 5, 13), "預估"),
    (date(2026, 6, 10), "預估"),
    (date(2026, 7, 15), "預估"),
    (date(2026, 8, 12), "預估"),
    (date(2026, 9, 10), "預估"),
    (date(2026, 10, 14), "預估"),
    (date(2026, 11, 12), "預估"),
    (date(2026, 12, 10), "預估"),
]

# ECB 2025 actual + 2026 estimated (8 meetings/year, Thursdays)
_ECB: list[tuple[date, str]] = [
    (date(2025, 1, 30), ""),
    (date(2025, 3, 6), ""),
    (date(2025, 4, 17), ""),
    (date(2025, 6, 5), ""),
    (date(2025, 7, 24), ""),
    (date(2025, 9, 11), ""),
    (date(2025, 10, 30), ""),
    (date(2025, 12, 18), ""),
    (date(2026, 1, 29), "預估"),
    (date(2026, 3, 5), "預估"),
    (date(2026, 4, 23), "預估"),
    (date(2026, 6, 4), "預估"),
    (date(2026, 7, 23), "預估"),
    (date(2026, 9, 10), "預估"),
    (date(2026, 10, 29), "預估"),
    (date(2026, 12, 17), "預估"),
]

# BOJ 2025 actual + 2026 estimated (8 meetings/year)
_BOJ: list[tuple[date, str]] = [
    (date(2025, 1, 24), ""),
    (date(2025, 3, 19), ""),
    (date(2025, 5, 1), ""),
    (date(2025, 6, 17), ""),
    (date(2025, 7, 31), ""),
    (date(2025, 9, 19), ""),
    (date(2025, 10, 29), ""),
    (date(2025, 12, 19), ""),
    (date(2026, 1, 23), "預估"),
    (date(2026, 3, 18), "預估"),
    (date(2026, 4, 30), "預估"),
    (date(2026, 6, 16), "預估"),
    (date(2026, 7, 30), "預估"),
    (date(2026, 9, 17), "預估"),
    (date(2026, 10, 28), "預估"),
    (date(2026, 12, 17), "預估"),
]

# US GDP advance estimate (quarterly, BEA — last week of Jan/Apr/Jul/Oct)
_US_GDP: list[tuple[date, str, str]] = [
    (date(2025, 1, 29), "", "Q3 2024 第三次"),
    (date(2025, 4, 30), "", "Q1 2025 初值"),
    (date(2025, 7, 30), "", "Q2 2025 初值"),
    (date(2025, 10, 29), "", "Q3 2025 初值"),
    (date(2026, 1, 28), "預估", "Q4 2025 初值"),
    (date(2026, 4, 29), "預估", "Q1 2026 初值"),
    (date(2026, 7, 29), "預估", "Q2 2026 初值"),
    (date(2026, 10, 28), "預估", "Q3 2026 初值"),
]

# Global major events (Jackson Hole, Davos, G7, G20)
_GLOBAL_EVENTS: list[tuple[date, str, str]] = [
    # Davos / WEF World Economic Forum (mid-January)
    (date(2025, 1, 20), "", "達沃斯論壇 (WEF)"),
    (date(2026, 1, 19), "預估", "達沃斯論壇 (WEF)"),
    # G7 Summit 2025: Kananaskis, Canada (Jun 15-17); 2026: Italy (est.)
    (date(2025, 6, 15), "", "G7 峰會"),
    (date(2026, 5, 31), "預估", "G7 峰會"),
    # G20 Summit 2025: Johannesburg, South Africa (Nov); 2026: est.
    (date(2025, 11, 18), "", "G20 峰會"),
    (date(2026, 11, 17), "預估", "G20 峰會"),
    # Jackson Hole Annual Economic Symposium (late August)
    (date(2025, 8, 21), "", "傑克遜霍爾年會"),
    (date(2026, 8, 27), "預估", "傑克遜霍爾年會"),
]


def _build_events_map(year: int, month: int) -> dict[date, list[Event]]:
    """建立指定月份的 {date: [Event]} 對照表。"""
    first = date(year, month, 1)
    last_day = _cal.monthrange(year, month)[1]
    last = date(year, month, last_day)

    events: list[Event] = []

    # 台指期月結算（第 3 個週三）
    d = _nth_weekday(year, month, 3, 2)
    if first <= d <= last:
        events.append(Event(d, "tw_futures", "台指期月結算"))

    # 四巫日（3/6/9/12 月第 3 個週五）
    if month in (3, 6, 9, 12):
        d = _nth_weekday(year, month, 3, 4)
        events.append(Event(d, "witching", "四巫日"))

    # NFP（第 1 個週五）
    nfp = _nth_weekday(year, month, 1, 4)
    events.append(Event(nfp, "us_nfp", "美國 NFP"))

    # PCE（月底最後週五，近似）
    pce = _last_weekday(year, month, 4)
    events.append(Event(pce, "us_pce", "美國 PCE", "近似"))

    # MSCI 季度再平衡（2月/5月/8月/11月第3個週五）
    if month in (2, 5, 8, 11):
        msci_d = _nth_weekday(year, month, 3, 4)
        events.append(Event(msci_d, "msci", "MSCI 季度再平衡"))

    # FOMC / CPI / ECB / BOJ / GDP / 全球重大事件（從硬編碼清單中篩選本月）
    for d, note in _FOMC:
        if d.year == year and d.month == month:
            events.append(Event(d, "fomc", "FOMC 利率決議", note))
    for d, note in _US_CPI:
        if d.year == year and d.month == month:
            events.append(Event(d, "us_cpi", "美國 CPI", note))
    for d, note in _ECB:
        if d.year == year and d.month == month:
            events.append(Event(d, "ecb", "ECB 利率決議", note))
    for d, note in _BOJ:
        if d.year == year and d.month == month:
            events.append(Event(d, "boj", "日銀利率決議", note))
    for d, note, name in _US_GDP:
        if d.year == year and d.month == month:
            events.append(Event(d, "us_gdp", f"美國 GDP（{name}）", note))
    for d, note, name in _GLOBAL_EVENTS:
        if d.year == year and d.month == month:
            events.append(Event(d, "global", name, note))

    result: dict[date, list[Event]] = {}
    for ev in events:
        result.setdefault(ev.date, []).append(ev)
    return result


def _render_calendar_html(
    year: int,
    month: int,
    events_map: dict[date, list[Event]],
    enabled: dict[str, bool],
    today: date,
) -> str:
    weeks = _cal.monthcalendar(year, month)  # [[Mon…Sun], …], 0 = padding day
    headers = ["一", "二", "三", "四", "五", "六", "日"]

    rows = []
    for week in weeks:
        cells = []
        for col, day in enumerate(week):
            is_weekend = col >= 5
            if day == 0:
                cells.append(
                    '<td style="background:#0c1018;border:1px solid #1e2530;'
                    'padding:6px;height:95px"></td>'
                )
                continue

            d = date(year, month, day)
            day_events = [e for e in events_map.get(d, []) if enabled.get(e.category, True)]
            is_today = d == today
            is_past = d < today

            # Cell background & border
            if is_today:
                bg, border = "#0f2040", "border:2px solid #3b82f6"
            elif is_past and is_weekend:
                bg, border = "#0d1118", "border:1px solid #1a2030"
            elif is_past:
                bg, border = "#10141e", "border:1px solid #1a2030"
            elif is_weekend:
                bg, border = "#12161f", "border:1px solid #252d3d"
            else:
                bg, border = "#151b28", "border:1px solid #252d3d"

            dim = "opacity:0.55;" if is_past else ""

            # Day number badge
            if is_today:
                num_html = (
                    f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                    f"width:24px;height:24px;background:#3b82f6;border-radius:50%;"
                    f'font-size:0.8rem;font-weight:700;color:#fff">{day}</span>'
                )
            else:
                num_color = "#505870" if is_past else "#6B7588" if is_weekend else "#C8D0DC"
                num_html = f'<span style="font-size:0.82rem;font-weight:600;color:{num_color}">{day}</span>'

            # Event badges
            badges = []
            for ev in day_events:
                cfg = CATEGORY_CFG[ev.category]
                note_part = (
                    f' <span style="opacity:0.65;font-size:0.62rem">({ev.note})</span>'
                    if ev.note
                    else ""
                )
                badges.append(
                    f'<div title="{ev.name}{" ("+ev.note+")" if ev.note else ""}" '
                    f'style="margin-top:3px;padding:2px 5px;border-radius:3px;'
                    f'background:{cfg["color"]}20;border-left:2px solid {cfg["color"]};'
                    f'font-size:0.68rem;color:{cfg["color"]};white-space:nowrap;'
                    f'overflow:hidden;text-overflow:ellipsis;">'
                    f'{cfg["icon"]} {ev.name}{note_part}</div>'
                )

            cells.append(
                f'<td style="vertical-align:top;padding:6px 7px;{border};'
                f'background:{bg};{dim}height:95px">'
                f'{num_html}{"".join(badges)}</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    header_cells = "".join(
        f'<th style="text-align:center;padding:10px 4px;background:#0e1420;'
        f'color:{"#5a6070" if i>=5 else "#8090a8"};font-size:0.82rem;'
        f'font-weight:500;border:1px solid #1e2530">{h}</th>'
        for i, h in enumerate(headers)
    )

    return (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


# ── Session state：目前顯示月份 ─────────────────────────────────────────────
today = date.today()

if "cal_year" not in st.session_state:
    st.session_state["cal_year"] = today.year
if "cal_month" not in st.session_state:
    st.session_state["cal_month"] = today.month


def _prev_month() -> None:
    if st.session_state["cal_month"] == 1:
        st.session_state["cal_year"] -= 1
        st.session_state["cal_month"] = 12
    else:
        st.session_state["cal_month"] -= 1


def _next_month() -> None:
    if st.session_state["cal_month"] == 12:
        st.session_state["cal_year"] += 1
        st.session_state["cal_month"] = 1
    else:
        st.session_state["cal_month"] += 1


def _goto_today() -> None:
    st.session_state["cal_year"] = today.year
    st.session_state["cal_month"] = today.month


# ── Sidebar：篩選器 ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 顯示事件")
    enabled: dict[str, bool] = {
        cat: st.checkbox(
            f"{cfg['icon']} {cfg['label']}",
            value=True,
            key=f"cal_{cat}",
        )
        for cat, cfg in CATEGORY_CFG.items()
    }
    st.divider()
    st.button("回到今天", on_click=_goto_today, use_container_width=True)

# ── 導航列 ─────────────────────────────────────────────────────────────────
cur_year: int = st.session_state["cal_year"]
cur_month: int = st.session_state["cal_month"]
month_names = [
    "一月",
    "二月",
    "三月",
    "四月",
    "五月",
    "六月",
    "七月",
    "八月",
    "九月",
    "十月",
    "十一月",
    "十二月",
]

nav_l, nav_title, nav_r = st.columns([1, 6, 1])
nav_l.button("◀", on_click=_prev_month, use_container_width=True, key="btn_prev")
nav_title.markdown(
    f'<h2 style="text-align:center;margin:0;padding:6px 0;font-size:1.4rem">'
    f"{cur_year} 年 {month_names[cur_month-1]}</h2>",
    unsafe_allow_html=True,
)
nav_r.button("▶", on_click=_next_month, use_container_width=True, key="btn_next")

# ── 圖例（每行 6 欄，多行排列）─────────────────────────────────────────────
_leg_items = list(CATEGORY_CFG.items())
_LEG_COLS = 6
for row_start in range(0, len(_leg_items), _LEG_COLS):
    row_items = _leg_items[row_start : row_start + _LEG_COLS]
    leg_cols = st.columns(_LEG_COLS)
    for i, (cat, cfg) in enumerate(row_items):
        leg_cols[i].markdown(
            f'<div style="display:flex;align-items:center;gap:5px;font-size:0.78rem;color:#8090a8">'
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
            f'background:{cfg["color"]}"></span>{cfg["icon"]} {cfg["label"]}</div>',
            unsafe_allow_html=True,
        )

st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)

# ── 月曆格子 ───────────────────────────────────────────────────────────────
events_map = _build_events_map(cur_year, cur_month)
st.markdown(
    _render_calendar_html(cur_year, cur_month, events_map, enabled, today),
    unsafe_allow_html=True,
)

st.divider()

# ── 本月事件清單（折疊） ───────────────────────────────────────────────────
month_events: list[Event] = sorted(
    [ev for evs in events_map.values() for ev in evs if enabled.get(ev.category, True)],
    key=lambda e: e.date,
)

with st.expander(f"本月事件清單（{len(month_events)} 件）"):
    if month_events:
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        df = pd.DataFrame(
            [
                {
                    "日期": e.date.strftime("%m/%d"),
                    "星期": weekday_map[e.date.weekday()],
                    "類型": CATEGORY_CFG[e.category]["label"],
                    "事件": e.name,
                    "備註": e.note,
                }
                for e in month_events
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ 下載 CSV",
            df.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"calendar_{cur_year}_{cur_month:02d}.csv",
            mime="text/csv",
        )
    else:
        st.info("本月無符合條件的事件")
