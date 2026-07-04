"""關注清單 widget：JSON 持久化＋快捷列＋加入/移出按鈕。"""

from __future__ import annotations

import json
import pathlib

import streamlit as st

_WATCHLIST_PATH = pathlib.Path(__file__).parents[3] / "data" / "ui_watchlist.json"

WatchItem = dict  # {"symbol": str, "name": str}

_STATE_KEY = "watchlist"


def _lookup_names(symbols: list[str]) -> dict[str, str]:
    """從 DB 查詢代號對應中文名稱。"""
    if not symbols:
        return {}
    try:
        from sqlalchemy.orm import Session

        from sentinel.domain.models import Stock
        from ui.services.db import get_engine

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
    _WATCHLIST_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _items() -> list[WatchItem]:
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = _load_watchlist()
    return st.session_state[_STATE_KEY]


def in_watchlist(symbol: str) -> bool:
    return symbol in {it["symbol"] for it in _items()}


def render_watchlist_bar(*, target_state_key: str = "sc_symbol") -> None:
    """關注清單快捷列：點擊即把代號帶入查詢輸入框。"""
    items = _items()
    if not items:
        return
    st.markdown("**關注清單**")
    cols = st.columns(min(len(items), 6))
    for i, item in enumerate(items):
        label = f"{item['name']} {item['symbol']}" if item.get("name") else item["symbol"]
        if cols[i % 6].button(label, key=f"wl_{item['symbol']}", width="stretch"):
            st.session_state[target_state_key] = item["symbol"]


def render_watchlist_toggle(container, symbol: str, name: str) -> None:
    """加入 / 移出關注清單按鈕（渲染在呼叫端提供的 container）。"""
    symbol = symbol.strip()
    if not symbol:
        return
    items = _items()
    if in_watchlist(symbol):
        if container.button("✕ 移出清單", key="wl_remove", width="stretch"):
            st.session_state[_STATE_KEY] = [it for it in items if it["symbol"] != symbol]
            _save_watchlist(st.session_state[_STATE_KEY])
            st.rerun()
    else:
        if container.button("＋ 加入清單", key="wl_add", width="stretch"):
            items.append({"symbol": symbol, "name": name.strip()})
            _save_watchlist(items)
            st.rerun()
