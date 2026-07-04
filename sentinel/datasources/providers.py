from __future__ import annotations

import csv
import random
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests

from sentinel.config import Settings
from sentinel.datasources.http_client import fetch_text
from sentinel.logging_utils import get_logger

logger = get_logger(__name__)
SOURCE_MODE_AUTO = "auto"
SOURCE_MODE_FIXTURE = "fixture"
SOURCE_MODE_NETWORK = "network"


def _rate_limit(settings: Settings) -> None:
    if settings.max_delay_seconds <= 0:
        return
    time.sleep(random.uniform(settings.min_delay_seconds, settings.max_delay_seconds))


def fetch_csv_with_retry(
    *,
    endpoint: str,
    params: dict[str, str],
    headers: dict[str, str],
    settings: Settings,
    market: str,
    trading_date: date,
    parse_fn: Callable[[str, date], pd.DataFrame],
    success_event: str,
    error_label: str,
) -> pd.DataFrame:
    """Shared fetch/parse loop with rate limiting, retries, and backoff + jitter.

    ``success_event`` is the structured-log event name emitted on success
    (e.g. "fetched_market_day"); ``error_label`` names the data kind in the final
    RuntimeError("Failed to fetch {market} {error_label} for {date}: ...") raised
    after exhausting ``settings.max_retries`` attempts.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, settings.max_retries + 1):
        try:
            _rate_limit(settings)
            payload = fetch_text(
                endpoint,
                params=params,
                headers=headers,
                timeout_seconds=settings.timeout_seconds,
            )
            frame = parse_fn(payload, trading_date)
            logger.info(
                success_event,
                extra={
                    "market": market,
                    "trading_date": trading_date.isoformat(),
                    "rows": int(len(frame.index)),
                },
            )
            return frame
        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
        ) as exc:
            last_error = exc
            logger.warning(
                "fetch_retry",
                extra={
                    "market": market,
                    "trading_date": trading_date.isoformat(),
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if attempt == settings.max_retries:
                break
            sleep_seconds = settings.retry_backoff_seconds * (2 ** (attempt - 1)) + random.uniform(
                0, settings.retry_jitter_seconds
            )
            time.sleep(sleep_seconds)

    raise RuntimeError(
        f"Failed to fetch {market} {error_label} for {trading_date.isoformat()}: {last_error}"
    ) from last_error


class DailyPriceProvider(ABC):
    market: str
    fixture_prefix: str

    @abstractmethod
    def fetch_day(
        self, trading_date: date, settings: Settings, source_mode: str = SOURCE_MODE_AUTO
    ) -> pd.DataFrame:
        raise NotImplementedError

    def fixture_path(self, trading_date: date, settings: Settings) -> Path:
        return (
            settings.raw_dir
            / "fixtures"
            / "prices"
            / "{0}_{1}.csv".format(
                self.fixture_prefix,
                trading_date.strftime("%Y%m%d"),
            )
        )

    def load_fixture_payload(self, trading_date: date, settings: Settings) -> Optional[str]:
        fixture_path = self.fixture_path(trading_date=trading_date, settings=settings)
        if not fixture_path.exists():
            return None
        return fixture_path.read_text(encoding="utf-8")


class TwseDailyPriceProvider(DailyPriceProvider):
    market = "TWSE"
    endpoint = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    fixture_prefix = "twse_daily"

    def fetch_day(
        self, trading_date: date, settings: Settings, source_mode: str = SOURCE_MODE_AUTO
    ) -> pd.DataFrame:
        if source_mode == SOURCE_MODE_FIXTURE:
            payload = self.load_fixture_payload(trading_date=trading_date, settings=settings)
            if payload is None:
                logger.info(
                    "price_fixture_missing",
                    extra={"market": self.market, "trading_date": trading_date.isoformat()},
                )
                return pd.DataFrame(columns=self._output_columns())
            return self._parse_csv(payload, trading_date)

        params = {
            "response": "csv",
            "date": trading_date.strftime("%Y%m%d"),
            "type": "ALLBUT0999",
        }
        headers = {"User-Agent": settings.user_agent}
        return fetch_csv_with_retry(
            endpoint=self.endpoint,
            params=params,
            headers=headers,
            settings=settings,
            market=self.market,
            trading_date=trading_date,
            parse_fn=self._parse_csv,
            success_event="fetched_market_day",
            error_label="daily prices",
        )

    def _parse_csv(self, payload: str, trading_date: date) -> pd.DataFrame:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]

        # 1. Validate data date from header (Format: 115年04月20日 每日收盤行情)
        data_date_raw = next((line for line in lines[:5] if "每日收盤行情" in line), None)
        if data_date_raw:
            # ROC year handling
            roc_year = trading_date.year - 1911
            # Check for year, month and day separately for better robustness
            y_ok = f"{roc_year}年" in data_date_raw
            m_ok = (
                f"{trading_date.month:02}月" in data_date_raw
                or f"{trading_date.month}月" in data_date_raw
            )
            d_ok = (
                f"{trading_date.day:02}日" in data_date_raw
                or f"{trading_date.day}日" in data_date_raw
            )

            if not (y_ok and m_ok and d_ok):
                logger.warning(
                    "market_data_date_not_match",
                    extra={
                        "market": self.market,
                        "expected": trading_date.isoformat(),
                        "found": data_date_raw.strip(),
                    },
                )
                return pd.DataFrame(columns=self._output_columns())

        header_index = next(
            (
                idx
                for idx, line in enumerate(lines)
                if "證券代號" in line and "成交股數" in line and "收盤價" in line
            ),
            None,
        )

        if header_index is None:
            return pd.DataFrame(columns=self._output_columns())

        header = next(csv.reader([lines[header_index]]))
        rows: list[list[str]] = []
        for raw_line in lines[header_index + 1 :]:
            if raw_line.startswith("說明") or raw_line.startswith("附註"):
                break
            parsed = next(csv.reader([raw_line]))
            if len(parsed) != len(header):
                continue
            symbol_token = _normalize_symbol_token(parsed[0]) if parsed else ""
            if not symbol_token.isdigit():
                continue
            parsed[0] = symbol_token
            rows.append(parsed)

        if not rows:
            return pd.DataFrame(columns=self._output_columns())

        raw_frame = pd.DataFrame(rows, columns=header)
        frame = pd.DataFrame(
            {
                "symbol": raw_frame["證券代號"].str.strip(),
                "name": raw_frame["證券名稱"].str.strip(),
                "market": self.market,
                "trading_date": trading_date,
                "open": raw_frame["開盤價"].map(_parse_price),
                "high": raw_frame["最高價"].map(_parse_price),
                "low": raw_frame["最低價"].map(_parse_price),
                "close": raw_frame["收盤價"].map(_parse_price),
                "volume": raw_frame["成交股數"].map(_parse_int),
                "turnover": raw_frame["成交金額"].map(_parse_int),
                "source": self.endpoint,
            }
        )
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        return frame[self._output_columns()]

    @staticmethod
    def _output_columns() -> list[str]:
        return [
            "symbol",
            "name",
            "market",
            "trading_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "source",
        ]


class TpexDailyPriceProvider(DailyPriceProvider):
    market = "TPEX"
    endpoint = (
        "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"
    )
    fixture_prefix = "tpex_daily"

    def fetch_day(
        self, trading_date: date, settings: Settings, source_mode: str = SOURCE_MODE_AUTO
    ) -> pd.DataFrame:
        if source_mode == SOURCE_MODE_FIXTURE:
            payload = self.load_fixture_payload(trading_date=trading_date, settings=settings)
            if payload is None:
                logger.info(
                    "price_fixture_missing",
                    extra={"market": self.market, "trading_date": trading_date.isoformat()},
                )
                return pd.DataFrame(columns=self._output_columns())
            return self._parse_csv(payload, trading_date)

        params = {
            "l": "zh-tw",
            "o": "csv",
            "d": _to_minguo_date(trading_date),
            "s": "0,asc,0",
        }
        headers = {"User-Agent": settings.user_agent}
        return fetch_csv_with_retry(
            endpoint=self.endpoint,
            params=params,
            headers=headers,
            settings=settings,
            market=self.market,
            trading_date=trading_date,
            parse_fn=self._parse_csv,
            success_event="fetched_market_day",
            error_label="daily prices",
        )

    def _parse_csv(self, payload: str, trading_date: date) -> pd.DataFrame:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]

        # 1. Validate data date from header (Format: 資料日期:115/04/20)
        data_date_raw = next((line for line in lines[:5] if "資料日期" in line), None)
        if data_date_raw:
            roc_year = trading_date.year - 1911
            y_ok = str(roc_year) in data_date_raw
            m_ok = (
                f"/{trading_date.month:02}/" in data_date_raw
                or f"/{trading_date.month}/" in data_date_raw
            )
            d_ok = (
                f"/{trading_date.day:02}" in data_date_raw
                or f"/{trading_date.day}" in data_date_raw
            )

            if not (y_ok and m_ok and d_ok):
                logger.warning(
                    "market_data_date_not_match",
                    extra={
                        "market": self.market,
                        "expected": trading_date.isoformat(),
                        "found": data_date_raw.strip(),
                    },
                )
                return pd.DataFrame(columns=self._output_columns())

        header_index = next(
            (
                idx
                for idx, line in enumerate(lines)
                if "代號" in line and "成交股數" in line and "收盤" in line
            ),
            None,
        )
        if header_index is None:
            return pd.DataFrame(columns=self._output_columns())

        header = [value.strip() for value in next(csv.reader([lines[header_index]]))]
        rows = []
        for raw_line in lines[header_index + 1 :]:
            if raw_line.startswith("=") or raw_line.startswith("註") or raw_line.startswith("＊"):
                break
            parsed = [value.strip() for value in next(csv.reader([raw_line]))]
            if len(parsed) != len(header):
                continue
            if not parsed or not parsed[0].strip().isdigit():
                continue
            rows.append(parsed)

        if not rows:
            return pd.DataFrame(columns=self._output_columns())

        raw_frame = pd.DataFrame(rows, columns=header)
        frame = pd.DataFrame(
            {
                "symbol": raw_frame[_find_column(raw_frame, ["代號"])].str.strip(),
                "name": raw_frame[_find_column(raw_frame, ["名稱"])].str.strip(),
                "market": self.market,
                "trading_date": trading_date,
                "open": raw_frame[_find_column(raw_frame, ["開盤"])].map(_parse_price),
                "high": raw_frame[_find_column(raw_frame, ["最高"])].map(_parse_price),
                "low": raw_frame[_find_column(raw_frame, ["最低"])].map(_parse_price),
                "close": raw_frame[_find_column(raw_frame, ["收盤"])].map(_parse_price),
                "volume": raw_frame[_find_column(raw_frame, ["成交股數"])].map(_parse_int),
                "turnover": raw_frame[_find_column(raw_frame, ["成交金額"])].map(_parse_int),
                "source": self.endpoint,
            }
        )
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        return frame[self._output_columns()]

    @staticmethod
    def _output_columns() -> list[str]:
        return [
            "symbol",
            "name",
            "market",
            "trading_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "source",
        ]


def _parse_price(value: str) -> Optional[float]:
    cleaned = value.replace(",", "").replace("=", "").strip().strip('"')
    if cleaned in {"", "--", "---", "----", "N/A"}:
        return None
    return float(cleaned)


def _normalize_symbol_token(value: str) -> str:
    return value.replace("=", "").replace('"', "").strip()


def _parse_int(value: str) -> int:
    cleaned = value.replace(",", "").replace("=", "").strip().strip('"')
    if cleaned in {"", "--", "---", "----", "N/A"}:
        return 0
    return int(float(cleaned))


def build_price_provider(market_name: str) -> DailyPriceProvider:
    normalized = normalize_market_name(market_name)
    if normalized == "TWSE":
        return TwseDailyPriceProvider()
    if normalized == "TPEX":
        return TpexDailyPriceProvider()
    raise ValueError(f"Unsupported market provider: {market_name}")


_YAHOO_SUFFIX = {"TWSE": ".TW", "TPEX": ".TWO"}
_YAHOO_CHUNK = 50


def fetch_yahoo_historical(
    market: str,
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Fetch historical OHLCV from Yahoo Finance for a date range.

    Taiwan tickers: TWSE → symbol+'.TW', TPEX → symbol+'.TWO'.
    Returns a DataFrame with the same columns as PRICE_COLUMNS in storage.py.
    The 'name' field is left empty (caller should enrich from stock master).
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance") from exc

    from datetime import timedelta

    suffix = _YAHOO_SUFFIX.get(market)
    if suffix is None:
        raise ValueError(f"Yahoo Finance backfill not supported for market: {market}")

    fetch_end = end_date + timedelta(days=1)
    all_rows: list[dict] = []

    for i in range(0, len(symbols), _YAHOO_CHUNK):
        chunk = symbols[i : i + _YAHOO_CHUNK]
        ticker_map = {f"{s}{suffix}": s for s in chunk}
        tickers = list(ticker_map.keys())

        raw = yf.download(
            tickers,
            start=start_date.isoformat(),
            end=fetch_end.isoformat(),
            auto_adjust=False,
            progress=False,
            group_by="column",
        )

        if raw.empty:
            continue

        is_multi = isinstance(raw.columns, pd.MultiIndex)

        for ticker, symbol in ticker_map.items():
            if is_multi:
                try:
                    ticker_df = raw.xs(ticker, axis=1, level=1)
                except KeyError:
                    continue
            else:
                ticker_df = raw

            for dt, row in ticker_df.iterrows():
                close_val = row.get("Close")
                if close_val is None or (
                    hasattr(close_val, "__float__") and pd.isna(float(close_val))
                ):
                    continue
                dt_date = dt.date() if hasattr(dt, "date") else dt
                all_rows.append(
                    {
                        "symbol": symbol,
                        "name": "",
                        "market": market,
                        "trading_date": dt_date,
                        "open": _safe_float(row.get("Open")),
                        "high": _safe_float(row.get("High")),
                        "low": _safe_float(row.get("Low")),
                        "close": _safe_float(close_val),
                        "volume": _safe_int(row.get("Volume")),
                        "turnover": 0,
                        "source": "yahoo_finance",
                    }
                )

        logger.info(
            "yahoo_chunk_fetched",
            extra={
                "market": market,
                "symbols_in_chunk": len(chunk),
                "rows_so_far": len(all_rows),
            },
        )

    if not all_rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "name",
                "market",
                "trading_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
                "source",
            ]
        )

    result = pd.DataFrame(all_rows)
    result["trading_date"] = pd.to_datetime(result["trading_date"]).dt.date
    return result


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int:
    try:
        v = float(val)
        return 0 if pd.isna(v) else int(v)
    except (TypeError, ValueError):
        return 0


def normalize_market_name(market_name: str) -> str:
    normalized = market_name.strip().upper()
    if normalized == "TPEX":
        return "TPEX"
    return normalized


def _to_minguo_date(trading_date: date) -> str:
    return f"{trading_date.year - 1911}/{trading_date.month:02d}/{trading_date.day:02d}"


def _find_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    for column in frame.columns:
        normalized = column.replace(" ", "").strip()
        if all(candidate in normalized for candidate in candidates):
            return column
    raise ValueError("Required column not found: {0}".format(", ".join(candidates)))
