"""核心摘要 widget：首屏只保留最重要的四件事 —
最新收盤價、綜合研判燈號、外資連買天數、訊號觸發統計。"""

from __future__ import annotations

import html
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

VERDICT_NONE = ("❌ 目前無訊號觸發，不符合進場條件", "#9AA6B2")
VERDICT_WARNING_ONLY = ("⚠️ 僅有警示訊號，建議出場或觀望", "#E0A94A")
VERDICT_STRONG = ("✅ 多個做多訊號確認，訊號強度佳", "#3FA66B")
VERDICT_MIXED = ("⚡ 做多與警示並存，需謹慎評估風險", "#E0A94A")
VERDICT_SINGLE = ("☑️ 單一做多訊號觸發，仍需觀察更多確認條件", "#3D6E8F")


def compute_verdict(triggered_count: int, warning_count: int) -> Tuple[str, str]:
    """由做多 / 警示觸發數量歸納綜合研判（文字, 顏色）。"""
    if triggered_count == 0 and warning_count == 0:
        return VERDICT_NONE
    if warning_count > 0 and triggered_count == 0:
        return VERDICT_WARNING_ONLY
    if triggered_count >= 2 and warning_count == 0:
        return VERDICT_STRONG
    if triggered_count >= 1 and warning_count >= 1:
        return VERDICT_MIXED
    return VERDICT_SINGLE


def foreign_buy_streak(flow_df: Optional[pd.DataFrame]) -> int:
    """外資連續買超天數（flow_df 依日期新→舊，「外資」欄，張）。"""
    if flow_df is None or flow_df.empty or "外資" not in flow_df.columns:
        return 0
    streak = 0
    for v in flow_df["外資"]:
        if pd.notna(v) and v > 0:
            streak += 1
        else:
            break
    return streak


def latest_close_summary(
    price_df: Optional[pd.DataFrame],
) -> Tuple[Optional[float], Optional[str]]:
    """最新收盤價與漲跌 delta 字串（price_df 依日期昇冪，close 欄）。

    回傳 (close, delta_str)；資料不足兩日時 delta_str 為 None。
    """
    if price_df is None or price_df.empty or "close" not in price_df.columns:
        return None, None
    closes = pd.to_numeric(price_df["close"], errors="coerce").dropna()
    if closes.empty:
        return None, None
    close = float(closes.iloc[-1])
    if len(closes) < 2:
        return close, None
    prev = float(closes.iloc[-2])
    if prev == 0:
        return close, None
    diff = close - prev
    return close, f"{diff:+,.2f}（{diff / prev:+.2%}）"


def render_summary_hero(
    parsed: dict,
    *,
    price_df: Optional[pd.DataFrame] = None,
    flow_df: Optional[pd.DataFrame] = None,
) -> None:
    """首屏核心指標列＋綜合研判燈號。"""
    close, delta = latest_close_summary(price_df)
    streak = foreign_buy_streak(flow_df)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("最新收盤價", f"{close:,.2f}" if close is not None else "—", delta)
    m2.metric("✅ 做多觸發", parsed["triggered_count"])
    m3.metric("🔴 警示觸發", parsed["warning_count"])
    m4.metric("外資連買", f"{streak} 天" if streak else "—")

    verdict, color = compute_verdict(parsed["triggered_count"], parsed["warning_count"])
    st.markdown(
        f'<div style="padding:0.5rem 0.8rem;border-radius:4px;background:#1a1f24;'
        f'border-left:3px solid {color};margin:0.4rem 0">'
        f'<span style="color:{color};font-weight:600">綜合研判：</span>'
        f'<span style="color:var(--text-0)">{html.escape(verdict)}</span></div>',
        unsafe_allow_html=True,
    )
