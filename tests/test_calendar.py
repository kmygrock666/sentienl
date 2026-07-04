from __future__ import annotations

from datetime import date

from sentinel.config import Settings
from sentinel.datasources.official_calendar import (
    SOURCE_MODE_FIXTURE,
    TwseOfficialTradingCalendarProvider,
    build_official_calendar_provider_registry,
    fetch_official_trading_calendar,
    parse_tpex_holiday_html,
    parse_twse_holiday_response,
)
from sentinel.domain.calendar import (
    build_trading_calendar,
    filter_trading_dates,
    is_default_trading_day,
    is_weekend,
)


def test_is_weekend_detects_saturday() -> None:
    assert is_weekend(date(2026, 3, 7)) is True
    assert is_default_trading_day(date(2026, 3, 6)) is True


def test_build_trading_calendar_marks_weekend_and_missing_weekday() -> None:
    calendar_frame = build_trading_calendar(
        start_date=date(2026, 3, 6),
        end_date=date(2026, 3, 8),
        markets=["TWSE"],
        observed_dates={"TWSE": {date(2026, 3, 6)}},
    )

    friday = calendar_frame[calendar_frame["calendar_date"] == date(2026, 3, 6)].iloc[0]
    saturday = calendar_frame[calendar_frame["calendar_date"] == date(2026, 3, 7)].iloc[0]
    sunday = calendar_frame[calendar_frame["calendar_date"] == date(2026, 3, 8)].iloc[0]

    assert bool(friday["is_trading_day"]) is True
    assert friday["reason"] is None
    assert bool(saturday["is_trading_day"]) is False
    assert saturday["reason"] == "weekend"
    assert bool(sunday["is_trading_day"]) is False
    assert sunday["reason"] == "weekend"


def test_parse_tpex_holiday_html_and_filter_trading_dates() -> None:
    payload = """
    <table>
      <tr><th>Month</th><th>Date</th><th>Description</th></tr>
      <tr><td>January</td><td>22 (Wednesday)</td><td>Last Trading Day before Lunar New Year Holiday</td></tr>
      <tr><td></td><td>23 (Thursday)</td><td>Last Clearing &amp; Settlement Days before Lunar New Year Holiday</td></tr>
      <tr><td></td><td>24 (Friday)</td><td></td></tr>
      <tr><td></td><td>27 (Monday)</td><td>Lunar New Year Holiday</td></tr>
    </table>
    """
    official_frame = parse_tpex_holiday_html(payload, year=2026)
    official_overrides = official_frame.assign(exchange="TWSE")

    trading_dates = filter_trading_dates(
        exchange="TWSE",
        start_date=date(2026, 1, 22),
        end_date=date(2026, 1, 27),
        official_overrides=official_overrides,
    )
    calendar_frame = build_trading_calendar(
        start_date=date(2026, 1, 22),
        end_date=date(2026, 1, 27),
        markets=["TWSE"],
        official_overrides=official_overrides,
    )

    assert date(2026, 1, 22) in trading_dates
    assert date(2026, 1, 23) not in trading_dates
    assert date(2026, 1, 24) not in trading_dates
    assert date(2026, 1, 27) not in trading_dates
    assert (
        calendar_frame[calendar_frame["calendar_date"] == date(2026, 1, 23)]
        .iloc[0]["reason"]
        .startswith("Last Clearing")
    )


def test_official_calendar_provider_registry_contains_twse_and_tpex() -> None:
    registry = build_official_calendar_provider_registry()

    assert "TWSE" in registry
    assert "TPEX" in registry
    assert isinstance(registry["TWSE"], TwseOfficialTradingCalendarProvider)


def test_parse_twse_holiday_response_uses_text_format() -> None:
    payload = """
    115 年市場開休市日期
    日期 名稱 說明
    2026-01-02 國曆新年開始交易日 國曆新年開始交易。
    2026-02-12 市場無交易，僅辦理結算交割作業
    2026-02-23 農曆春節後開始交易日 農曆春節後開始交易。
    """

    frame = parse_twse_holiday_response(payload)

    assert list(frame["calendar_date"]) == [date(2026, 1, 2), date(2026, 2, 12), date(2026, 2, 23)]
    assert bool(frame.iloc[0]["is_trading_day"]) is True
    assert bool(frame.iloc[1]["is_trading_day"]) is False
    assert "結算交割" in frame.iloc[1]["reason"]
    assert bool(frame.iloc[2]["is_trading_day"]) is True


def test_fetch_official_trading_calendar_uses_local_fixture(tmp_path) -> None:
    fixture_dir = tmp_path / "raw" / "fixtures" / "trading_calendar"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / "tpex_holiday_2026.html"
    fixture_path.write_text(
        """
        <table>
          <tr><th>Month</th><th>Date</th><th>Description</th></tr>
          <tr><td>March</td><td>2 (Monday)</td><td>Last Trading Day before Holiday</td></tr>
          <tr><td></td><td>3 (Tuesday)</td><td>Holiday</td></tr>
        </table>
        """,
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path)

    frame = fetch_official_trading_calendar(
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 3),
        markets=["TPEX"],
        settings=settings,
        source_mode=SOURCE_MODE_FIXTURE,
    )

    assert list(frame["exchange"]) == ["TPEX", "TPEX"]
    assert list(frame["calendar_date"]) == [date(2026, 3, 2), date(2026, 3, 3)]
    assert bool(frame.iloc[0]["is_trading_day"]) is True
    assert frame.iloc[1]["reason"] == "Holiday"


def test_parse_tpex_holiday_html_detects_header_row_after_title_block() -> None:
    payload = """
    <table>
      <tr><td colspan="3">TPEx Trading Calendar</td></tr>
      <tr><td>Generated at 2026-01-01</td><td></td><td></td></tr>
      <tr><th>Month</th><th>Date</th><th>Description</th></tr>
      <tr><td>January</td><td>2 (Friday)</td><td>Last Trading Day before Holiday</td></tr>
      <tr><td></td><td>3 (Saturday)</td><td>Holiday</td></tr>
    </table>
    """

    frame = parse_tpex_holiday_html(payload, year=2026)

    assert list(frame["calendar_date"]) == [date(2026, 1, 2), date(2026, 1, 3)]
    assert bool(frame.iloc[0]["is_trading_day"]) is True
    assert bool(frame.iloc[1]["is_trading_day"]) is False
