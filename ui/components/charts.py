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
        "#ef4444" if c >= o else "#22c55e"
        for c, o in zip(price_df["close"], price_df["open"])
    ]
    fig.add_trace(
        go.Bar(x=price_df["trading_date"], y=price_df["volume"], name="成交量", marker_color=colors),
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
