from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
import re
import subprocess
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
import requests

from sentinel.config import Settings
from sentinel.http_client import fetch_text
from sentinel.logging_utils import get_logger
from sentinel.providers import normalize_market_name
from sentinel.utils import daterange

logger = get_logger(__name__)

OFFICIAL_CALENDAR_COLUMNS = ["exchange", "calendar_date", "is_trading_day", "reason"]
PROVIDER_FRAME_COLUMNS = ["calendar_date", "is_trading_day", "reason"]
SOURCE_MODE_AUTO = "auto"
SOURCE_MODE_FIXTURE = "fixture"
SOURCE_MODE_NETWORK = "network"


class OfficialTradingCalendarProvider(ABC):
    exchange: str
    cache_prefix: str

    def fetch_range(
        self,
        start_date: date,
        end_date: date,
        settings: Settings,
        source_mode: str = SOURCE_MODE_AUTO,
    ) -> pd.DataFrame:
        years = sorted({current_date.year for current_date in daterange(start_date, end_date)})
        frames = []
        for year in years:
            year_frame = self.fetch_year(year=year, settings=settings, source_mode=source_mode)
            if year_frame.empty:
                continue
            frames.append(year_frame)

        if not frames:
            return pd.DataFrame(columns=OFFICIAL_CALENDAR_COLUMNS)

        combined = pd.concat(frames, ignore_index=True)
        combined["calendar_date"] = pd.to_datetime(combined["calendar_date"]).dt.date
        filtered = combined[combined["calendar_date"].between(start_date, end_date)].copy()
        filtered["exchange"] = self.exchange
        return filtered[OFFICIAL_CALENDAR_COLUMNS]

    def fetch_year(self, year: int, settings: Settings, source_mode: str = SOURCE_MODE_AUTO) -> pd.DataFrame:
        cache_path = settings.raw_dir / "trading_calendar" / "{0}_{1}.csv".format(self.cache_prefix, year)
        if cache_path.exists():
            frame = pd.read_csv(cache_path)
            if frame.empty:
                return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)
            frame["calendar_date"] = pd.to_datetime(frame["calendar_date"]).dt.date
            return frame[PROVIDER_FRAME_COLUMNS]

        if source_mode in {SOURCE_MODE_AUTO, SOURCE_MODE_FIXTURE}:
            fixture_payload = self._load_fixture_payload(year=year, settings=settings)
            if fixture_payload is not None:
                parsed = self.parse_payload(payload=fixture_payload, year=year)
                if not parsed.empty:
                    _save_provider_cache(cache_path=cache_path, frame=parsed)
                return parsed
            if source_mode == SOURCE_MODE_FIXTURE:
                logger.info(
                    "official_calendar_fixture_missing",
                    extra={"exchange": self.exchange, "year": year},
                )
                return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)

        if source_mode == SOURCE_MODE_FIXTURE:
            return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)

        url = self.build_url(year=year, settings=settings)
        if not url:
            logger.info(
                "official_calendar_provider_skipped",
                extra={"exchange": self.exchange, "year": year, "reason": "missing_url_template"},
            )
            return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)

        try:
            payload = fetch_text(
                url,
                headers={"User-Agent": settings.user_agent},
                timeout_seconds=settings.timeout_seconds,
            )
            parsed = self.parse_payload(payload=payload, year=year)
            if parsed.empty:
                return parsed
            _save_provider_cache(cache_path=cache_path, frame=parsed)
            return parsed
        except (requests.RequestException, RuntimeError, subprocess.CalledProcessError) as exc:
            logger.warning(
                "official_calendar_fetch_failed",
                extra={"year": year, "exchange": self.exchange, "url": url, "error": str(exc)},
            )
            return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)

    @abstractmethod
    def build_url(self, year: int, settings: Settings) -> Optional[str]:
        raise NotImplementedError

    @abstractmethod
    def parse_payload(self, payload: str, year: int) -> pd.DataFrame:
        raise NotImplementedError

    def fixture_path(self, year: int, settings: Settings) -> Path:
        return settings.raw_dir / "fixtures" / "trading_calendar" / "{0}_{1}.html".format(self.cache_prefix, year)

    def _load_fixture_payload(self, year: int, settings: Settings) -> Optional[str]:
        fixture_path = self.fixture_path(year=year, settings=settings)
        if not fixture_path.exists():
            return None
        return fixture_path.read_text(encoding="utf-8")


