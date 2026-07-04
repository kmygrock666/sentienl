"""結果表格元件：高密度資料呈現與 CSV 下載。"""

from __future__ import annotations

import json
import pathlib

import pandas as pd
import streamlit as st

_STRATEGIES_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "strategies.json"


@st.cache_data(show_spinner=False)
def _load_strategy_names() -> dict[str, str]:
    """載入策略名稱對照表 strategy_id → name。"""
    try:
        raw = json.loads(_STRATEGIES_PATH.read_text(encoding="utf-8"))
        result = {}
        for direction in ("long_strategies", "short_strategies"):
            for s in raw.get(direction, []):
                result[s["strategy_id"]] = s.get("name", s["strategy_id"])
        return result
    except Exception:
        return {}


def render_df(
    df: pd.DataFrame,
    title: str = "",
    download_label: str = "下載 CSV",
    download_filename: str = "export.csv",
    height: int = 400,
    hide_index: bool = True,
) -> None:
    """顯示 DataFrame，附帶下載按鈕。"""
    if title:
        st.markdown(f"**{title}** — {len(df)} 筆")
    if df.empty:
        st.info("無資料")
        return

    st.dataframe(df, width="stretch", hide_index=hide_index, height=height)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(download_label, csv, file_name=download_filename, mime="text/csv")


_DIRECTION_BADGE = {
    "long": '<span style="color:#D84B4B;font-weight:600;font-size:0.78rem">LONG</span>',
    "short": '<span style="color:#3FA66B;font-weight:600;font-size:0.78rem">SHORT</span>',
    "": '<span style="color:#9AA6B2;font-size:0.78rem">—</span>',
}


def render_scan_results(df: pd.DataFrame) -> None:
    """渲染掃描結果表格（帶語義顏色、direction badge、TradingView 匯出）。"""
    if df.empty:
        st.info("此條件無結果")
        return

    # 統計摘要
    total = len(df)
    long_cnt = (
        (df.get("direction", pd.Series(dtype=str)) == "long").sum()
        if "direction" in df.columns
        else 0
    )
    short_cnt = (
        (df.get("direction", pd.Series(dtype=str)) == "short").sum()
        if "direction" in df.columns
        else 0
    )
    sm1, sm2, sm3 = st.columns(3)
    sm1.metric("命中總數", total)
    sm2.metric("做多", int(long_cnt))
    sm3.metric("做空", int(short_cnt))

    # 策略分佈
    if "strategy_id" in df.columns:
        strategy_names = _load_strategy_names()
        strat_df = (
            df.groupby("strategy_id")
            .size()
            .reset_index(name="命中數")
            .sort_values("命中數", ascending=False)
        )
        strat_df.insert(
            1,
            "策略名稱",
            strat_df["strategy_id"].map(lambda sid: strategy_names.get(sid, sid)),
        )
        strat_df = strat_df.rename(columns={"strategy_id": "策略 ID"})
        with st.expander(f"📊 策略分佈（共 {len(strat_df)} 個策略命中）", expanded=True):
            st.dataframe(strat_df, hide_index=True, width="stretch")

    # 顯示欄位順序（含 direction）
    preferred_cols = [
        "trading_date",
        "direction",
        "market",
        "symbol",
        "name",
        "industry",
        "strategy_id",
        "score",
        "close",
    ]
    display = df[[c for c in preferred_cols if c in df.columns]].copy()
    # industry 全空時不顯示（資料尚未同步）
    if "industry" in display.columns and display["industry"].fillna("").eq("").all():
        display = display.drop(columns=["industry"])

    if "score" in display.columns:
        display["score"] = display["score"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) and x is not None else "—"
        )
    if "close" in display.columns:
        display["close"] = display["close"].apply(
            lambda x: f"{x:.2f}" if pd.notna(x) and x is not None else "—"
        )

    st.dataframe(display, width="stretch", hide_index=True, height=420)

    dl1, dl2 = st.columns(2)

    # CSV 下載
    csv = df.to_csv(index=False).encode("utf-8-sig")
    dl1.download_button(
        "⬇ 下載 CSV",
        csv,
        file_name="scan_results.csv",
        mime="text/csv",
        width="stretch",
    )

    # TradingView watchlist 匯出
    if "symbol" in df.columns and "market" in df.columns:
        suffix_map = {"TWSE": "TW", "TPEX": "TWO"}
        tv_lines = []
        for _, row in df.iterrows():
            suffix = suffix_map.get(str(row.get("market", "")), "TW")
            tv_lines.append(f"{row['symbol']}.{suffix}")
        tv_txt = "\n".join(tv_lines)
        dl2.download_button(
            "📺 匯出 TradingView 清單",
            tv_txt.encode("utf-8"),
            file_name="tradingview.txt",
            mime="text/plain",
            width="stretch",
        )
