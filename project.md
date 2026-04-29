# 專案需求規格書：跨市場策略選股系統 (Taiwan Stock First)

## 1. 專案目標與範圍
開發一個具備自動化數據採集、技術分析運算、策略篩選功能的投資輔助系統。  
第一階段以台股 (TWSE/TPEx) 日線資料為核心，並保留擴充至美股與加密貨幣的架構。

In Scope (MVP):
- 台股日線資料採集與清洗
- 指標計算 (MA, RSI, MACD 等)
- 規則式選股掃描與每日輸出
- 基礎回測與績效驗證報表

Out of Scope (MVP):
- 即時盤中交易
- 自動下單
- 衍生品策略

## 2. 成功指標 (KPI)
- 每日排程成功率 >= 99.5% (30 日滾動)
- 資料完整率 >= 99.9% (symbol x trading_date)，定義見 2.1
- 單次全市場掃描完成時間 <= 15 分鐘（定義見 2.2）
- 同一資料版本重跑結果一致率 100% (可重現)
- 異常資料告警 5 分鐘內可被偵測

### 2.1 資料完整率定義與量測
- **分子**: 實際寫入 `daily_prices` 且通過 Validity 檢查的 `(symbol, trading_date)` 筆數。
- **分母**: 當日 `trading_calendar` 認定為交易日且 `stocks.list_status = 'active'` 的標的數（排除當日新上市、下市、長期停牌等依規則排除之標的）。
- **公式**: `完整率 = 分子 / 分母`；目標 >= 99.9%。
- **量測**: 於每日採集/檢查任務結束後寫入 `job_runs` 或監控指標（如 `data_completeness_pct`），供儀表板與告警使用。

### 2.2 掃描時效說明
- **掃描運算**: 單次全市場掃描執行時間 <= 15 分鐘（僅指 `scan_strategy()` 運算階段）。
- **端到端 SLA**: 當日掃描結果最晚 **20:30** 產出；排程 20:00 啟動後，20:00–20:30 可包含指標計算、寫入 DB、產出 JSON/CSV、通知等，兩者不衝突。

## 3. 技術堆疊建議 (Tech Stack)
- 語言: Python 3.11+
- 環境管理: 內建 `venv` (虛擬環境資料夾命名為 `.venv`)
- 依賴管理: `pip` + `requirements.txt`；正式環境建置時使用既有 `requirements.txt` 不升級，以利可重現（可選：`pip-tools` 鎖版）。
- 資料庫: PostgreSQL 16 + TimescaleDB
- 技術分析庫: Pandas-TA (預設) / TA-Lib (可選)；若 Pandas-TA 棄用或 breaking change，預留指標介面/Adapter 以便遷移。
- 數據採集: Requests + Pandas + 官方 API/公開資料端點
- 排程: Airflow (正式環境) / GitHub Actions (小規模)
- 設定管理: `.env` + pydantic-settings
- 資料庫遷移: Alembic
- 測試框架: Pytest
- 部署工具: Docker (可選，開發優先使用 venv)
- 觀測性: 結構化日誌 (JSON) + 指標監控 (Prometheus/Grafana 可選)

## 4. 系統模組規劃
### A. 數據採集模組 (Data Ingestion)
資料來源:
- 臺灣證券交易所 (TWSE)
- 證券櫃檯買賣中心 (TPEx)

**資料來源對照表（實作時請填寫具體 URL/文件）**:

| 資料類型 | 主要來源 | 取得方式/API | 更新頻率 | 備援或備註 |
|----------|----------|--------------|----------|------------|
| 日 K 線 (OHLCV) | TWSE / TPEx | 官方盤後 CSV 或公開 API | 每交易日盤後 | 可選: FinMind、Yahoo 等，需註明授權 |
| 三大法人買賣超 | TWSE / TPEx | 法人買賣超統計 | 每交易日 | — |
| 融資融券餘額 | TWSE / TPEx | 信用交易統計 | 每交易日 | — |
| 月營收、季 EPS、PE、殖利率 | 公開資訊觀測站 / 報價源 | 依實際選用 API | 月/季/日 | 需定義「可得日」防 look-ahead |
| 除權息/公司行動 | 交易所或公開資訊 | 除權息預告與異動 | 事件驅動 | 寫入 `corporate_actions` |

抓取目標:
- 日 K 線 (OHLCV)
- 三大法人買賣超
- 融資融券餘額與增減
- 基本面資料 (月營收、季 EPS、PE、殖利率)
- 公司行動/除權息事件

關鍵要求:
- 支援 Backfill (歷史回補) 與 Incremental (日更)
- API 限速與重試機制 (exponential backoff + jitter)
- 具備 idempotent upsert，重跑不得造成重複資料
- **自動辨識休市日**: 整合 `trading_calendar` 機制，非交易日不觸發抓取告警
- **採集階段性與斷點續傳**: 每次採集分配 `batch_id`，記錄個別 symbol 狀態 (success/failed)，支援僅補齊未完成部分。
- **速率控制**: 內建 Proxy 支持與隨機延遲，避免官方 IP 封鎖。