class TpexOfficialTradingCalendarProvider(OfficialTradingCalendarProvider):
    exchange = "TPEX"
    cache_prefix = "tpex_holiday"

    def build_url(self, year: int, settings: Settings) -> Optional[str]:
        roc_year = year - 1911
        return settings.tpex_holiday_url_template.format(roc_year=roc_year, year=year)

    def parse_payload(self, payload: str, year: int) -> pd.DataFrame:
        return parse_tpex_holiday_html(payload=payload, year=year)


class TwseOfficialTradingCalendarProvider(OfficialTradingCalendarProvider):
    exchange = "TWSE"
    cache_prefix = "twse_holiday"

    def build_url(self, year: int, settings: Settings) -> Optional[str]:
        roc_year = year - 1911
        return settings.twse_holiday_url_template.format(roc_year=roc_year, year=year)

    def parse_payload(self, payload: str, year: int) -> pd.DataFrame:
        return parse_twse_holiday_response(payload=payload)


def fetch_official_trading_calendar(
    start_date: date,
    end_date: date,
    markets: Iterable[str],
    settings: Settings,
    providers: Optional[Sequence[OfficialTradingCalendarProvider]] = None,
    source_mode: str = SOURCE_MODE_AUTO,
) -> pd.DataFrame:
    provider_registry = build_official_calendar_provider_registry(providers)
    frames = []
    for market in markets:
        exchange = normalize_market_name(market)
        provider = provider_registry.get(exchange)
        if provider is None:
            logger.info(
                "official_calendar_provider_missing",
                extra={"exchange": exchange, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )
            continue
        market_frame = provider.fetch_range(
            start_date=start_date,
            end_date=end_date,
            settings=settings,
            source_mode=source_mode,
        )
        if market_frame.empty:
            continue
        frames.append(market_frame)

    if not frames:
        return pd.DataFrame(columns=OFFICIAL_CALENDAR_COLUMNS)

    merged = pd.concat(frames, ignore_index=True)
    merged["calendar_date"] = pd.to_datetime(merged["calendar_date"]).dt.date
    merged = merged.drop_duplicates(subset=["exchange", "calendar_date"], keep="last")
    merged = merged.sort_values(["exchange", "calendar_date"]).reset_index(drop=True)
    return merged[OFFICIAL_CALENDAR_COLUMNS]


def build_official_calendar_provider_registry(
    providers: Optional[Sequence[OfficialTradingCalendarProvider]] = None,
) -> Dict[str, OfficialTradingCalendarProvider]:
    active_providers = list(providers) if providers is not None else [
        TwseOfficialTradingCalendarProvider(),
        TpexOfficialTradingCalendarProvider(),
    ]
    return {provider.exchange: provider for provider in active_providers}


def parse_tpex_holiday_html(payload: str, year: int) -> pd.DataFrame:
    return _parse_generic_holiday_html(
        payload=payload,
        year=year,
        month_candidates=["Month", "月份", "月別"],
        date_candidates=["Date", "日期"],
        description_candidates=["Description", "說明", "備註"],
    )


def parse_twse_holiday_response(payload: str) -> pd.DataFrame:
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    rows = []
    for line in lines:
        match = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$", line)
        if not match:
            continue
        calendar_date = pd.to_datetime(match.group(1)).date()
        remainder = match.group(2).strip()
        is_trading_day = _infer_twse_is_trading_day(remainder)
        rows.append(
            {
                "calendar_date": calendar_date,
                "is_trading_day": is_trading_day,
                "reason": None if is_trading_day else remainder,
            }
        )
    return pd.DataFrame.from_records(rows, columns=PROVIDER_FRAME_COLUMNS)


def _parse_generic_holiday_html(
    payload: str,
    year: int,
    month_candidates: List[str],
    date_candidates: List[str],
    description_candidates: List[str],
) -> pd.DataFrame:
    rows = _extract_html_rows(payload)
    if not rows:
        return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)

    header_index = _find_header_row_index(
        rows=rows,
        column_candidates=[month_candidates, date_candidates, description_candidates],
    )
    if header_index is None:
        return pd.DataFrame(columns=PROVIDER_FRAME_COLUMNS)

    header = rows[header_index]
    data_rows = []
    for row in rows[header_index + 1:]:
        if len(row) < len(header):
            row = row + ([""] * (len(header) - len(row)))
        elif len(row) > len(header):
            row = row[: len(header)]
        data_rows.append(row)

    raw_frame = pd.DataFrame(data_rows, columns=header)
    month_column = _find_column(raw_frame.columns.tolist(), month_candidates)
    date_column = _find_column(raw_frame.columns.tolist(), date_candidates)
    description_column = _find_column(raw_frame.columns.tolist(), description_candidates)

    raw_frame[month_column] = raw_frame[month_column].replace("", pd.NA).ffill()
    parsed_rows = []
    current_description = None
    for row in raw_frame.to_dict(orient="records"):
        month_name = str(row.get(month_column, "")).strip()
        day_value = str(row.get(date_column, "")).strip()
        description_value = row.get(description_column)
        description = str(description_value).strip() if pd.notna(description_value) else None
        if description:
            current_description = description
        elif current_description:
            description = current_description

        calendar_date = _parse_month_day(year=year, month_name=month_name, day_value=day_value)
        if calendar_date is None:
            continue

        is_trading_day = _infer_is_trading_day(description)
        reason = None if is_trading_day else (description or "holiday")
        parsed_rows.append(
            {
                "calendar_date": calendar_date,
                "is_trading_day": is_trading_day,
                "reason": reason,
            }
        )

    return pd.DataFrame.from_records(parsed_rows, columns=PROVIDER_FRAME_COLUMNS)


