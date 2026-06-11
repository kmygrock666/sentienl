"""測試籌碼K線圖表 builder 與 UI 用 CSV 價格載入器。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import ui.services.queries as queries
from ui.components.charts import candlestick_with_institutional
from ui.services.queries import load_symbol_prices

# ═══════════════════════════════════════════════════════════════════════════
# candlestick_with_institutional
# ═══════════════════════════════════════════════════════════════════════════


def _price_frame() -> pd.DataFrame:
    dates = pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"])
    return pd.DataFrame(
        {
            "trading_date": dates,
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1000, 2000, 1500],
        }
    )


def _flow_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"]),
            "外資": [120, -80, 50],
            "投信": [30, 0, -20],
            "自營商": [-10, 20, 10],
            "合計": [140, -60, 40],
        }
    )
    for col in ["外資", "投信", "自營商", "合計"]:
        df[col] = df[col].astype("Int64")
    return df


def test_chart_with_flows_has_five_traces() -> None:
    """有籌碼資料：K線 + 成交量 + 三條法人 bar，共 5 traces。"""
    fig = candlestick_with_institutional(_price_frame(), _flow_frame(), title="測試")

    assert len(fig.data) == 5
    names = [t.name for t in fig.data]
    assert "外資" in names
    assert "投信" in names
    assert "自營商" in names
    assert fig.layout.height == 620


def test_chart_without_flows_has_two_traces() -> None:
    """flow_df=None：只有 K線 + 成交量。"""
    fig = candlestick_with_institutional(_price_frame(), None)

    assert len(fig.data) == 2
    assert fig.layout.height == 480


def test_chart_with_empty_flows_behaves_like_none() -> None:
    """空 flow_df 視同無籌碼資料（兩列模式）。"""
    empty = pd.DataFrame(columns=["日期", "外資", "投信", "自營商", "合計"])
    fig = candlestick_with_institutional(_price_frame(), empty)

    assert len(fig.data) == 2


def test_chart_candle_colors_follow_tw_convention() -> None:
    """K線漲紅跌綠（台股慣例），且 hover 採 x unified。"""
    fig = candlestick_with_institutional(_price_frame(), _flow_frame())

    candle = fig.data[0]
    assert candle.increasing.line.color == "#E5484D"
    assert candle.decreasing.line.color == "#2FA46C"
    assert fig.layout.hovermode == "x unified"


# ═══════════════════════════════════════════════════════════════════════════
# candlestick_with_institutional + 主力買賣超（第 4 列）
# ═══════════════════════════════════════════════════════════════════════════


def _main_force_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"]),
            "主力買超": [150, 80, 60],
            "主力賣超": [-110, -40, -90],
            "主力買賣超": [40, 40, -30],
        }
    )
    for col in ["主力買超", "主力賣超", "主力買賣超"]:
        df[col] = df[col].astype("Int64")
    return df


def test_chart_with_flows_and_main_force_has_six_traces() -> None:
    """法人 + 主力都有資料：K線 + 成交量 + 3 法人 + 1 主力 = 6 traces，4 列模式。"""
    fig = candlestick_with_institutional(
        _price_frame(), _flow_frame(), title="測試", main_force_df=_main_force_frame()
    )

    assert len(fig.data) == 6
    names = [t.name for t in fig.data]
    assert "主力買賣超" in names
    mf_trace = next(t for t in fig.data if t.name == "主力買賣超")
    assert mf_trace.marker.color == "#9D7CD8"
    assert fig.layout.height == 740


def test_chart_main_force_bars_align_to_main_force_dates() -> None:
    """主力 bar 的 x 軸必須等於 main_force_df 的日期。"""
    mf = _main_force_frame()
    fig = candlestick_with_institutional(_price_frame(), _flow_frame(), main_force_df=mf)

    mf_trace = next(t for t in fig.data if t.name == "主力買賣超")
    assert list(mf_trace.x) == list(mf["日期"])


def test_chart_empty_main_force_behaves_like_absent() -> None:
    """空主力 frame 視同未提供：維持 3 列 / 5 traces。"""
    empty_mf = pd.DataFrame(columns=["日期", "主力買超", "主力賣超", "主力買賣超"])
    fig = candlestick_with_institutional(_price_frame(), _flow_frame(), main_force_df=empty_mf)

    assert len(fig.data) == 5
    assert fig.layout.height == 620


def test_chart_main_force_without_flows() -> None:
    """只有主力、無法人：3 列（K線/量/主力），3 traces。"""
    fig = candlestick_with_institutional(_price_frame(), None, main_force_df=_main_force_frame())

    assert len(fig.data) == 3
    assert [t.name for t in fig.data][-1] == "主力買賣超"


# ═══════════════════════════════════════════════════════════════════════════
# load_symbol_prices
# ═══════════════════════════════════════════════════════════════════════════

_CSV_HEADER = "symbol,name,market,trading_date,open,high,low,close,volume,turnover,source"


class _FakeSettings:
    def __init__(self, path: Path) -> None:
        self.price_dataset_path = path


@pytest.fixture()
def price_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """兩檔個股、亂序日期的價格 CSV，並 monkeypatch Settings 指向它。"""
    rows = [
        _CSV_HEADER,
        "2330,台積電,TWSE,2026-06-10,1000,1010,995,1005,30000,1,twse",
        "2330,台積電,TWSE,2026-06-08,980,995,975,990,25000,1,twse",
        "2330,台積電,TWSE,2026-06-09,990,1000,985,995,28000,1,twse",
        "5347,世界,TPEX,2026-06-10,100,102,99,101,5000,1,tpex",
    ]
    path = tmp_path / "daily_prices.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(queries, "Settings", lambda: _FakeSettings(path))
    return path


def test_load_symbol_prices_filters_and_sorts_ascending(price_csv: Path) -> None:
    """只取指定 symbol，依日期昇冪排序。"""
    df = load_symbol_prices("2330")

    assert len(df) == 3
    assert set(df["symbol"]) == {"2330"}
    dates = [str(d) for d in df["trading_date"]]
    assert dates == ["2026-06-08", "2026-06-09", "2026-06-10"]
    for col in ["market", "symbol", "trading_date", "open", "high", "low", "close", "volume"]:
        assert col in df.columns


def test_load_symbol_prices_tail_days(price_csv: Path) -> None:
    """days 限制只取最近 N 個交易日。"""
    df = load_symbol_prices("2330", days=2)

    assert len(df) == 2
    assert [str(d) for d in df["trading_date"]] == ["2026-06-09", "2026-06-10"]


def test_load_symbol_prices_missing_symbol_returns_empty(price_csv: Path) -> None:
    """找不到 symbol 時回傳含欄位的空 frame。"""
    df = load_symbol_prices("9999")

    assert df.empty
    for col in ["market", "symbol", "trading_date", "open", "high", "low", "close", "volume"]:
        assert col in df.columns


def test_load_symbol_prices_missing_dataset_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """價格資料集不存在時回傳空 frame（不噴錯）。"""
    monkeypatch.setattr(queries, "Settings", lambda: _FakeSettings(tmp_path / "nope.csv"))

    df = load_symbol_prices("2330")

    assert df.empty


# ── market filtering ────────────────────────────────────────────────────────

_CSV_COLLISION_HEADER = "symbol,name,market,trading_date,open,high,low,close,volume,turnover,source"


@pytest.fixture()
def _collision_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """同一代號 6201 同時出現在 TWSE 與 TPEX（真實碰撞情境）。"""
    rows = [
        _CSV_COLLISION_HEADER,
        "6201,aaa,TWSE,2026-06-10,50,51,49,50,10000,1,twse",
        "6201,bbb,TPEX,2026-06-10,20,21,19,20,5000,1,tpex",
        "6201,aaa,TWSE,2026-06-09,49,50,48,49,9000,1,twse",
    ]
    path = tmp_path / "collision_prices.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(queries, "Settings", lambda: _FakeSettings(path))
    return path


def test_load_symbol_prices_market_filter_twse(_collision_csv: Path) -> None:
    """market='TWSE' 只回傳 TWSE 的列，排除 TPEX 同代號（記錄碰撞風險）。"""
    df = load_symbol_prices("6201", days=60, market="TWSE")

    assert not df.empty
    assert (df["market"] == "TWSE").all()
    assert len(df) == 2  # 兩個 TWSE 日期


def test_load_symbol_prices_market_none_returns_both(_collision_csv: Path) -> None:
    """market=None 回傳兩市場全部列——記錄 (symbol, date) 碰撞風險。"""
    df = load_symbol_prices("6201", days=60, market=None)

    assert len(df) == 3  # TWSE×2 + TPEX×1
    assert set(df["market"]) == {"TWSE", "TPEX"}


# ── bar-alignment regression ─────────────────────────────────────────────────


def _short_flow_frame() -> pd.DataFrame:
    """法人資料只有兩個日期（比 price_frame 的三天少一天）。"""
    df = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-06-09", "2026-06-10"]),
            "外資": [100, -50],
            "投信": [10, -5],
            "自營商": [5, 5],
            "合計": [115, -50],
        }
    )
    for col in ["外資", "投信", "自營商", "合計"]:
        df[col] = df[col].astype("Int64")
    return df


def test_flow_bars_align_to_flow_dates_not_price_dates() -> None:
    """法人 bar 的 x 軸日期必須等於 flow_df 的日期，不能被拉伸到 price_df 範圍。"""
    price_df = _price_frame()  # 3 dates: 06-08, 06-09, 06-10
    flow_df = _short_flow_frame()  # 2 dates: 06-09, 06-10

    fig = candlestick_with_institutional(price_df, flow_df, title="對齊測試")

    # 找到名稱為「外資」的 trace（比用索引更穩健）
    foreign_trace = next(t for t in fig.data if t.name == "外資")
    bar_dates = list(foreign_trace.x)
    expected = list(flow_df["日期"])
    assert bar_dates == expected, f"外資 bar x={bar_dates!r}，期望 {expected!r}"
