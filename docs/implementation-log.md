# 實作與操作紀錄

## 2026-03-08

### 日線 fixture 重播與資料正規化

- 補齊 `run --calendar-source-mode fixture --price-source-mode fixture` 的離線重播流程。
- 修正 `daily_prices.csv` 讀取時 `symbol` 型別不一致問題，避免歷史資料與新抓資料分組錯誤，影響 `MA5/MA20` 與 `scan_results`。
- 補上 CLI fixture 整合測試，驗證 `daily_prices`、`technical_indicators`、`scan_results` 可正確落表。
- 驗證指令：
  - `./.venv/bin/python -m pytest -q`
  - `./.venv/bin/python -m pytest tests/test_cli.py -q`

### 日線 validity 與 quarantine

- 新增 `daily_prices` 基本 validity 規則：
  - `high >= max(open, close)`
  - `low <= min(open, close)`
  - `volume >= 0`
- 無效 row 會自 `run` 主流程隔離，不寫入正式 `daily_prices`；若有 DB，會寫入 `data_quarantine`。
- 補上 invalid fixture 與 CLI/DB 單元測試。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_cli.py tests/test_db.py tests/test_quality.py -q`

### Completeness Summary

- 新增 `run` metadata completeness summary，輸出 `expected_rows`、`actual_rows`、`quarantined_rows`、`completeness_pct`。
- 目前 basis 為 `known_symbols_in_local_dataset`，用本地既有 symbol universe 估算 requested trading days 的覆蓋率。
- 補上 completeness 單元測試與 CLI metadata 驗證。
- 驗證指令：
  - `./.venv/bin/python -m pytest -q`

### Active Stocks 主檔

- 新增 `sync-stocks` 指令，使用 fixture 建立 `data/processed/stocks.csv` 與 DB `stocks` 主檔。
- `run` 的 completeness 會優先使用 `stocks.csv` 中 `list_status=active` 的 symbol universe 作為母數。
- 補上 `sync-stocks` CLI 測試、stock master 單元測試，以及 `run` 搭配 stock master 的 metadata 驗證。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_cli.py tests/test_completeness.py tests/test_stock_master.py -q`

### Stock Master Provider 架構

- 將 `sync-stocks` 提升為 `TWSE` / `TPEx` provider 架構，支援 `auto` / `fixture` / `network` source mode。
- `auto` 目前策略為：先讀 fixture，再讀使用者設定的 `TS_TWSE_STOCK_MASTER_URL` / `TS_TPEX_STOCK_MASTER_URL`。
- `network` mode 暫時只支援讀取與 fixture 相同欄位結構的 CSV，尚未做 live source 驗證。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_stock_master.py tests/test_cli.py -q`
  - `./.venv/bin/python -m sentinel sync-stocks --help`

### Stock Master Official-Style Parser

- `TWSE` / `TPEx` stock master provider 新增官方風格欄位名稱 alias parser。
- 目前可解析例如 `證券代號/證券名稱/產業別/上市別` 與 `代號/名稱/產業類別/上櫃別` 這類 CSV 欄位。
- 尚未做 live source 驗證，仍以 fixture 與 parser 測試為主。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_stock_master.py -q`
  - `./.venv/bin/python -m pytest -q`

### ISIN HTML Stock Master Parser

- 確認官方 stock master 來源可用 `https://isin.twse.com.tw/isin/C_public.jsp?strMode=2` 與 `strMode=4`。
- provider 新增 HTML table parser，並在 HTML 模式只抽取「股票」區塊，排除 ETF、權證、ETN 等其他商品。
- 目前已把這兩個 URL 設成 stock master 預設值，但尚未做完整 live smoke test。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_stock_master.py -q`
  - `./.venv/bin/python -m pytest -q`

### Stock Master Official HTML Replay

- 修正 `stock master` fixture / network payload decode 路徑，新增 `UTF-8`、`UTF-8-SIG`、`CP950`、`Big5`、`Big5-HKSCS` fallback。
- 實際以 `curl` 下載 TWSE / TPEx 官方 ISIN HTML，保存到 `/tmp/sentinel-live-smoke/data/raw/fixtures/stocks/` 後，使用 `sync-stocks --source-mode fixture` 完成真實資料重播。
- 本次 replay 結果：
  - `data/processed/stocks.csv`: `1924` rows
  - SQLite `stocks`: `1924` rows
  - 市場分布：`TWSE=1045`、`TPEX=879`
- 目前尚未完成 app 內建 `requests` 直連官方站台的 live network smoke test；現階段已確認 parser 與資料落地流程可處理真實官方 HTML。
- 另外在 2026-03-08 補跑 `sync-stocks --source-mode network`，目前這台環境的 Python `requests` 直連 `isin.twse.com.tw` 仍會遇到 DNS resolution failure，因此正式 live network path 尚待另一次環境驗證。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_stock_master.py -q`
  - `TS_DATA_DIR=/tmp/sentinel-live-smoke/data TS_OUTPUT_DIR=/tmp/sentinel-live-smoke/output ./.venv/bin/python -m sentinel sync-stocks --market TWSE --market TPEX --source-mode fixture --database-url sqlite:////tmp/sentinel-live-smoke/live_smoke.db`
  - `TS_DATA_DIR=/tmp/sentinel-live-network/data TS_OUTPUT_DIR=/tmp/sentinel-live-network/output ./.venv/bin/python -m sentinel sync-stocks --market TWSE --market TPEX --source-mode network --database-url sqlite:////tmp/sentinel-live-network/live_network.db`
  - `./.venv/bin/python -m pytest -q`

