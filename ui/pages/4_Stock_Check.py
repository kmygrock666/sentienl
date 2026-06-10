"""Stock Check — 個股訊號規則判讀面板（v2）。"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.services.command_runner import get_store, launch_task, poll_task
from ui.services.command_specs import CHECK_STOCK
from ui.services.db import get_engine
from ui.services.parsers import parse_check_stock_output_v2

st.set_page_config(page_title="Stock Check | Sentinel", layout="wide")
inject_css()
st.title("🔎 Stock Check")
st.caption("個股訊號規則判讀面板 — 一眼看清觸發 / 未觸發 / 需盤中資料")

store = get_store()

# ── 關注清單（持久化） ────────────────────────────────────────────────────────
_WATCHLIST_PATH = pathlib.Path(__file__).parent.parent.parent / "data" / "ui_watchlist.json"

WatchItem = dict  # {"symbol": str, "name": str}


def _lookup_names(symbols: list[str]) -> dict[str, str]:
    """從 DB 查詢代號對應中文名稱。"""
    if not symbols:
        return {}
    try:
        from sqlalchemy.orm import Session
        from sentinel.models import Stock
        engine = get_engine()
        with Session(engine) as s:
            rows = s.query(Stock.symbol, Stock.name).filter(Stock.symbol.in_(symbols)).all()
        return {r.symbol: r.name or "" for r in rows}
    except Exception:
        return {}


def _load_watchlist() -> list[WatchItem]:
    if not _WATCHLIST_PATH.exists():
        return []
    try:
        raw = json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
        # backward-compat: old format was list[str]
        if raw and isinstance(raw[0], str):
            items: list[WatchItem] = [{"symbol": s, "name": ""} for s in raw]
        else:
            items = raw
        # 補齊名稱空白的項目
        missing = [it["symbol"] for it in items if not it.get("name")]
        if missing:
            name_map = _lookup_names(missing)
            changed = False
            for it in items:
                if not it.get("name") and it["symbol"] in name_map:
                    it["name"] = name_map[it["symbol"]]
                    changed = True
            if changed:
                _save_watchlist(items)
        return items
    except Exception:
        return []


def _save_watchlist(items: list[WatchItem]) -> None:
    _WATCHLIST_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _wl_symbols(items: list[WatchItem]) -> set[str]:
    return {it["symbol"] for it in items}


if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = _load_watchlist()

section_header("個股訊號檢驗", "輸入股票代號查看各訊號觸發狀況")

# ── 關注清單快捷列 ────────────────────────────────────────────────────────────
watchlist: list[WatchItem] = st.session_state["watchlist"]
if watchlist:
    st.markdown("**關注清單**")
    cols = st.columns(min(len(watchlist), 6))
    for i, item in enumerate(watchlist):
        label = f"{item['name']} {item['symbol']}" if item.get("name") else item["symbol"]
        if cols[i % 6].button(label, key=f"wl_{item['symbol']}", use_container_width=True):
            st.session_state["sc_symbol"] = item["symbol"]

# ── 表單 ────────────────────────────────────────────────────────────────────
with st.form("check_stock_form"):
    c1, c2 = st.columns(2)
    symbol = c1.text_input("股票代號 *", key="sc_symbol", placeholder="例：2330")
    check_date = c2.date_input("交易日（留空=最新）", value=None)

    with st.expander("進階選項"):
        signal_path = st.text_input("訊號設定檔路徑（留空=預設）", placeholder="config/signals.json")
        dataset_path = st.text_input("資料集路徑（留空=預設）")

    preview_params: dict = {}
    if symbol:
        preview_params["symbol"] = symbol.strip()
    if check_date:
        preview_params["date"] = check_date.isoformat()
    render_command_preview(CHECK_STOCK, preview_params)
    submitted = st.form_submit_button("▶ 執行 check-stock", use_container_width=True)

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

# ── 結果面板 ────────────────────────────────────────────────────────────────
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

# ── 摘要列 ──────────────────────────────────────────────────────────────────
if meta.get("symbol") or meta.get("name"):
    title_col, wl_col = st.columns([5, 1])
    title_col.markdown(
        f"### {meta.get('name', '')} {meta.get('symbol', '')}　"
        f"<span style='color:var(--text-1);font-size:0.9rem'>檢驗日：{meta.get('date','—')}</span>",
        unsafe_allow_html=True,
    )
    cur_sym = meta.get("symbol", "").strip()
    cur_name = meta.get("name", "").strip()
    if cur_sym:
        in_wl = cur_sym in _wl_symbols(st.session_state["watchlist"])
        if in_wl:
            if wl_col.button("✕ 移出清單", key="wl_remove", use_container_width=True):
                st.session_state["watchlist"] = [
                    it for it in st.session_state["watchlist"] if it["symbol"] != cur_sym
                ]
                _save_watchlist(st.session_state["watchlist"])
                st.rerun()
        else:
            if wl_col.button("＋ 加入清單", key="wl_add", use_container_width=True):
                st.session_state["watchlist"].append({"symbol": cur_sym, "name": cur_name})
                _save_watchlist(st.session_state["watchlist"])
                st.rerun()

sm1, sm2, sm3, sm4 = st.columns(4)
sm1.metric("✅ 做多觸發", parsed["triggered_count"])
sm2.metric("🔴 警示觸發", parsed["warning_count"])
sm3.metric("❌ 未觸發", parsed["not_triggered_count"])
sm4.metric("⚙️ 需盤中資料", parsed["needs_intraday_count"])

st.divider()

# ── 篩選器 ──────────────────────────────────────────────────────────────────
FILTERS = ["全部", "只看觸發", "只看警示", "只看未觸發", "只看需盤中"]
flt = st.radio("篩選", FILTERS, horizontal=True, label_visibility="collapsed")


def _filter(sig: dict) -> bool:
    if flt == "只看觸發":
        return sig["status"] == "triggered" and sig["direction"] == "long"
    if flt == "只看警示":
        return sig["status"] == "triggered" and sig["direction"] == "warning"
    if flt == "只看未觸發":
        return sig["status"] == "not_triggered"
    if flt == "只看需盤中":
        return sig["status"] == "needs_intraday"
    return True


# Sort: triggered long > triggered warning > not_triggered > needs_intraday
def _sort_key(sig: dict) -> int:
    if sig["status"] == "triggered" and sig["direction"] == "long":
        return 0
    if sig["status"] == "triggered" and sig["direction"] == "warning":
        return 1
    if sig["status"] == "not_triggered":
        return 2
    return 3


visible = sorted([s for s in signals if _filter(s)], key=_sort_key)

if not visible:
    st.info("此篩選條件無符合訊號")

# ── 訊號卡片 ────────────────────────────────────────────────────────────────
_DIR_LABEL = {"long": "做多進場", "warning": "警示 / 出場", "intraday": "需盤中資料"}
_STATUS_CSS = {
    "triggered_long":    ("border-left:3px solid #3FA66B; background:#1a2e22;", "✅", "#3FA66B"),
    "triggered_warning": ("border-left:3px solid #E0A94A; background:#2e2a1a;", "🔴", "#E0A94A"),
    "not_triggered":     ("border-left:3px solid #4a5568; background:#1a1f24;", "❌", "#9AA6B2"),
    "needs_intraday":    ("border-left:3px solid #3D6E8F; background:#1a222e;", "⚙️", "#3D6E8F"),
}


def _card_key(sig: dict) -> str:
    if sig["status"] == "triggered" and sig["direction"] == "long":
        return "triggered_long"
    if sig["status"] == "triggered" and sig["direction"] == "warning":
        return "triggered_warning"
    if sig["status"] == "needs_intraday":
        return "needs_intraday"
    return "not_triggered"


for idx, sig in enumerate(visible):
    ck = _card_key(sig)
    css, icon, color = _STATUS_CSS[ck]
    dir_label = _DIR_LABEL.get(sig["direction"], sig["direction"])
    cond_summary = f"{sig['passed_count']}/{sig['total_count']} 條件通過" if sig["total_count"] > 0 else ""

    with st.container():
        st.markdown(
            f'<div style="padding:0.6rem 0.8rem; border-radius:4px; margin-bottom:0.5rem; {css}">'
            f'<span style="font-size:1.1rem">{icon}</span> '
            f'<strong style="color:{color}">{sig["name"]}</strong>'
            f'<span style="color:var(--text-1);font-size:0.78rem;margin-left:0.5rem">'
            f'[{dir_label}]</span>'
            + (f'<span style="color:var(--text-1);font-size:0.78rem;margin-left:0.5rem">'
               f'· {cond_summary}</span>' if cond_summary else '')
            + (f'<span style="color:var(--text-1);font-size:0.78rem;margin-left:0.5rem">'
               f'— {sig["source_rule"]}</span>' if sig.get("source_rule") else '')
            + '</div>',
            unsafe_allow_html=True,
        )

        # Conditions detail (for triggered and not_triggered)
        if sig["conditions"]:
            failed = [c for c in sig["conditions"] if not c["passed"]]
            passed = [c for c in sig["conditions"] if c["passed"]]

            if sig["status"] == "triggered":
                # Show all conditions for triggered
                with st.expander(f"條件明細（{sig['passed_count']}/{sig['total_count']} 通過）"):
                    for c in sig["conditions"]:
                        mark = "✅" if c["passed"] else "  "
                        st.markdown(
                            f'<span style="font-family:monospace;font-size:0.82rem;color:{"#3FA66B" if c["passed"] else "#9AA6B2"}">'
                            f'{mark} {c["text"]}</span>',
                            unsafe_allow_html=True,
                        )
            else:
                # For not_triggered, show failed conditions prominently
                if failed:
                    fail_text = "；".join(c["text"] for c in failed[:3])
                    st.markdown(
                        f'<div style="margin-left:1rem;color:#9AA6B2;font-size:0.80rem">'
                        f'未達條件：{fail_text}'
                        + (" 等..." if len(failed) > 3 else "")
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                    if len(sig["conditions"]) > 3:
                        with st.expander("展開全部條件"):
                            for c in sig["conditions"]:
                                mark = "✅" if c["passed"] else "✗"
                                st.markdown(
                                    f'<span style="font-family:monospace;font-size:0.82rem;color:{"#3FA66B" if c["passed"] else "#D84B4B"}">'
                                    f'{mark} {c["text"]}</span>',
                                    unsafe_allow_html=True,
                                )

        # Intraday reason
        if sig["status"] == "needs_intraday" and sig.get("reason"):
            st.markdown(
                f'<div style="margin-left:1rem;color:#3D6E8F;font-size:0.80rem">原因：{sig["reason"]}</div>',
                unsafe_allow_html=True,
            )

st.divider()

# ── 快捷操作 ────────────────────────────────────────────────────────────────
section_header("快捷操作")
qa1, qa2, qa3 = st.columns(3)
if meta.get("date"):
    qa1.page_link("pages/3_Daily_Scan.py", label=f"📊 帶入 {meta['date']} 到 Daily Scan", use_container_width=True)
if meta.get("symbol"):
    qa2.page_link("pages/7_Inspect.py", label=f"🔍 前往 Inspect 查看{meta['symbol']}", use_container_width=True)

# Copy params
import json as _json
params_copy = {}
if meta.get("symbol"):
    params_copy["symbol"] = meta["symbol"]
if meta.get("date"):
    params_copy["date"] = meta["date"]
qa3.code(_json.dumps(params_copy, ensure_ascii=False), language="json")

st.divider()

# ── 完整原始輸出（debug）─────────────────────────────────────────────────────
with st.expander("完整原始輸出（debug）", expanded=not bool(signals)):
    render_log_tail(task.stdout_tail, task.stderr_tail)