### B. 還原價與指標引擎 (Adjustment + TA Engine)
預設指標:
- 均線: MA5/10/20/60/240
- 動量: KD, RSI, MACD
- 波動: Bollinger Bands, ATR

還原價規範:
- 建立 `corporate_actions` 事件表，儲存除權息/減資等事件
- 以事件日計算 `adjustment_factor`，並維護 `cumulative_adjustment_factor`
- `adjusted_close = close * cumulative_adjustment_factor`
- 指標一律以調整後價格計算，避免除權息造成訊號失真
- 演算法版本化 (`adjustment_version`)，確保結果可追溯

自定義指標:
- 建立 `IndicatorFactory`，允許透過組合欄位與函式建立新指標
- 所有指標需記錄參數與版本 (`indicator_name`, `params_hash`, `calc_version`)

### C. 策略篩選器 (Scanner)
多維度條件:
- 技術面: `close > MA20` 且 `RSI < 30`
- 籌碼面: `投信連續買超 >= 3 天`
- 量能面: `volume > 2 * MA(volume, 5)`

執行規範:
- 每日掃描全市場標的
- 輸出 JSON/CSV + run metadata (run_id, data_version, scan_time)
- 支援策略設定檔 (YAML/JSON) 以便擴充規則；設定檔需定義條件欄位、運算子、閾值、連續 N 日等（schema 與 `strategies.params_json` 對齊）。
- `scan_results.signals_json` 建議結構：`{"conditions": [{"name": "...", "passed": true/false, "value": ...}], ...}`，便於報表與除錯。

資料窗規範:
- 任一策略的最小歷史資料天數 = `max(最長技術指標週期, 連續天數條件) + 5`
- 例如使用 MA20，最少需 25 個交易日，不可只抓近 5 日

## 5. 非功能需求 (NFR)
- 時區: 全系統使用 `Asia/Taipei`
- 排程:
  - 日資料抓取: 每交易日 18:30
  - 指標計算與掃描: 每交易日 20:00
- SLA:
  - 當日掃描結果最晚 20:30 產出
  - 單一資料源失敗可自動重試 3 次
- 可維運性:
  - 所有任務須寫入 `job_runs` (開始/結束/狀態/錯誤摘要)
  - 失敗時發送告警 (Slack/Email 任一)
- 安全性:
  - API 金鑰儲存於環境變數，不得硬編碼
  - 輸入參數需做格式驗證與 SQL 注入防護
- 測試與可靠性:
  - 核心計算邏輯 (還原價、TA 指標) 必須包含單元測試 (Unit Tests)
  - 支援手動觸發 backfill 與指定日期區間重跑
- 開發環境規範:
  - 必須在 `.venv` 虛擬環境內開發
  - 虛擬環境資料夾 (.venv/) 嚴禁進入 Git 版控
  - 新增套件後需執行 `pip freeze > requirements.txt` 更新依賴清單
- 資源管理與清理 (Retention Policy):
  - `job_runs`, `data_quarantine` 定期清理 (預設保留 90 天)
  - 技術指標表可依版本清理舊版數據以節省空間

## 6. 資料品質規範 (Data Quality)
- Completeness: 每日應有資料筆數需落在合理區間（量測方式見 2.1）
- Uniqueness: `(symbol, trading_date)` 必須唯一
- Validity:
  - `high >= max(open, close)`
  - `low <= min(open, close)`
  - `volume >= 0`
- Timeliness: 逾時未更新需告警
- 異常隔離: 不合規資料寫入 `data_quarantine` 表，不直接覆蓋正式資料（表結構見 §7）

**資料可得時間（防 look-ahead）**:
- 日 K / 法人 / 融資券: 當日盤後即可用（T 日收盤後採集視為 T 日可得）。
- 月營收: 依公開資訊觀測站公告日，建議採用「公告日 T」起算可用。
- 季報 EPS / PE: 依財報公告日定義可用日。
- 除權息: `ex_date` 當日收盤後可納入還原價計算；回測時當日報價已為除權息後價，需依 `corporate_actions` 還原。

## 7. 資料庫 Data Contract
### 核心表
1. `stocks`
- PK: `symbol`
- 欄位: `name`, `market`, `industry`, `list_status`, `created_at`, `updated_at`

2. `daily_prices`
- PK: `(symbol, trading_date)`
- 欄位: `open`, `high`, `low`, `close`, `volume`, `turnover`, `adjusted_close`, `data_version`, `updated_at`
- 索引: `trading_date`, `(symbol, trading_date DESC)`
- **優化**: 資料量過大時建議採用 PostgreSQL Declarative Partitioning (by YEAR/MONTH)。

3. `institutional_flows`
- PK: `(symbol, trading_date)`
- 欄位: `foreign_net`, `investment_trust_net`, `dealer_net`, `total_net`

