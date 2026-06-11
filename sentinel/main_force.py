"""主力買賣超（券商分點 Top-N）— FinMind TaiwanStockTradingDailyReport。

主力定義（台股慣例）：
- 分點淨額 = buy − sell（股）
- 主力買超 = 前 top_n 大「正」淨額合計
- 主力賣超 = 前 top_n 大「負」淨額合計（負值）
- 主力買賣超 = 主力買超 + 主力賣超

資料來源需 FinMind Sponsor 等級 token（TS_FINMIND_TOKEN）。
"""

from __future__ import annotations

from datetime import date
from typing import Union

import pandas as pd
import requests

from sentinel.config import Settings

__all__ = [
    "REPORT_COLUMNS",
    "FinMindError",
    "fetch_trading_daily_report",
    "compute_main_force_daily",
]

REPORT_COLUMNS = [
    "date",
    "stock_id",
    "securities_trader",
    "securities_trader_id",
    "buy",
    "sell",
]

_COMPUTE_COLUMNS = ["trading_date", "main_buy", "main_sell", "main_net", "branch_count"]

_DATASET = "TaiwanStockTradingDailyReport"

_MISSING_TOKEN_MESSAGE = (
    "未設定 TS_FINMIND_TOKEN，券商分點主力買賣超需 FinMind Sponsor 等級 API token。"
    "請至 https://finmindtrade.com 註冊並升級後，將 token 填入 .env 的 TS_FINMIND_TOKEN。"
)

DateLike = Union[str, date]


class FinMindError(RuntimeError):
    """FinMind API 錯誤，message 為可直接顯示給使用者的中文說明。"""


def _to_iso(value: DateLike) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _redact_token(message: str, token: str | None) -> str:
    """錯誤訊息中的 token 一律遮蔽，避免洩漏到終端／UI／日誌。"""
    if token:
        message = message.replace(token, "***")
    return message


def fetch_trading_daily_report(
    symbol: str,
    start_date: DateLike,
    end_date: DateLike,
    settings: Settings,
) -> pd.DataFrame:
    """抓取單一個股在日期區間內的券商分點逐日買賣明細（原始列）。

    無 token、API 等級不足、網路錯誤皆以 FinMindError 拋出（含可行動訊息）。
    成功但無資料時回傳含 REPORT_COLUMNS 欄位的空 DataFrame。
    """
    if not settings.finmind_token:
        raise FinMindError(_MISSING_TOKEN_MESSAGE)

    params = {
        "dataset": _DATASET,
        "data_id": symbol,
        "start_date": _to_iso(start_date),
        "end_date": _to_iso(end_date),
        "token": settings.finmind_token,
    }
    try:
        response = requests.get(
            settings.finmind_api_url, params=params, timeout=settings.timeout_seconds
        )
    except requests.RequestException as exc:
        raise FinMindError(
            f"FinMind API 連線失敗：{_redact_token(str(exc), settings.finmind_token)}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise FinMindError(
            f"FinMind API 回應非 JSON（HTTP {response.status_code}），請稍後重試。"
        ) from exc

    body_status = payload.get("status")
    api_msg = payload.get("msg", "")
    if response.status_code != 200 or body_status != 200:
        raise FinMindError(
            f"FinMind API 錯誤（status={body_status or response.status_code}）：{api_msg}。"
            "若訊息為等級不足（level），請升級至 Sponsor 等級後更新 TS_FINMIND_TOKEN。"
        )

    rows = payload.get("data") or []
    if not rows:
        return pd.DataFrame(columns=REPORT_COLUMNS)
    return pd.DataFrame(rows)


def compute_main_force_daily(report: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """由券商分點原始列計算逐日主力買賣超（純函式，單位：股）。

    輸出欄位：trading_date / main_buy / main_sell / main_net / branch_count，
    依 trading_date 昇冪。空輸入回傳含欄位的空 DataFrame。
    """
    if report.empty:
        return pd.DataFrame(columns=_COMPUTE_COLUMNS)

    frame = report.copy()
    frame["buy"] = pd.to_numeric(frame["buy"], errors="coerce").fillna(0)
    frame["sell"] = pd.to_numeric(frame["sell"], errors="coerce").fillna(0)

    # 同一分點同日多列時先合併（依 securities_trader_id；缺欄位時逐列視為分點）
    if "securities_trader_id" in frame.columns:
        branch_nets = frame.groupby(["date", "securities_trader_id"], as_index=False)[
            ["buy", "sell"]
        ].sum()
    else:
        branch_nets = frame[["date", "buy", "sell"]].copy()
    branch_nets["net"] = branch_nets["buy"] - branch_nets["sell"]

    records = []
    for trading_date, group in branch_nets.groupby("date"):
        nets = group["net"]
        positive = nets[nets > 0].nlargest(top_n)
        negative = nets[nets < 0].nsmallest(top_n)
        main_buy = int(positive.sum())
        main_sell = int(negative.sum())
        records.append(
            {
                "trading_date": pd.to_datetime(trading_date).date(),
                "main_buy": main_buy,
                "main_sell": main_sell,
                "main_net": main_buy + main_sell,
                "branch_count": int(len(group)),
            }
        )

    return (
        pd.DataFrame(records, columns=_COMPUTE_COLUMNS)
        .sort_values("trading_date")
        .reset_index(drop=True)
    )
