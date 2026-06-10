from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TS_",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("data"))
    output_dir: Path = Field(default=Path("outputs"))
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=1)
    retry_backoff_seconds: float = Field(default=1.0, ge=0)
    retry_jitter_seconds: float = Field(default=0.25, ge=0)
    min_delay_seconds: float = Field(default=0.2, ge=0)
    max_delay_seconds: float = Field(default=0.8, ge=0)
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0"
    )
    data_version: str = Field(default="v1")
    log_level: str = Field(default="INFO")
    database_url: Optional[str] = Field(default=None)
    intraday_database_url: Optional[str] = Field(default="sqlite:///data/db/intraday.db")
    twse_holiday_url_template: str = Field(
        default="https://www.twse.com.tw/holidaySchedule/holidaySchedule?queryYear={roc_year}&response=html"
    )
    tpex_holiday_url_template: str = Field(
        default="https://www.tpex.org.tw/storage/en-us/web/bulletin/trading_date/trading_date_{roc_year}.htm"
    )
    twse_stock_master_url: Optional[str] = Field(
        default="https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    )
    tpex_stock_master_url: Optional[str] = Field(
        default="https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    )
    tg_token: Optional[str] = Field(default=None)
    tg_chat_id: Optional[str] = Field(default=None)
    indicator_cache_dir: Optional[Path] = Field(default=None)
    indicator_calc_version: str = Field(default="v1")

    @property
    def resolved_indicator_cache_dir(self) -> Path:
        return self.indicator_cache_dir or (self.data_dir / "cache")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def price_dataset_path(self) -> Path:
        return self.processed_dir / "daily_prices.csv"

    @property
    def stock_master_path(self) -> Path:
        return self.processed_dir / "stocks.csv"

    @property
    def strategy_config_path(self) -> Path:
        return Path("config") / "strategies.json"

    @property
    def signal_config_path(self) -> Path:
        return Path("config") / "signals.json"
