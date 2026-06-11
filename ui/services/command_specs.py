"""CLI 指令規格定義（Declarative CommandSpec）。

新增 CLI 指令時只需在此新增 CommandSpec，無需修改頁面程式碼。
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class FieldSpec:
    """描述一個 CLI 參數的表單欄位。"""

    name: str
    type: str  # text | number | date | select | multiselect | checkbox | path
    label: str = ""
    required: bool = False
    default: Any = None
    options: list = field(default_factory=list)
    help: str = ""
    min_val: Any = None
    max_val: Any = None
    step: Any = None
    placeholder: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name.replace("-", " ").replace("_", " ").title()


@dataclass
class CommandSpec:
    """描述一個 CLI 指令的完整規格。"""

    command_id: str
    description: str
    argv_base: list[str]  # e.g. ["sentinel", "run"]
    fields: list[FieldSpec] = field(default_factory=list)
    validator: Optional[Callable[[dict], Optional[str]]] = None
    result_parser: Optional[Callable[[str, str], dict]] = None
    page_slot: str = ""
    is_long_task: bool = True  # 超過 5 秒的任務


def _sentinel_base() -> list[str]:
    """回傳 sentinel CLI 的基底呼叫方式（python -m sentinel）。"""
    return [sys.executable, "-m", "sentinel"]


def _validate_date_range(params: dict) -> Optional[str]:
    from datetime import date as _date

    start = params.get("start-date")
    end = params.get("end-date")
    if start and end:
        try:
            if _date.fromisoformat(str(start)) > _date.fromisoformat(str(end)):
                return "開始日期不可晚於結束日期"
        except ValueError:
            return "日期格式錯誤，請使用 YYYY-MM-DD"
    return None


def build_argv(spec: CommandSpec, params: dict) -> list[str]:
    """依據 CommandSpec 與使用者填入的 params 組合 argv。"""
    argv = list(spec.argv_base)
    for f in spec.fields:
        val = params.get(f.name)
        if val is None or val == "" or val is False:
            continue
        flag = f"--{f.name}"
        if f.type == "checkbox":
            if val:
                argv.append(flag)
        elif f.type == "multiselect":
            if isinstance(val, list):
                for v in val:
                    argv += [flag, str(v)]
        else:
            argv += [flag, str(val)]
    return argv


def argv_to_preview(argv: list[str]) -> str:
    """把 argv list 轉為可複製的 shell 字串。"""
    return " ".join(shlex.quote(a) for a in argv)


# ---------------------------------------------------------------------------
# 指令規格定義
# ---------------------------------------------------------------------------

INIT_DB = CommandSpec(
    command_id="init-db",
    description="初始化資料庫 Schema（首次執行或 Schema 升級後執行）",
    argv_base=_sentinel_base() + ["init-db"],
    fields=[
        FieldSpec(
            "database-url", "text", label="資料庫 URL", help="留空使用環境變數 TS_DATABASE_URL"
        ),
    ],
    is_long_task=False,
    page_slot="data_sync",
)

SYNC_CALENDAR = CommandSpec(
    command_id="sync-calendar",
    description="同步交易日曆（需指定日期區間）",
    argv_base=_sentinel_base() + ["sync-calendar"],
    fields=[
        FieldSpec("start-date", "date", required=True, label="開始日期"),
        FieldSpec("end-date", "date", required=True, label="結束日期"),
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=["TWSE"],
        ),
        FieldSpec(
            "source-mode",
            "select",
            label="資料來源模式",
            options=["auto", "fixture", "network"],
            default="auto",
        ),
        FieldSpec("database-url", "text", label="資料庫 URL", help="留空使用環境變數"),
    ],
    validator=_validate_date_range,
    page_slot="data_sync",
)

SYNC_STOCKS = CommandSpec(
    command_id="sync-stocks",
    description="同步股票主檔（公司基本資訊）",
    argv_base=_sentinel_base() + ["sync-stocks"],
    fields=[
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=["TWSE"],
        ),
        FieldSpec(
            "source-mode",
            "select",
            label="資料來源模式",
            options=["auto", "fixture", "network"],
            default="auto",
        ),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    page_slot="data_sync",
)

SYNC = CommandSpec(
    command_id="sync",
    description="自動補齊股價（抓取缺失日期的價格資料直到今日）",
    argv_base=_sentinel_base() + ["sync"],
    fields=[
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=["TWSE", "TPEX"],
        ),
        FieldSpec("scan", "checkbox", label="補完後執行策略掃描"),
        FieldSpec(
            "direction",
            "select",
            label="掃描方向（--scan 時有效）",
            options=["", "long", "short"],
            default="",
        ),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    page_slot="data_sync",
)

BACKFILL_YAHOO = CommandSpec(
    command_id="backfill-yahoo",
    description="從 Yahoo Finance 補填歷史股價",
    argv_base=_sentinel_base() + ["backfill-yahoo"],
    fields=[
        FieldSpec("start-date", "date", required=True, label="開始日期"),
        FieldSpec("end-date", "date", required=True, label="結束日期"),
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=["TWSE", "TPEX"],
        ),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    validator=_validate_date_range,
    page_slot="data_sync",
)

SYNC_INSTITUTIONAL = CommandSpec(
    command_id="sync-institutional",
    description="同步三大法人買賣超（TWSE T86 / TPEX）",
    argv_base=_sentinel_base() + ["sync-institutional"],
    fields=[
        FieldSpec("date", "date", required=True, label="資料日期"),
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=["TWSE", "TPEX"],
        ),
        FieldSpec(
            "source-mode",
            "select",
            label="資料來源模式",
            options=["auto", "fixture", "network"],
            default="auto",
        ),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    page_slot="data_sync",
)

RUN = CommandSpec(
    command_id="run",
    description="執行完整 Pipeline（抓價格 → 計算指標 → 策略掃描）",
    argv_base=_sentinel_base() + ["run"],
    fields=[
        FieldSpec("start-date", "date", required=True, label="開始日期"),
        FieldSpec("end-date", "date", required=True, label="結束日期"),
        FieldSpec("trading-date", "date", label="掃描交易日（留空=結束日期）"),
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=[],
        ),
        FieldSpec(
            "direction",
            "select",
            label="方向篩選",
            options=["", "long", "short"],
            default="",
        ),
        FieldSpec("strategy-path", "path", label="策略設定檔路徑（留空使用預設）"),
        FieldSpec("skip-indicators", "checkbox", label="跳過技術指標計算"),
        FieldSpec("skip-strategies", "checkbox", label="跳過策略掃描"),
        FieldSpec(
            "calendar-source-mode",
            "select",
            label="行事曆來源",
            options=["auto", "fixture", "network"],
            default="auto",
        ),
        FieldSpec(
            "price-source-mode",
            "select",
            label="股價來源",
            options=["auto", "fixture", "network"],
            default="auto",
        ),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    validator=_validate_date_range,
    page_slot="daily_scan",
)

CHECK_STOCK = CommandSpec(
    command_id="check-stock",
    description="逐條檢核個股訊號觸發狀況",
    argv_base=_sentinel_base() + ["check-stock"],
    fields=[
        FieldSpec("symbol", "text", required=True, label="股票代號（例：2330）"),
        FieldSpec("date", "date", label="交易日（留空=最新）"),
        FieldSpec("signal-path", "path", label="訊號設定檔路徑"),
        FieldSpec("dataset-path", "path", label="資料集路徑"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="stock_check",
)

IMPORT_MINUTE_BARS = CommandSpec(
    command_id="import-minute-bars",
    description="匯入 FinMind 1 分鐘線 CSV，聚合為 5 分鐘 K 棒寫入 DB",
    argv_base=_sentinel_base() + ["import-minute-bars"],
    fields=[
        FieldSpec("csv", "path", required=True, label="CSV 檔案路徑"),
        FieldSpec(
            "chunk-size",
            "number",
            label="每批處理行數",
            default=100000,
            min_val=1000,
            max_val=1000000,
        ),
        FieldSpec("database-url", "text", label="主資料庫 URL"),
        FieldSpec("intraday-database-url", "text", label="日內資料庫 URL"),
    ],
    page_slot="backtest",
)

BACKFILL_AGG_BARS = CommandSpec(
    command_id="backfill-aggregated-bars",
    description="一次性補建 3 日 / 47 日聚合 K 棒",
    argv_base=_sentinel_base() + ["backfill-aggregated-bars"],
    fields=[
        FieldSpec("database-url", "text", label="資料庫 URL"),
        FieldSpec("dataset-path", "path", label="資料集路徑"),
    ],
    page_slot="backtest",
)

BACKTEST = CommandSpec(
    command_id="backtest",
    description="執行回測",
    argv_base=_sentinel_base() + ["backtest"],
    fields=[
        FieldSpec("start-date", "date", required=True, label="開始日期"),
        FieldSpec("end-date", "date", required=True, label="結束日期"),
        FieldSpec(
            "market",
            "multiselect",
            label="市場",
            options=["TWSE", "TPEX"],
            default=[],
        ),
        FieldSpec(
            "execution-model",
            "select",
            label="執行模型",
            options=["daily", "minute_bar"],
            default="daily",
        ),
        FieldSpec(
            "strategy-mode",
            "select",
            label="策略模式",
            options=["standard", "tomorrow_star"],
            default="standard",
        ),
        FieldSpec("symbol", "text", label="限定股票代號（留空=全部）"),
        FieldSpec("initial-capital", "number", label="初始資金（留空=無限制）", min_val=0),
        FieldSpec("position-size", "number", label="單筆金額", default=100000, min_val=1000),
        FieldSpec("benchmark-symbol", "text", label="基準指標代號（選填）"),
        FieldSpec("strategy-path", "path", label="策略設定檔路徑"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    validator=_validate_date_range,
    page_slot="backtest",
)

UPDATE_INTRADAY_STATS = CommandSpec(
    command_id="update-intraday-stats",
    description="更新日內策略歷史勝率統計",
    argv_base=_sentinel_base() + ["update-intraday-stats"],
    fields=[
        FieldSpec(
            "lookback-days", "number", label="回溯天數", default=180, min_val=30, max_val=730
        ),
        FieldSpec(
            "gain-threshold",
            "number",
            label="獲利門檻",
            default=0.05,
            min_val=0.01,
            max_val=0.5,
            step=0.01,
        ),
        FieldSpec("min-samples", "number", label="最低樣本數", default=5, min_val=1, max_val=50),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    page_slot="intraday",
)

CAPTURE_SNAPSHOT = CommandSpec(
    command_id="capture-intraday-snapshot",
    description="擷取盤中即時快照（MIS 資料）",
    argv_base=_sentinel_base() + ["capture-intraday-snapshot"],
    fields=[
        FieldSpec("time", "text", label="快照時間標籤（例：12:00）", default="12:00"),
        FieldSpec("top", "number", label="抓取量排前 N 檔", default=300, min_val=50, max_val=1000),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="intraday",
)

RUN_INTRADAY = CommandSpec(
    command_id="run-intraday",
    description="執行明日之星策略掃描（13:00 盤中）",
    argv_base=_sentinel_base() + ["run-intraday"],
    fields=[
        FieldSpec("top", "number", label="監控量排前 N 檔", default=300, min_val=50, max_val=1000),
        FieldSpec(
            "min-gain",
            "number",
            label="最低漲幅門檻",
            default=0.075,
            min_val=0.01,
            max_val=0.3,
            step=0.005,
        ),
        FieldSpec("notify-telegram", "checkbox", label="傳送 Telegram 通知"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    page_slot="intraday",
)

UPDATE_INTRADAY_TRADES = CommandSpec(
    command_id="update-intraday-trades",
    description="結算前一日未平倉模擬交易",
    argv_base=_sentinel_base() + ["update-intraday-trades"],
    fields=[
        FieldSpec("real-time", "checkbox", label="使用即時開盤價（MIS）"),
        FieldSpec(
            "price-type",
            "select",
            label="結算價格類型",
            options=["open", "last"],
            default="open",
        ),
        FieldSpec("allow-today", "checkbox", label="允許結算今日交易（測試用）"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="intraday",
)

MONITOR_INTRADAY_TRADES = CommandSpec(
    command_id="monitor-intraday-trades",
    description="監控未平倉交易停利/停損觸發",
    argv_base=_sentinel_base() + ["monitor-intraday-trades"],
    fields=[
        FieldSpec(
            "threshold",
            "number",
            label="停利/停損門檻",
            default=0.02,
            min_val=0.005,
            max_val=0.2,
            step=0.005,
        ),
        FieldSpec("force-close", "checkbox", label="強制平倉全部未平倉"),
        FieldSpec("allow-today", "checkbox", label="允許監控今日交易（測試用）"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="intraday",
)

ADD_INTRADAY_TRADE = CommandSpec(
    command_id="add-intraday-trade",
    description="手動新增模擬交易",
    argv_base=_sentinel_base() + ["add-intraday-trade"],
    fields=[
        FieldSpec("symbol", "text", required=True, label="股票代號"),
        FieldSpec("price", "number", required=True, label="進場價格", min_val=0.01, step=0.01),
        FieldSpec(
            "market",
            "select",
            label="市場（留空自動偵測）",
            options=["", "TWSE", "TPEX"],
            default="",
        ),
        FieldSpec("notes", "text", label="備註"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="intraday",
)

CLEAR_INTRADAY_TRADES = CommandSpec(
    command_id="clear-intraday-trades",
    description="清除所有模擬交易記錄",
    argv_base=_sentinel_base() + ["clear-intraday-trades"],
    fields=[
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="intraday",
)

SCHEDULER = CommandSpec(
    command_id="scheduler",
    description="啟動自動化日內策略排程器",
    argv_base=_sentinel_base() + ["scheduler"],
    fields=[
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    page_slot="intraday",
)

INSPECT_STATUS = CommandSpec(
    command_id="inspect-status",
    description="顯示各資料表最新日期狀態",
    argv_base=_sentinel_base() + ["inspect", "status"],
    fields=[
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="inspect",
)

INSPECT_COMPLETENESS = CommandSpec(
    command_id="inspect-completeness",
    description="檢查指定日期資料完整性",
    argv_base=_sentinel_base() + ["inspect", "completeness"],
    fields=[
        FieldSpec("date", "date", required=True, label="目標日期"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="inspect",
)

INSPECT_RESULTS = CommandSpec(
    command_id="inspect-results",
    description="顯示策略掃描結果",
    argv_base=_sentinel_base() + ["inspect", "results"],
    fields=[
        FieldSpec("strategy", "text", label="策略 ID（留空=全部）"),
        FieldSpec("date", "date", label="目標日期（留空=最新）"),
        FieldSpec("min-volume", "number", label="最低成交量", min_val=0),
        FieldSpec(
            "direction",
            "select",
            label="方向",
            options=["", "long", "short"],
            default="",
        ),
        FieldSpec("limit", "number", label="最大筆數", default=50, min_val=1, max_val=500),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="inspect",
)

INSPECT_LOGS = CommandSpec(
    command_id="inspect-logs",
    description="顯示 Job 執行記錄或隔離日誌",
    argv_base=_sentinel_base() + ["inspect", "logs"],
    fields=[
        FieldSpec(
            "type",
            "select",
            label="日誌類型",
            options=["jobs", "quarantine"],
            default="jobs",
        ),
        FieldSpec("limit", "number", label="最大筆數", default=20, min_val=1, max_val=200),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="inspect",
)

INSPECT_INTRADAY_TRADES = CommandSpec(
    command_id="inspect-intraday-trades",
    description="顯示模擬交易日誌",
    argv_base=_sentinel_base() + ["inspect", "intraday-trades"],
    fields=[
        FieldSpec("export", "checkbox", label="匯出為 CSV"),
        FieldSpec("database-url", "text", label="資料庫 URL"),
    ],
    is_long_task=False,
    page_slot="inspect",
)

ALL_SPECS: dict[str, CommandSpec] = {
    s.command_id: s
    for s in [
        INIT_DB,
        SYNC_CALENDAR,
        SYNC_STOCKS,
        SYNC,
        BACKFILL_YAHOO,
        SYNC_INSTITUTIONAL,
        RUN,
        CHECK_STOCK,
        IMPORT_MINUTE_BARS,
        BACKFILL_AGG_BARS,
        BACKTEST,
        UPDATE_INTRADAY_STATS,
        CAPTURE_SNAPSHOT,
        RUN_INTRADAY,
        UPDATE_INTRADAY_TRADES,
        MONITOR_INTRADAY_TRADES,
        ADD_INTRADAY_TRADE,
        CLEAR_INTRADAY_TRADES,
        SCHEDULER,
        INSPECT_STATUS,
        INSPECT_COMPLETENESS,
        INSPECT_RESULTS,
        INSPECT_LOGS,
        INSPECT_INTRADAY_TRADES,
    ]
}
