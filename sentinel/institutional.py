"""三大法人買賣超（法人籌碼）providers for TWSE (T86) and TPEX.

Follows the provider pattern in sentinel/providers.py: fixture/network source
modes, retry loop with exponential backoff + jitter, ROC-date validation and
tolerant column matching against the official CSV payloads.
"""

from __future__ import annotations

import csv
import random
import subprocess
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from sentinel.config import Settings
from sentinel.http_client import fetch_text
from sentinel.logging_utils import get_logger
from sentinel.providers import (
    SOURCE_MODE_AUTO,
    SOURCE_MODE_FIXTURE,
    SOURCE_MODE_NETWORK,
    _find_column,
    _normalize_symbol_token,
    _to_minguo_date,
    normalize_market_name,
)

__all__ = [
    "SOURCE_MODE_AUTO",
    "SOURCE_MODE_FIXTURE",
    "SOURCE_MODE_NETWORK",
    "InstitutionalFlowProvider",
    "TwseT86Provider",
    "TpexInstitutionalProvider",
    "build_institutional_provider",
]

logger = get_logger(__name__)

_NET_COLUMNS = ["foreign_net", "investment_trust_net", "dealer_net", "total_net"]


class InstitutionalFlowProvider(ABC):
    market: str
    fixture_prefix: str
    endpoint: str

    def fixture_path(self, trading_date: date, settings: Settings) -> Path:
        return (
            settings.raw_dir
            / "fixtures"
            / "institutional"
            / "{}_{}.csv".format(
                self.fixture_prefix,
                trading_date.strftime("%Y%m%d"),
            )
        )

    def load_fixture_payload(self, trading_date: date, settings: Settings) -> str | None:
        fixture_path = self.fixture_path(trading_date=trading_date, settings=settings)
        if not fixture_path.exists():
            return None
        return fixture_path.read_text(encoding="utf-8")

    def fetch_day(
        self, trading_date: date, settings: Settings, source_mode: str = SOURCE_MODE_AUTO
    ) -> pd.DataFrame:
        if source_mode == SOURCE_MODE_FIXTURE:
            payload = self.load_fixture_payload(trading_date=trading_date, settings=settings)
            if payload is None:
                logger.info(
                    "institutional_fixture_missing",
                    extra={"market": self.market, "trading_date": trading_date.isoformat()},
                )
                return pd.DataFrame(columns=self._output_columns())
            return self._parse_csv(payload, trading_date)

        params = self._network_params(trading_date)
        headers = {"User-Agent": settings.user_agent}
        last_error: Exception | None = None

        for attempt in range(1, settings.max_retries + 1):
            try:
                self._rate_limit(settings)
                payload = fetch_text(
                    self.endpoint,
                    params=params,
                    headers=headers,
                    timeout_seconds=settings.timeout_seconds,
                )
                frame = self._parse_csv(payload, trading_date)
                logger.info(
                    "fetched_institutional_day",
                    extra={
                        "market": self.market,
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
                        "market": self.market,
                        "trading_date": trading_date.isoformat(),
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                if attempt == settings.max_retries:
                    break
                sleep_seconds = settings.retry_backoff_seconds * (
                    2 ** (attempt - 1)
                ) + random.uniform(0, settings.retry_jitter_seconds)
                time.sleep(sleep_seconds)

        raise RuntimeError(
            f"Failed to fetch {self.market} institutional flows for "
            f"{trading_date.isoformat()}: {last_error}"
        ) from last_error

    @abstractmethod
    def _network_params(self, trading_date: date) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def _parse_csv(self, payload: str, trading_date: date) -> pd.DataFrame:
        raise NotImplementedError

    def _rate_limit(self, settings: Settings) -> None:
        if settings.max_delay_seconds <= 0:
            return
        time.sleep(random.uniform(settings.min_delay_seconds, settings.max_delay_seconds))

    @staticmethod
    def _output_columns() -> list[str]:
        return ["market", "symbol", "trading_date"] + list(_NET_COLUMNS)

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=self._output_columns())

    def _build_frame(
        self, header: list[str], rows: list[list[str]], symbol_keyword: str, trading_date: date
    ) -> pd.DataFrame:
        raw_frame = pd.DataFrame(rows, columns=header)
        symbol_column = _find_column(raw_frame, [symbol_keyword])
        net_columns = {
            "foreign_net": _find_foreign_net_column(raw_frame),
            "investment_trust_net": _find_first_matching_column(raw_frame, ["投信", "買賣超"]),
            "dealer_net": _find_dealer_net_column(raw_frame),
            "total_net": _find_first_matching_column(raw_frame, ["三大法人買賣超"]),
        }
        for field, column in net_columns.items():
            if column is None:
                # 交易所改欄名時整欄會變 None，提早留下線索方便除錯
                logger.warning(
                    "institutional_column_not_found",
                    extra={"field": field, "market": self.market, "header": header},
                )
        frame = pd.DataFrame(
            {
                "market": self.market,
                "symbol": raw_frame[symbol_column].str.strip(),
                "trading_date": trading_date,
                **{field: _net_series(raw_frame, column) for field, column in net_columns.items()},
            }
        )
        frame = frame.dropna(subset=_NET_COLUMNS, how="all")
        return frame[self._output_columns()].reset_index(drop=True)


class TwseT86Provider(InstitutionalFlowProvider):
    market = "TWSE"
    endpoint = "https://www.twse.com.tw/rwd/zh/fund/T86"
    fixture_prefix = "twse_t86"

    def _network_params(self, trading_date: date) -> dict[str, str]:
        return {
            "date": trading_date.strftime("%Y%m%d"),
            "selectType": "ALLBUT0999",
            "response": "csv",
        }

    def _parse_csv(self, payload: str, trading_date: date) -> pd.DataFrame:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]

        # Validate data date from title (Format: 114年03月05日 三大法人買賣超日報)
        data_date_raw = next(
            (line for line in lines[:5] if "三大法人買賣超" in line and "年" in line),
            None,
        )
        if data_date_raw and not _payload_date_matches(data_date_raw, trading_date):
            logger.warning(
                "institutional_data_date_not_match",
                extra={
                    "market": self.market,
                    "expected": trading_date.isoformat(),
                    "found": data_date_raw.strip(),
                },
            )
            return self._empty_frame()

        header_index = next(
            (idx for idx, line in enumerate(lines) if "證券代號" in line and "買賣超" in line),
            None,
        )
        if header_index is None:
            return self._empty_frame()

        header = [value.strip() for value in next(csv.reader([lines[header_index]]))]
        rows: list[list[str]] = []
        for raw_line in lines[header_index + 1 :]:
            if raw_line.startswith("說明") or raw_line.startswith("附註"):
                break
            parsed = [value.strip() for value in next(csv.reader([raw_line]))]
            if len(parsed) != len(header):
                continue
            symbol_token = _normalize_symbol_token(parsed[0]) if parsed else ""
            if not symbol_token.isdigit():
                continue
            parsed[0] = symbol_token
            rows.append(parsed)

        if not rows:
            return self._empty_frame()

        return self._build_frame(header, rows, "證券代號", trading_date)


