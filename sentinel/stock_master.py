from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import re
from typing import Dict, Iterable, Optional, Sequence

import pandas as pd
import requests

from sentinel.config import Settings
from sentinel.logging_utils import get_logger
from sentinel.providers import SOURCE_MODE_AUTO, SOURCE_MODE_FIXTURE, SOURCE_MODE_NETWORK, normalize_market_name

logger = get_logger(__name__)

STOCK_COLUMNS = [
    "symbol",
    "name",
    "market",
    "industry",
    "list_status",
    "source",
]


@dataclass
class StockMasterFetchAttempt:
    transport: str
    status: str
    rows_fetched: int = 0
    url: Optional[str] = None
    fixture_path: Optional[str] = None
    error_category: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    http_status_code: Optional[int] = None


@dataclass
class StockMasterFetchDiagnostic:
    market: str
    source_mode: str
    final_status: str
    rows_fetched: int
    attempts: list[StockMasterFetchAttempt] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "source_mode": self.source_mode,
            "final_status": self.final_status,
            "rows_fetched": self.rows_fetched,
            "attempts": [asdict(attempt) for attempt in self.attempts],
        }


class StockMasterProvider(ABC):
    market: str
    fixture_prefix: str

    def fetch(self, settings: Settings, source_mode: str = SOURCE_MODE_AUTO) -> pd.DataFrame:
        frame, _ = self.fetch_with_diagnostic(settings=settings, source_mode=source_mode)
        return frame

    def fetch_with_diagnostic(
        self,
        settings: Settings,
        source_mode: str = SOURCE_MODE_AUTO,
    ) -> tuple[pd.DataFrame, StockMasterFetchDiagnostic]:
        attempts: list[StockMasterFetchAttempt] = []
        if source_mode in {SOURCE_MODE_AUTO, SOURCE_MODE_FIXTURE}:
            fixture_payload = self._load_fixture_payload(settings=settings)
            if fixture_payload is not None:
                try:
                    frame = self.parse_payload(fixture_payload)
                except Exception as exc:  # pragma: no cover - defensive classification path
                    attempts.append(
                        StockMasterFetchAttempt(
                            transport="fixture",
                            status="failed",
                            fixture_path=str(self.fixture_path(settings=settings)),
                            error_category="parse",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                    )
                else:
                    attempts.append(
                        StockMasterFetchAttempt(
                            transport="fixture",
                            status="success",
                            fixture_path=str(self.fixture_path(settings=settings)),
                            rows_fetched=int(len(frame.index)),
                        )
                    )
                    return frame, _build_stock_master_fetch_diagnostic(
                        market=self.market,
                        source_mode=source_mode,
                        attempts=attempts,
                    )
            if source_mode == SOURCE_MODE_FIXTURE:
                logger.info("stock_master_fixture_missing", extra={"market": self.market})
                if not attempts:
                    attempts.append(
                        StockMasterFetchAttempt(
                            transport="fixture",
                            status="missing",
                            fixture_path=str(self.fixture_path(settings=settings)),
                            error_category="fixture_missing",
                        )
                    )
                return (
                    pd.DataFrame(columns=STOCK_COLUMNS),
                    _build_stock_master_fetch_diagnostic(
                        market=self.market,
                        source_mode=source_mode,
                        attempts=attempts,
                    ),
                )
            if fixture_payload is None:
                attempts.append(
                    StockMasterFetchAttempt(
                        transport="fixture",
                        status="missing",
                        fixture_path=str(self.fixture_path(settings=settings)),
                        error_category="fixture_missing",
                    )
                )

        if source_mode == SOURCE_MODE_FIXTURE:
            return (
                pd.DataFrame(columns=STOCK_COLUMNS),
                _build_stock_master_fetch_diagnostic(
                    market=self.market,
                    source_mode=source_mode,
                    attempts=attempts,
                ),
            )

        url = self.build_url(settings=settings)
        if not url:
            logger.info("stock_master_provider_skipped", extra={"market": self.market, "reason": "missing_url"})
            attempts.append(
                StockMasterFetchAttempt(
                    transport="network",
                    status="skipped",
                    error_category="missing_url",
                )
            )
            return (
                pd.DataFrame(columns=STOCK_COLUMNS),
                _build_stock_master_fetch_diagnostic(
                    market=self.market,
                    source_mode=source_mode,
                    attempts=attempts,
                ),
            )

        try:
            response = requests.get(
                url,
                headers={"User-Agent": settings.user_agent},
                timeout=settings.timeout_seconds,
            )
            response.raise_for_status()
            frame = self.parse_payload(_decode_stock_master_payload(response.content))
            attempts.append(
                StockMasterFetchAttempt(
                    transport="network",
                    status="success",
                    url=url,
                    rows_fetched=int(len(frame.index)),
                )
            )
            return frame, _build_stock_master_fetch_diagnostic(
                market=self.market,
                source_mode=source_mode,
                attempts=attempts,
            )
        except requests.RequestException as exc:
            failure_details = _classify_request_exception(exc)
            attempts.append(
                StockMasterFetchAttempt(
                    transport="network",
                    status="failed",
                    url=url,
                    error_category=failure_details["error_category"],
                    error_type=failure_details["error_type"],
                    error_message=failure_details["error_message"],
                    http_status_code=failure_details["http_status_code"],
                )
            )
            logger.warning(
                "stock_master_fetch_failed",
                extra={
                    "market": self.market,
                    "url": url,
                    "error": str(exc),
                    "error_category": failure_details["error_category"],
                    "error_type": failure_details["error_type"],
                    "http_status_code": failure_details["http_status_code"],
                },
            )
            return (
                pd.DataFrame(columns=STOCK_COLUMNS),
                _build_stock_master_fetch_diagnostic(
                    market=self.market,
                    source_mode=source_mode,
                    attempts=attempts,
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive classification path
            attempts.append(
                StockMasterFetchAttempt(
                    transport="network",
                    status="failed",
                    url=url,
                    error_category="parse",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )
            logger.warning(
                "stock_master_parse_failed",
                extra={"market": self.market, "url": url, "error": str(exc), "error_type": type(exc).__name__},
            )
            return (
                pd.DataFrame(columns=STOCK_COLUMNS),
                _build_stock_master_fetch_diagnostic(
                    market=self.market,
                    source_mode=source_mode,
                    attempts=attempts,
                ),
            )

    @abstractmethod
    def build_url(self, settings: Settings) -> Optional[str]:
        raise NotImplementedError

    def parse_payload(self, payload: str) -> pd.DataFrame:
        if _looks_like_html(payload):
            return self.parse_html_payload(payload)
        frame = pd.read_csv(StringIO(payload), dtype={"證券代號": str, "股票代號": str, "公司代號": str, "symbol": str, "代號": str})
        return _normalize_stock_master(frame)

    def parse_html_payload(self, payload: str) -> pd.DataFrame:
        raise NotImplementedError

    def fixture_path(self, settings: Settings) -> Path:
        return settings.raw_dir / "fixtures" / "stocks" / "{0}.csv".format(self.fixture_prefix)

    def _load_fixture_payload(self, settings: Settings) -> Optional[str]:
        fixture_path = self.fixture_path(settings=settings)
        if not fixture_path.exists():
            return None
        return _decode_stock_master_payload(fixture_path.read_bytes())


class TwseStockMasterProvider(StockMasterProvider):
    market = "TWSE"
    fixture_prefix = "twse_stocks"

    def build_url(self, settings: Settings) -> Optional[str]:
        return settings.twse_stock_master_url

    def parse_payload(self, payload: str) -> pd.DataFrame:
        if _looks_like_html(payload):
            return self.parse_html_payload(payload)
        frame = pd.read_csv(StringIO(payload), dtype={"證券代號": str, "股票代號": str, "公司代號": str, "symbol": str, "代號": str})
        normalized = pd.DataFrame(
            {
                "symbol": frame[_find_stock_master_column(frame, ["symbol", "證券代號", "股票代號", "公司代號"])],
                "name": frame[_find_stock_master_column(frame, ["name", "證券名稱", "公司名稱", "股票名稱"])],
                "market": self.market,
                "industry": frame[_find_stock_master_column(frame, ["industry", "產業別", "產業類別"], optional=True)],
                "list_status": frame[
                    _find_stock_master_column(frame, ["list_status", "上市別", "狀態", "掛牌狀態"], optional=True)
                ],
                "source": frame[_find_stock_master_column(frame, ["source", "資料來源"], optional=True)],
            }
        )
        return _normalize_stock_master(normalized)

    def parse_html_payload(self, payload: str) -> pd.DataFrame:
        return _parse_isin_html_stock_master(payload=payload, market=self.market, required_status="上市")


class TpexStockMasterProvider(StockMasterProvider):
    market = "TPEX"
    fixture_prefix = "tpex_stocks"

    def build_url(self, settings: Settings) -> Optional[str]:
        return settings.tpex_stock_master_url

    def parse_payload(self, payload: str) -> pd.DataFrame:
        if _looks_like_html(payload):
            return self.parse_html_payload(payload)
        frame = pd.read_csv(StringIO(payload), dtype={"證券代號": str, "股票代號": str, "公司代號": str, "symbol": str, "代號": str})
        normalized = pd.DataFrame(
            {
                "symbol": frame[_find_stock_master_column(frame, ["symbol", "代號", "股票代號", "公司代號"])],
                "name": frame[_find_stock_master_column(frame, ["name", "名稱", "公司名稱", "股票名稱"])],
                "market": self.market,
                "industry": frame[_find_stock_master_column(frame, ["industry", "產業類別", "產業別"], optional=True)],
                "list_status": frame[
                    _find_stock_master_column(frame, ["list_status", "上櫃別", "狀態", "掛牌狀態"], optional=True)
                ],
                "source": frame[_find_stock_master_column(frame, ["source", "資料來源"], optional=True)],
            }
        )
        return _normalize_stock_master(normalized)

    def parse_html_payload(self, payload: str) -> pd.DataFrame:
        return _parse_isin_html_stock_master(payload=payload, market=self.market, required_status="上櫃")


def fetch_stock_master(
    markets: Iterable[str],
    settings: Settings,
    source_mode: str = SOURCE_MODE_AUTO,
    providers: Optional[Sequence[StockMasterProvider]] = None,
) -> pd.DataFrame:
    frame, _ = fetch_stock_master_with_diagnostics(
        markets=markets,
        settings=settings,
        source_mode=source_mode,
        providers=providers,
    )
    return frame


def fetch_stock_master_with_diagnostics(
    markets: Iterable[str],
    settings: Settings,
    source_mode: str = SOURCE_MODE_AUTO,
    providers: Optional[Sequence[StockMasterProvider]] = None,
) -> tuple[pd.DataFrame, list[dict]]:
    provider_registry = build_stock_master_provider_registry(providers)
    frames = []
    diagnostics = []
    for market in markets:
        normalized_market = normalize_market_name(market)
        provider = provider_registry.get(normalized_market)
        if provider is None:
            logger.info("stock_master_provider_missing", extra={"market": normalized_market})
            diagnostics.append(
                {
                    "market": normalized_market,
                    "source_mode": source_mode,
                    "final_status": "failed",
                    "rows_fetched": 0,
                    "attempts": [
                        {
                            "transport": "provider",
                            "status": "missing",
                            "rows_fetched": 0,
                            "error_category": "provider_missing",
                            "error_type": None,
                            "error_message": None,
                            "http_status_code": None,
                            "url": None,
                            "fixture_path": None,
                        }
                    ],
                }
            )
            continue
        frame, diagnostic = provider.fetch_with_diagnostic(settings=settings, source_mode=source_mode)
        diagnostics.append(diagnostic.to_dict())
        if frame.empty:
            continue
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=STOCK_COLUMNS), diagnostics

    merged = pd.concat(frames, ignore_index=True)
    return _normalize_stock_master(merged), diagnostics


def save_stock_master_diagnostics(diagnostics: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "diagnostics": diagnostics,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_stock_master_provider_registry(
    providers: Optional[Sequence[StockMasterProvider]] = None,
) -> Dict[str, StockMasterProvider]:
    active_providers = list(providers) if providers is not None else [
        TwseStockMasterProvider(),
        TpexStockMasterProvider(),
    ]
    return {provider.market: provider for provider in active_providers}


def load_stock_master(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=STOCK_COLUMNS)

    frame = pd.read_csv(path, dtype={"symbol": str})
    if frame.empty:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    return _normalize_stock_master(frame)


def upsert_stock_master(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing.empty and incoming.empty:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    if existing.empty:
        merged = incoming.copy()
    elif incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, incoming], ignore_index=True)

    merged = _normalize_stock_master(merged)
    merged = merged.drop_duplicates(subset=["market", "symbol"], keep="last")
    merged = merged.sort_values(["market", "symbol"]).reset_index(drop=True)
    return merged[STOCK_COLUMNS]


def save_stock_master(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _normalize_stock_master(frame).to_csv(path, index=False, encoding="utf-8")


def _normalize_stock_master(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in STOCK_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized["symbol"] = normalized["symbol"].where(normalized["symbol"].notna(), "").astype(str).str.strip()
    normalized["name"] = normalized["name"].where(normalized["name"].notna(), "").astype(str).str.strip()
    normalized["market"] = normalized["market"].where(normalized["market"].notna(), "").astype(str).str.upper().str.strip()
    normalized["industry"] = normalized["industry"].where(normalized["industry"].notna(), "").astype(str).str.strip()
    normalized["list_status"] = (
        normalized["list_status"].where(normalized["list_status"].notna(), "active").astype(str).str.lower().str.strip()
    )
    normalized["list_status"] = normalized["list_status"].replace(
        {
            "上市": "active",
            "上櫃": "active",
            "active": "active",
            "正常": "active",
            "掛牌中": "active",
            "下市": "inactive",
            "下櫃": "inactive",
            "inactive": "inactive",
            "停止買賣": "inactive",
        }
    )
    normalized["source"] = normalized["source"].where(normalized["source"].notna(), "").astype(str).str.strip()
    normalized = normalized[normalized["symbol"] != ""].reset_index(drop=True)
    # Filter out non-regular equities (warrants, bonds, leveraged/inverse ETFs, etc.)
    mask = normalized["symbol"].apply(_is_tradeable_equity)
    normalized = normalized[mask].reset_index(drop=True)
    return normalized[STOCK_COLUMNS]


def _is_tradeable_equity(symbol: str) -> bool:
    """Return True if the symbol is a regular stock or ETF that appears in daily price tables.

    Excluded:
    - Warrants: TPEX 6-digit codes starting with 7 (e.g. 700123, 739123)
    - Bonds / Government securities: starting with '020' or '010'
    - Leveraged/Inverse ETFs: symbol ends with L, R, K, U (e.g. 00631L, 00632R)
    - Bond ETFs that trade differently: ends with B (00710B)
    - Structured notes & TDR-type: ends with A, T, D (e.g. 00980A, 01001T)
    """
    s = str(symbol).strip()
    if not s:
        return False
    # Warrants: TPEX codes – 6 digits starting with 7 (700000-799999, 700000+ is 6 digits)
    if re.match(r'^7\d{5}$', s):
        return False
    # Bonds: starts with 020 or 010 (government bonds listed on exchange)
    if re.match(r'^0[12]\d', s):
        return False
    # Leveraged/inverse ETFs and structured products: ends with L, R, K, U, A, B, T, D
    if re.match(r'^\d{5,6}[LRKUABTDlrkuabtd]$', s):
        return False
    return True

def _parse_isin_html_stock_master(payload: str, market: str, required_status: str) -> pd.DataFrame:
    rows = _extract_html_rows(payload)
    if not rows:
        return pd.DataFrame(columns=STOCK_COLUMNS)

    parsed_rows = []
    current_section = None
    for row in rows:
        if len(row) == 1:
            current_section = _normalize_html_text(row[0])
            continue
        if len(row) < 5:
            continue

        first_cell = _normalize_html_text(row[0])
        list_status = _normalize_html_text(row[3])
        industry = _normalize_html_text(row[4]) if len(row) > 4 else ""

        section_name = current_section or ""
        valid_sections = ["股票", "ETF", "受益"]
        if not any(valid in section_name for valid in valid_sections):
            continue
        if required_status not in list_status:
            continue

        parsed_identity = _parse_symbol_name_cell(first_cell)
        if parsed_identity is None:
            continue

        symbol, name = parsed_identity
        parsed_rows.append(
            {
                "symbol": symbol,
                "name": name,
                "market": market,
                "industry": industry,
                "list_status": "active",
                "source": "isin.twse.com.tw",
            }
        )

    return _normalize_stock_master(pd.DataFrame(parsed_rows, columns=STOCK_COLUMNS))


def _parse_symbol_name_cell(value: str) -> Optional[tuple[str, str]]:
    normalized = value.replace("\u3000", " ").strip()
    match = re.match(r"^([0-9A-Z]{4,10})\s+(.+)$", normalized)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _looks_like_html(payload: str) -> bool:
    lowered = payload.lower()
    return "<table" in lowered or "<tr" in lowered or "<td" in lowered


def _normalize_html_text(text: str) -> str:
    return text.replace("\xa0", " ").replace("&nbsp;", " ").strip()


def _extract_html_rows(payload: str) -> list[list[str]]:
    rows = []
    for row_match in re.findall(r"<tr[^>]*>(.*?)</tr>", payload, flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_match, flags=re.IGNORECASE | re.DOTALL)
        if not cells:
            continue
        normalized_cells = []
        for cell in cells:
            text = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            text = (
                text.replace("&nbsp;", " ")
                .replace("&#160;", " ")
                .replace("&amp;", "&")
                .strip()
            )
            normalized_cells.append(text)
        rows.append(normalized_cells)
    return rows


def _find_stock_master_column(frame: pd.DataFrame, candidates: list[str], optional: bool = False) -> str:
    normalized_candidates = {candidate.strip().lower(): candidate for candidate in candidates}
    for column in frame.columns.tolist():
        key = str(column).strip().lower()
        if key in normalized_candidates:
            return column
    if optional:
        placeholder = "__missing_{0}".format(candidates[0])
        frame[placeholder] = ""
        return placeholder
    raise KeyError("Missing stock master column. candidates={0}".format(candidates))


def _decode_stock_master_payload(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp950", "big5", "big5hkscs"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _build_stock_master_fetch_diagnostic(
    market: str,
    source_mode: str,
    attempts: list[StockMasterFetchAttempt],
) -> StockMasterFetchDiagnostic:
    rows_fetched = 0
    final_status = "failed"
    for attempt in attempts:
        rows_fetched += attempt.rows_fetched
        if attempt.status == "success":
            final_status = "success"
            break
    return StockMasterFetchDiagnostic(
        market=market,
        source_mode=source_mode,
        final_status=final_status,
        rows_fetched=rows_fetched,
        attempts=attempts,
    )


def _classify_request_exception(exc: requests.RequestException) -> dict:
    error_message = str(exc)
    http_status_code = None
    error_category = "request"

    if isinstance(exc, requests.exceptions.HTTPError):
        http_status_code = exc.response.status_code if exc.response is not None else None
        error_category = "http_status"
    elif isinstance(exc, requests.exceptions.SSLError):
        error_category = "tls"
    elif isinstance(
        exc,
        (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.Timeout,
        ),
    ):
        error_category = "timeout"
    elif isinstance(exc, requests.exceptions.ConnectionError):
        lowered = error_message.lower()
        if (
            "nameresolutionerror" in lowered
            or "failed to resolve" in lowered
            or "nodename nor servname provided" in lowered
            or "temporary failure in name resolution" in lowered
        ):
            error_category = "dns"
        else:
            error_category = "connection"

    return {
        "error_category": error_category,
        "error_type": type(exc).__name__,
        "error_message": error_message,
        "http_status_code": http_status_code,
    }