def _find_column(columns: List[str], candidates: List[str]) -> str:
    for column in columns:
        normalized = _normalize_column_name(column)
        if any(_normalize_column_name(candidate) in normalized for candidate in candidates):
            return column
    raise ValueError("Required column not found: {0}".format(", ".join(candidates)))


def _find_header_row_index(rows: List[List[str]], column_candidates: List[List[str]]) -> Optional[int]:
    for index, row in enumerate(rows):
        normalized_row = [_normalize_column_name(cell) for cell in row]
        matched_all = True
        for candidates in column_candidates:
            if not any(
                any(_normalize_column_name(candidate) in cell for candidate in candidates)
                for cell in normalized_row
            ):
                matched_all = False
                break
        if matched_all:
            return index
    return None


def _normalize_column_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def _parse_month_day(year: int, month_name: str, day_value: str) -> Optional[date]:
    if not month_name or not day_value:
        return None

    month_lookup = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    month = month_lookup.get(month_name)
    if month is None:
        return None

    day_token = day_value.split(" ", 1)[0].strip()
    if not day_token.isdigit():
        return None
    return date(year, month, int(day_token))


def _infer_is_trading_day(description: Optional[str]) -> bool:
    if not description:
        return False
    return "last trading day" in description.lower()


def _infer_twse_is_trading_day(text: str) -> bool:
    normalized = text.replace(" ", "")
    return ("開始交易" in normalized) or ("最後交易" in normalized)


def _extract_html_rows(payload: str) -> List[List[str]]:
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


def _save_provider_cache(cache_path: Path, frame: pd.DataFrame) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    export_frame = frame.copy()
    export_frame["calendar_date"] = pd.to_datetime(export_frame["calendar_date"]).dt.strftime("%Y-%m-%d")
    export_frame.to_csv(cache_path, index=False, encoding="utf-8")