class TpexInstitutionalProvider(InstitutionalFlowProvider):
    market = "TPEX"
    endpoint = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    fixture_prefix = "tpex_inst"

    def _network_params(self, trading_date: date) -> dict[str, str]:
        return {
            "l": "zh-tw",
            "o": "csv",
            "se": "EW",
            "t": "D",
            "d": _to_minguo_date(trading_date),
        }

    def _parse_csv(self, payload: str, trading_date: date) -> pd.DataFrame:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]

        # Validate data date (Format: 資料日期:114/03/05 or 114年03月05日 ... title)
        data_date_raw = next(
            (
                line
                for line in lines[:5]
                if "資料日期" in line or ("買賣超" in line and "年" in line)
            ),
            None,
        )
        if data_date_raw and not _payload_date_matches(data_date_raw, trading_date):
            logger.warning(
                "institutional_data_date_not_match",
                extra={
                    "market": self.market,
                    "expected": trading_date.isoformat(),
                    "found": data_date_raw.strip(),
                },
            )
            return self._empty_frame()

        header_index = next(
            (idx for idx, line in enumerate(lines) if "代號" in line and "買賣超" in line),
            None,
        )
        if header_index is None:
            return self._empty_frame()

        header = [value.strip() for value in next(csv.reader([lines[header_index]]))]
        rows: list[list[str]] = []
        for raw_line in lines[header_index + 1 :]:
            if raw_line.startswith("=") or raw_line.startswith("註") or raw_line.startswith("＊"):
                break
            parsed = [value.strip() for value in next(csv.reader([raw_line]))]
            if len(parsed) != len(header):
                continue
            symbol_token = _normalize_symbol_token(parsed[0]) if parsed else ""
            if not symbol_token.isdigit():
                continue
            parsed[0] = symbol_token
            rows.append(parsed)

        if not rows:
            return self._empty_frame()

        return self._build_frame(header, rows, "代號", trading_date)