4. `margin_balances`
- PK: `(symbol, trading_date)`
- 欄位: `margin_balance`, `short_balance`, `margin_change`, `short_change`

5. `corporate_actions`
- PK: `action_id`
- 欄位: `symbol`, `ex_date`, `action_type`, `cash_dividend`, `stock_dividend_ratio`, `adjustment_factor`, `source`
- 索引: `(symbol, ex_date)`

6. `technical_indicators`
- PK: `(symbol, trading_date, indicator_name, params_hash, calc_version)`
- 欄位: `value`, `source_field`, `updated_at`

7. `scan_results`
- PK: `(run_id, symbol, strategy_id)`
- 欄位: `trading_date`, `score`, `signals_json`, `data_version`, `created_at`

8. `job_runs`
- PK: `run_id`
- 欄位: `job_name`, `start_time`, `end_time`, `status`, `rows_in`, `rows_out`, `error_summary`

9. `trading_calendar`
- PK: `(exchange, calendar_date)`
- 欄位: `is_trading_day`, `reason` (如: 颱風假), `updated_at`

10. `strategies`
- PK: `strategy_id`
- 欄位: `name`, `version`, `params_json`, `description`, `is_active`

11. `data_quarantine`
- PK: `quarantine_id`
- 欄位: `source_table`, `source_pk_or_batch`, `raw_payload_json`, `violated_rule` (e.g. validity/completeness), `detected_at`, `resolution` (pending/rejected/fixed), `resolved_at`, `notes`
- 用途: 不合規資料隔離，不寫入正式表；可事後審核、修正或丟棄。

## 8. 回測與驗證規範
- 回測假設:
  - 手續費與交易稅需納入
  - **成交價模型**: MVP 固定採用「次日開盤價」；若改為 VWAP 需版本化並在報表註明 `execution_model_version`。
  - **流動性門檻**: 例如「最近 20 日平均成交金額 >= 門檻」或「成交量 >= N 張」，需在策略/回測設定中明確定義並記錄於報表 (`liquidity_rule`)。
- 防偏誤:
  - 嚴禁使用未來資料 (look-ahead bias)
  - 指標與財報資料需考慮公告可得時間
- 產出指標:
  - CAGR, MDD, Sharpe, Win Rate, Turnover
  - 與基準 (例如加權指數) 比較超額報酬

## 9. 開發階段與驗收標準 (Roadmap + Exit Criteria)
### Phase 1 (MVP Data)
目標:
- 建立台股資料採集管線，回補近 3 年日線與法人資料

驗收:
- 資料完整率 >= 99.5%
- 重跑 3 次資料列數一致
- 日更成功率 >= 99%

### Phase 2 (TA Engine)
目標:
- 建立調整後價格與常用指標計算流程

驗收:
- MA/RSI/MACD 抽樣比對誤差 <= 1e-6
- 指標計算時間 <= 10 分鐘 (全市場)
- 指標版本追溯可查

### Phase 3 (Strategy & Scanner)
目標:
- 支援規則式策略設定與每日掃描輸出

驗收:
- 每日 20:30 前完成掃描
- 輸出含 run metadata，且可重現
- 至少 3 個策略模板可用

### Phase 4 (Backtest & Expansion)
目標:
- 補齊回測報表並抽象化市場資料介面，擴充美股資料源

驗收:
- 回測報表可自動生成
- 新增市場時核心策略程式碼無需改動
- 完成至少 1 個美股資料源接入 PoC

### Phase 5 (Optional: Visualization)
目標:
- 提供簡單的 Web 或 Dashboard 介面顯示每日篩選結果與績效監控。

驗收:
- 可透過瀏覽器查看每日選股名單
- 提供策略回測結果的圖表化展示 (Equity Curve, Drawdown)

## 10. 給 AI 的執行指令 (Prompt, 修正版)
以下為最小可行範例，完整策略以 §4 策略設定檔與多維度條件為準。請根據本規格書撰寫 Python 腳本與模組，要求如下:

1. 抓取台股指定日期區間的盤後個股資料，最少需覆蓋最近 25 個交易日 (支援 MA20 計算)。  
2. 使用 Pandas 清洗資料並計算 MA5、MA20。  
3. 實作選股條件: `close > MA5` 且 `MA5 > MA20`。  
4. 加入限速、重試、逾時、錯誤日誌與重跑 idempotent。  
5. 輸出 JSON/CSV，且附上 `run_id`, `trading_date`, `data_version`。  
6. 以函式化結構提供:
   - `fetch_prices()`
   - `compute_indicators()`
   - `scan_strategy()`
   - `save_results()`

## 11. 操作手冊位置
為避免規格書與操作步驟重複維護，所有實際操作流程統一維護於：

- `docs/operation-manual.md`

本規格書僅保留需求、設計與驗收標準；若操作命令與本文件描述不一致，請以操作手冊為準。