### Stock Master Network Diagnostics

- `stock master` provider 新增結構化 diagnostics，會記錄 market、source mode、attempts、transport、error category、HTTP status。
- `sync-stocks` 新增 `--diagnostics-path`，預設輸出到 `outputs/stock_master/sync_diagnostics.json`。
- network 例外目前會分類為 `dns`、`timeout`、`tls`、`http_status`、`connection`、`parse`，方便快速判斷是環境問題還是 parser 問題。
- 2026-03-08 實測目前環境的 network diagnostics：
  - `TWSE -> dns`
  - `TPEX -> dns`
- 補上 provider 與 CLI 測試，驗證 diagnostics JSON 會寫出且失敗分類正確。
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_stock_master.py tests/test_cli.py -q`
  - `./.venv/bin/python -m pytest -q`

### Calendar Sync Runtime Fix

- 修正 `sync-calendar` 在使用 `sqlite:///data/db/sentinel.db` 時，若父資料夾不存在會直接失敗的問題；現在 `create_db_engine()` 會自動建立 SQLite 父目錄。
- `sync-calendar` / `sync-stocks` / `run` / `backtest` 若有帶 `--database-url`，現在會先自動補 schema，再進行寫入，不必強制先跑一次 `init-db`。
- 修正 TPEx holiday parser，改成可自動尋找真正的 header row，降低官方 HTML 標題列/前置說明列造成的欄位辨識失敗。
- 2026-03-08 實際重跑：
  - `python -m sentinel sync-calendar --market TWSE --market TPEX --database-url sqlite:///data/db/sentinel.db --start-date 2026-01-01 --end-date 2026-12-31`
  - 結果：成功輸出 `730` rows，並寫入 SQLite `trading_calendar=730`
  - `TWSE` 來源仍有 DNS warning，但流程不再 crash，會完成 fallback calendar 輸出

### Indicator / Strategy / Backtest Expansion

- 指標引擎由 `MA5/MA20` 擴充為 `MA5/10/20/60/240`、`RSI14`、`MACD`、`KD`、`ATR14`、`Bollinger Bands`、`volume_ma5`。
- 新增策略設定模組與預設策略檔 `config/strategies.json`，目前內建：
  - `mvp_ma_crossover`
  - `rsi_pullback`
  - `volume_breakout`
- `run` 新增 `--strategy-path`，掃描結果與 `strategies` table 改為支援多策略。
- 新增 `backtest` CLI，會讀本地價格資料集、重算指標、依策略產生訊號，輸出：
  - `outputs/backtests/<start>_<end>/report.csv`
  - `outputs/backtests/<start>_<end>/trades.csv`
  - `outputs/backtests/<start>_<end>/metadata.json`
- `backtest` 目前使用 `next_open_to_close` 成交模型，並輸出 `total_return`、`cagr`、`mdd`、`win_rate`、`turnover`、`benchmark_total_return`。
- 補上 indicator、strategy、backtest、CLI 整合測試，確認：
  - 多指標可正確寫入 `technical_indicators`
  - 多策略可落地 `scan_results`
  - `backtest` CLI 可產出報表
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_pipeline.py tests/test_strategies.py tests/test_db.py tests/test_cli.py -q`
  - `./.venv/bin/python -m sentinel run --help`
  - `./.venv/bin/python -m sentinel backtest --help`

### Live Daily Price Verification And Market-Scoped Keys

- 2026-03-08 直接對官方來源補跑 live `run`：
  - `python -m sentinel run --market TWSE --market TPEX --database-url sqlite:///data/db/sentinel.db --start-date 2026-03-02 --end-date 2026-03-06 --trading-date 2026-03-06`
- 修正 TWSE 日線 parser：
  - 官方 payload 的代號會長成 `="0050"`，原本 `isdigit()` 與 `raw_line.startswith("=")` 會把真實資料列誤判掉
  - 現在會先正規化 symbol token，再進行資料列判斷
- 新增 shared HTTP fallback：
  - `requests` 失敗時退回 `curl`
  - 共用在 `daily_prices` 與 `official_calendar`
  - 補上 `UTF-8` / `UTF-8-SIG` / `CP950` / `Big5` / `Big5-HKSCS` decode fallback
- 修正 SQLite legacy schema 問題：
  - `stocks` / `daily_prices` / `technical_indicators` / `scan_results` 現在都以 `market + symbol` 為核心鍵
  - `create_schema()` 會自動偵測舊版 SQLite 表結構，必要時重建並搬移資料
  - 修掉舊版 `stocks(symbol)` 導致 `ON CONFLICT (market, symbol)` 無法命中的問題
- 本次 live run 結果：
  - `job_runs.status=success`
  - `rows_fetched=30815`
  - `daily_prices=30815`
  - `stocks=6166`
  - `technical_indicators=12312`
  - 最新交易日：`2026-03-06`
  - `TWSE` 與 `TPEx` 都完成真實抓取
- 觀察到的 live 行為：
  - `TPEx` 個別日期偶爾會回 `curl exit 28/56`
  - 目前 retry 後可恢復，流程能正常完成
- 新增回歸測試：
  - 跨市場同代號不互蓋
  - SQLite 舊 schema 自動升級
  - `stock_master` 同代號跨市場保留
- 驗證指令：
  - `./.venv/bin/python -m pytest tests/test_db.py tests/test_stock_master.py tests/test_cli.py -q`
  - `./.venv/bin/python -m pytest -q`