def build_institutional_provider(market: str) -> InstitutionalFlowProvider:
    normalized = normalize_market_name(market)
    if normalized == "TWSE":
        return TwseT86Provider()
    if normalized == "TPEX":
        return TpexInstitutionalProvider()
    raise ValueError(f"Unsupported institutional flow provider: {market}")


def _payload_date_matches(line: str, trading_date: date) -> bool:
    roc_year = trading_date.year - 1911
    y_ok = f"{roc_year}年" in line or f"{roc_year}/" in line
    m_ok = any(
        token in line
        for token in (
            f"{trading_date.month:02}月",
            f"{trading_date.month}月",
            f"/{trading_date.month:02}/",
            f"/{trading_date.month}/",
        )
    )
    d_ok = any(
        token in line
        for token in (
            f"{trading_date.day:02}日",
            f"{trading_date.day}日",
            f"/{trading_date.day:02}",
            f"/{trading_date.day}",
        )
    )
    return y_ok and m_ok and d_ok


def _normalize_column_name(column: str) -> str:
    return column.replace(" ", "").replace("-", "").strip()


def _match_columns(frame: pd.DataFrame, keywords: Sequence[str]) -> list[str]:
    return [
        column
        for column in frame.columns
        if all(keyword in _normalize_column_name(column) for keyword in keywords)
    ]


def _find_first_matching_column(frame: pd.DataFrame, keywords: Sequence[str]) -> str | None:
    matches = _match_columns(frame, keywords)
    return matches[0] if matches else None


def _find_foreign_net_column(frame: pd.DataFrame) -> str | None:
    matches = _match_columns(frame, ["外陸資", "買賣超"]) or _match_columns(
        frame, ["外資", "買賣超"]
    )
    # Prefer the aggregate foreign column over the foreign-dealer-only column
    # (外資自營商買賣超股數), but keep names like 外陸資買賣超股數(不含外資自營商).
    preferred = [
        column
        for column in matches
        if "外資自營" not in _normalize_column_name(column)
        or "不含" in _normalize_column_name(column)
    ]
    pool = preferred or matches
    return pool[0] if pool else None


def _find_dealer_net_column(frame: pd.DataFrame) -> str | None:
    matches = _match_columns(frame, ["自營商", "買賣超股數"])
    if not matches:
        return None
    # Prefer the aggregate column, i.e. the shortest matching name
    # (自營商買賣超股數 over 自營商買賣超股數(自行買賣) / (避險) / 外資自營商...).
    return min(matches, key=lambda column: len(_normalize_column_name(column)))


def _net_series(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series([None] * len(frame.index), index=frame.index, dtype=object)
    return frame[column].map(_parse_net)


def _parse_net(value: str) -> int | None:
    cleaned = value.replace(",", "").replace("=", "").strip().strip('"')
    if cleaned in {"", "--", "---", "----", "N/A"}:
        return None
    return int(float(cleaned))
