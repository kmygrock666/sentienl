from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_INDICATOR_COLORS = {
    "ma5": "#f59e0b",
    "ma20": "#3b82f6",
    "ma60": "#8b5cf6",
    "ma120": "#ec4899",
    "ma200": "#ef4444",
    "ma240": "#64748b",
    "bb_upper": "#94a3b8",
    "bb_lower": "#94a3b8",
    "bb_mid": "#cbd5e1",
}


# 台股慣例：漲紅、跌綠（與 11_Institutional 頁面色票一致）
_TW_UP = "#E5484D"
_TW_DOWN = "#2FA46C"
_VOLUME_GRAY = "#5C6B78"
_CHIP_BG = "#0C1116"
_FLOW_COLORS = {
    "外資": "#F0A03C",
    "投信": "#4DB8C4",
    "自營商": "#8E9BA8",
}


def candlestick_with_institutional(
    price_df: pd.DataFrame,
    flow_df: pd.DataFrame | None = None,
    title: str = "",
) -> go.Figure:
    """三列子圖：K線、成交量、三大法人買賣超（張）。

    price_df: trading_date/open/high/low/close/volume（已按日期昇冪）
    flow_df: get_institutional_flow 輸出（日期/外資/投信/自營商/合計，張，可為 None/空）
    """
    if flow_df is not None and flow_df.empty:
        flow_df = None
    has_flow = flow_df is not None
    rows = 3 if has_flow else 2
    row_heights = [0.5, 0.2, 0.3] if has_flow else [0.7, 0.3]
    subplot_titles = [title, "成交量"] + (["三大法人買賣超（張）"] if has_flow else [])

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    fig.add_trace(
        go.Candlestick(
            x=price_df["trading_date"],
            open=price_df["open"],
            high=price_df["high"],
            low=price_df["low"],
            close=price_df["close"],
            name="K線",
            increasing_line_color=_TW_UP,
            decreasing_line_color=_TW_DOWN,
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=price_df["trading_date"],
            y=price_df["volume"],
            name="成交量",
            marker_color=_VOLUME_GRAY,
        ),
        row=2,
        col=1,
    )

    if flow_df is not None:
        for col_name, color in _FLOW_COLORS.items():
            fig.add_trace(
                go.Bar(
                    x=flow_df["日期"],
                    y=flow_df[col_name],
                    name=col_name,
                    marker_color=color,
                ),
                row=3,
                col=1,
            )
        fig.add_hline(y=0, line_width=1, line_color="#3a4654", row=3, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=620 if has_flow else 480,
        margin={"l": 40, "r": 20, "t": 40, "b": 20},
        legend={"orientation": "h", "y": 1.02},
        plot_bgcolor=_CHIP_BG,
        paper_bgcolor=_CHIP_BG,
        font_color="#e2e8f0",
        hovermode="x unified",
        # relative: 正負值分別往上/下堆疊；120-240 日時 group 模式柱寬不足一像素
        barmode="relative",
    )
    # rangebreaks 隱藏週六／日缺口；國定假日仍會留空（刻意保留，符合 TWSE 慣例）
    # showspikes + spikemode="across"：游標所在日期以琥珀虛線貫穿 K 線／成交量／買賣超三個面板
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        rangebreaks=[{"bounds": ["sat", "mon"]}],
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikedash="dash",
        spikethickness=1,
        spikecolor="#F0A03C",
    )
    fig.update_layout(spikedistance=-1)
    fig.update_yaxes(showgrid=True, gridcolor="#1e293b", zeroline=False)

    return fig


def candlestick_chart(
    price_df: pd.DataFrame,
    indicator_df: pd.DataFrame | None = None,
    selected_indicators: list[str] | None = None,
    title: str = "",
    show_rsi: bool = False,
) -> go.Figure:
    """Build a Plotly candlestick chart with optional overlaid indicators and RSI subplot."""
    rows = 3 if show_rsi else 2
    row_heights = [0.6, 0.2, 0.2] if show_rsi else [0.7, 0.3]
    subplot_titles = [title, "成交量", "RSI"] if show_rsi else [title, "成交量"]

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    fig.add_trace(
        go.Candlestick(
            x=price_df["trading_date"],
            open=price_df["open"],
            high=price_df["high"],
            low=price_df["low"],
            close=price_df["close"],
            name="K線",
            increasing_line_color="#ef4444",
            decreasing_line_color="#22c55e",
        ),
        row=1,
        col=1,
    )

    if indicator_df is not None and selected_indicators:
        for ind in selected_indicators:
            if ind not in indicator_df.columns or ind in ("rsi", "rsi14"):
                continue
            color = _INDICATOR_COLORS.get(ind, "#94a3b8")
            dash = "dash" if ind.startswith("bb_") else "solid"
            fig.add_trace(
                go.Scatter(
                    x=indicator_df["trading_date"],
                    y=indicator_df[ind],
                    mode="lines",
                    name=ind.upper(),
                    line={"color": color, "width": 1, "dash": dash},
                ),
                row=1,
                col=1,
            )

    colors = [
        "#ef4444" if c >= o else "#22c55e" for c, o in zip(price_df["close"], price_df["open"])
    ]
    fig.add_trace(
        go.Bar(
            x=price_df["trading_date"], y=price_df["volume"], name="成交量", marker_color=colors
        ),
        row=2,
        col=1,
    )

    if show_rsi and indicator_df is not None:
        rsi_col = next((c for c in indicator_df.columns if c.lower().startswith("rsi")), None)
        if rsi_col:
            fig.add_trace(
                go.Scatter(
                    x=indicator_df["trading_date"],
                    y=indicator_df[rsi_col],
                    mode="lines",
                    name="RSI",
                    line={"color": "#a78bfa", "width": 1.5},
                ),
                row=3,
                col=1,
            )
            for level, color in [(70, "rgba(239,68,68,0.3)"), (30, "rgba(34,197,94,0.3)")]:
                fig.add_hline(y=level, line_dash="dot", line_color=color, row=3, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=600 if show_rsi else 500,
        margin={"l": 40, "r": 20, "t": 40, "b": 20},
        legend={"orientation": "h", "y": 1.02},
        plot_bgcolor="#0f172a",
        paper_bgcolor="#0f172a",
        font_color="#e2e8f0",
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#1e293b", zeroline=False)

    return fig
