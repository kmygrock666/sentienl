"""Stock Check — 個股資訊儀表板（v3）。

漸進式揭露：首屏只保留查詢表單與核心摘要（收盤價、綜合研判、外資連買、
觸發統計）；訊號明細、法人籌碼與工具各自收在獨立 Tab。
渲染邏輯拆在 ui/components/stock_check/ 的四個 widget。
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.components.stock_check.institutional import fetch_flow, render_institutional_panel
from ui.components.stock_check.signal_cards import render_signal_cards
from ui.components.stock_check.summary import render_summary_hero
from ui.components.stock_check.watchlist import render_watchlist_bar, render_watchlist_toggle
from ui.services.command_runner import launch_task, poll_task
from ui.services.command_specs import CHECK_STOCK
from ui.services.db import get_engine
from ui.services.parsers import parse_check_stock_output_v2
from ui.services.queries import load_symbol_prices

st.set_page_config(page_title="Stock Check | Sentinel", layout="wide")
inject_css()
st.title("🔎 Stock Check")
st.caption("個股資訊儀表板 — 核心指標一眼看，明細收在分頁")

# ── 查詢面板 ────────────────────────────────────────────────────────────────
section_header("個股訊號檢驗", "輸入股票代號查看各訊號觸發狀況")
render_watchlist_bar(target_state_key="sc_symbol")

with st.form("check_stock_form"):
    c1, c2 = st.columns(2)
    symbol = c1.text_input("股票代號 *", key="sc_symbol", placeholder="例：2330")
    check_date = c2.date_input("交易日（留空=最新）", value=None)

    with st.expander("進階選項"):
        signal_path = st.text_input(
            "訊號設定檔路徑（留空=預設）", placeholder="config/signals.json"
        )
        dataset_path = st.text_input("資料集路徑（留空=預設）")

    preview_params: dict = {}
    if symbol:
        preview_params["symbol"] = symbol.strip()
    if check_date:
        preview_params["date"] = check_date.isoformat()
    render_command_preview(CHECK_STOCK, preview_params)
    submitted = st.form_submit_button("▶ 執行 check-stock", width="stretch")

if submitted:
    if not symbol or not symbol.strip():
        st.error("請輸入股票代號")
    else:
        run_params: dict = {"symbol": symbol.strip()}
        if check_date:
            run_params["date"] = check_date.isoformat()
        if signal_path:
            run_params["signal-path"] = signal_path
        if dataset_path:
            run_params["dataset-path"] = dataset_path
        task = launch_task(CHECK_STOCK, run_params)
        st.session_state["check_stock_task"] = task.task_id
        st.rerun()

# ── 任務狀態 ────────────────────────────────────────────────────────────────
if "check_stock_task" not in st.session_state:
    st.stop()

task = poll_task(st.session_state["check_stock_task"])
st.markdown(
    status_badge_html(task.status) + f" · 耗時 {task.duration_str}",
    unsafe_allow_html=True,
)

if not task.stdout_tail:
    if task.stderr_tail:
        render_log_tail("", task.stderr_tail)
    st.stop()

parsed = parse_check_stock_output_v2(task.stdout_tail, task.stderr_tail)
meta = parsed["meta"]
signals = parsed["signals"]

# ── 標題列＋關注清單切換 ──────────────────────────────────────────────────────
if meta.get("symbol") or meta.get("name"):
    title_col, wl_col = st.columns([5, 1])
    title_col.markdown(
        f"### {meta.get('name', '')} {meta.get('symbol', '')}　"
        f"<span style='color:var(--text-1);font-size:0.9rem'>檢驗日：{meta.get('date','—')}</span>",
        unsafe_allow_html=True,
    )
    render_watchlist_toggle(wl_col, meta.get("symbol", ""), meta.get("name", ""))

# ── 核心摘要（首屏唯一的數據區塊）────────────────────────────────────────────
_symbol = (meta.get("symbol") or symbol or "").strip()
_market = None
_flow_df = None
_price_df = None
if _symbol:
    # DB 離線或 dataset 缺檔時首屏仍顯示訊號統計
    with contextlib.suppress(Exception):
        _market, _flow_df = fetch_flow(get_engine(), _symbol)
    with contextlib.suppress(Exception):
        _price_df = load_symbol_prices(_symbol, days=120, market=_market)

render_summary_hero(parsed, price_df=_price_df, flow_df=_flow_df)

# ── 明細分頁（漸進式揭露）────────────────────────────────────────────────────
tab_signals, tab_flow, tab_tools = st.tabs(["📋 訊號明細", "🏦 法人籌碼", "🛠 工具與原始輸出"])

with tab_signals:
    render_signal_cards(signals)

with tab_flow:
    if not _symbol:
        st.info("無股票代號可查詢")
    else:
        try:
            render_institutional_panel(
                get_engine(),
                _symbol,
                market=_market,
                flow_df=_flow_df,
                title=f"{meta.get('name', '')} {_symbol}".strip(),
            )
        except Exception as exc:
            st.warning(f"法人籌碼查詢失敗：{exc}")

with tab_tools:
    section_header("快捷操作")
    qa1, qa2, qa3 = st.columns(3)
    if meta.get("date"):
        qa1.page_link(
            "pages/3_Daily_Scan.py",
            label=f"📊 帶入 {meta['date']} 到 Daily Scan",
            width="stretch",
        )
    if meta.get("symbol"):
        qa2.page_link(
            "pages/7_Inspect.py",
            label=f"🔍 前往 Inspect 查看{meta['symbol']}",
            width="stretch",
        )
    params_copy = {}
    if meta.get("symbol"):
        params_copy["symbol"] = meta["symbol"]
    if meta.get("date"):
        params_copy["date"] = meta["date"]
    qa3.code(json.dumps(params_copy, ensure_ascii=False), language="json")

    with st.expander("完整原始輸出（debug）", expanded=not bool(signals)):
        render_log_tail(task.stdout_tail, task.stderr_tail)
