# 操作手冊 (Operation Manual)

本文件是唯一的操作手冊，包含系統所有可用 CLI 指令的詳細功能說明、內部執行邏輯，以及輸出資料表的欄位定義。

---

## 常用指令快速參考 (Quick Reference)

| 類別 | 功能 | 指令範例 |
| :--- | :--- | :--- |
| **系統** | 初始化資料庫 | `./.venv/bin/python -m sentinel init-db` |
| **同步** | 同步市場行事曆 | `./.venv/bin/python -m sentinel sync-calendar --start-date 2024-01-01 --end-date 2024-12-31 --market TWSE --market TPEX` |
| **同步** | 同步標的主檔 | `./.venv/bin/python -m sentinel sync-stocks --market TWSE --market TPEX` |
| **掃描** | 執行日線掃描 | `./.venv/bin/python -m sentinel run --market TWSE --market TPEX --start-date 2024-03-01 --end-date 2024-03-22` |
| **回測** | 執行策略回測 | `./.venv/bin/python -m sentinel backtest --start-date 2024-01-01 --end-date 2024-03-22 --execution-model daily` |
| **日內** | 啟動排程器 | `./.venv/bin/python -m sentinel scheduler` |
| **日內** | 執行明日之星掃描 | `./.venv/bin/python -m sentinel run-intraday --top 300 --min-gain 0.075` |
| **同步** | 自動補齊股價資料 | `./.venv/bin/python -m sentinel sync --market TWSE --market TPEX` |
| **檢查**| 檢查資料庫狀態 | `./.venv/bin/python -m sentinel inspect status` |
| **個股** | 檢驗個股觀察訊號 | `./.venv/bin/python -m sentinel check-stock --symbol 2492` |

---

## 目錄
1. [系統初始化與環境配置](#1-系統初始化與環境配置)
2. [基礎資料同步指令](#2-基礎資料同步指令)
3. [核心日線掃描指令](#3-核心日線掃描指令)
4. [個股觀察訊號檢驗](#4-個股觀察訊號檢驗)
5. [日線與分鐘歷史回測](#5-日線與分鐘歷史回測)
6. [資料庫與系統狀態查詢](#6-資料庫與系統狀態查詢)
7. [「明日之星」日內當沖模組 (Intraday)](#7-明日之星日內當沖模組-intraday)

---

## 1. 系統初始化與環境配置

### 環境變數 (`.env`)
- `TS_DATABASE_URL`: 主資料庫連線字串（開發預設：`sqlite:///data/db/sentinel.db`）
- `TS_INTRADAY_DATABASE_URL`: 分鐘級/日內專用資料庫（開發預設：`sqlite:///data/db/intraday.db`）
- `TS_DATA_DIR` / `TS_OUTPUT_DIR`: 預設為 `data/` 與 `outputs/`。

### `init-db`
- **指令範例**：`./.venv/bin/python -m sentinel init-db`
- **功能**：初始化所有資料表的 Schema。
- **執行邏輯**：連線至指定的 `database_url`，透過 SQLAlchemy Metadata 建立 `stocks`, `daily_prices`, `trading_calendar` 等基礎資料表。若表已存在則跳過。
- **輸出目標**：資料庫 Schema 更新。

---

## 2. 基礎資料同步指令

### `sync-calendar`
- **指令範例**：`./.venv/bin/python -m sentinel sync-calendar --start-date 2024-01-01 --end-date 2024-12-31 --market TWSE --market TPEX`
- **功能**：同步證交所 (TWSE) 與櫃買中心 (TPEX) 的休假日與交易日曆。
- **執行邏輯**：抓取官方公告之假日 JSON/HTML，建立連續日期序列並標記每一天是否為交易日 (`is_trading_day`)。
- **輸出欄位 (Trading Calendar)**：
  - `market` (市場), `date` (日期), `is_trading_day` (是否開市: 0/1)。

### `sync-stocks`
- **指令範例**：`./.venv/bin/python -m sentinel sync-stocks --market TWSE --market TPEX`
- **功能**：獲取最新上市櫃純股票清單，過濾掉權證、ETF 及特別股。
- **執行邏輯**：從 ISIN 官方網站爬取列表，使用代碼長度與特定前綴進行「純股票」過濾後，將 `is_active` 為 1 的標的存入資料庫。
- **輸出欄位 (Stock Master)**：
  - `market` (市場), `symbol` (代號), `name` (名稱), `industry` (產業分類), `is_active` (是否上市/櫃: 0/1)。
  - **診斷輸出**：`outputs/stock_master/sync_diagnostics.json` (紀錄爬蟲網路狀態與錯誤分類)。

### `sync` (Automatic Price Sync)
- **指令範例**：`./.venv/bin/python -m sentinel sync --market TWSE --market TPEX`
- **功能**：自動偵測資料庫缺失日期，抓取股價至最新日期。
- **執行邏輯**：
  1. 查詢 `daily_prices` 資料表各市場的 `Max(trading_date)`。
  2. 計算起始日（最後日期 + 1）與結束日（執行當天）。
  3. 自動執行 `sync-calendar` 與 `run` (Pipeline) 流程補齊資料。
- **參數**：
  - `--market`: 指定同步市場（可重複，預設 TWSE, TPEX）。
  - `--scan`: 同步完成後，是否自動對最新交易日執行策略掃描（預設關閉）。
  - `--direction`: 若開啟掃描，可過濾做多/做空訊號。

---

## 3. 核心日線掃描指令

### `run` (Daily Pipeline)
- **指令範例**：`./.venv/bin/python -m sentinel run --market TWSE --market TPEX --start-date 2026-04-29 --end-date 2026-04-29 --trading-date 2026-04-29`
- **功能**：一鍵完成「抓取股價 -> 運算技術指標 -> 策略篩選與輸出」。
- **執行邏輯**：
  1. 依據時間區間批次抓取每日 `daily_prices` 股價。
  2. 自動排除連續異常（如股價停滯不前的變造資料，標記 `is_stuck_data`）。
  3. 為所有標的計算長短期均線 (MA)、長黑K低點、高點等技術指標。
  4. 載入 `config/strategies.json` 裡所有 `is_active=true` 的策略，進行向量化布林邏輯條件篩選。
  5. 將符合所有條件的股票輸出成報表。
- **參數**：`--start-date`, `--end-date`, `--trading-date` (基準日), `--strategy-path` 等。
- **輸出資料**：
  - DB: `daily_prices` (含開高低收量), `technical_indicators` (各指標欄位), `scan_results` (命中的選股紀錄)。
  - File: `outputs/<date>/scan_results.csv` 以及 Markdown 表格，欄位：日期、策略名稱、方向、市場、代號、名稱、產業、收盤價、符合度。
  - **TradingView 專用檔**: `outputs/<date>/tradingview_<date>.txt` (格式為 `市場:代號`)，可直接匯入 TradingView 自選清單。

#### TradingView 清單匯入步驟
1. 開啟 TradingView 網頁版或 App。
2. 點擊右側「自選表 (Watchlist)」選單中的「匯入清單 (Import List)」。
3. 選擇 `outputs/` 目錄下對應日期的 `tradingview_<date>.txt` 即可。

---

## 4. 個股觀察訊號檢驗

> 此功能與選股策略（`strategies.json`）**完全獨立**。選股策略是掃全市場找標的，觀察訊號是針對**已持有或關注的個股**，確認當日是否出現特定的進場或出場條件。

### `check-stock`

- **指令範例**：
  ```bash
  # 檢驗最新一天
  ./.venv/bin/python -m sentinel check-stock --symbol 2492

  # 指定日期
  ./.venv/bin/python -m sentinel check-stock --symbol 2492 --date 2025-10-21
  ```
- **功能**：讀取 `config/signals.json` 中的所有觀察訊號，對指定股票的當日資料逐條比對，輸出每條規則的觸發結果與各條件的實際數值。
- **執行邏輯**：
  1. 從本地 `daily_prices.csv` 載入該股票的歷史資料並計算技術指標。
  2. 逐條掃描 `signals.json` 中 `is_active: true` 且不需要盤中資料的訊號。
  3. 對需要盤中資料（1H K線、5分K、Tick）或尚未實作的訊號，列出但標記為「無法自動檢驗」。
- **參數**：
  - `--symbol`（必填）：股票代號，例如 `2492`。
  - `--date`：指定日期（YYYY-MM-DD），省略時自動取該股最新一天。
  - `--signal-path`：覆蓋預設的 `config/signals.json` 路徑。
  - `--dataset-path`：覆蓋預設的 `data/processed/daily_prices.csv` 路徑。
- **輸出範例**：
  ```
  ╔══════════════════════════════════════════════════════════════╗
  ║  個股訊號檢驗 — 華新科 2492  （2025-10-21）                  ║
  ╚══════════════════════════════════════════════════════════════╝

  📈 做多進場訊號
  ────────────────────────────────────────────────────────────────
    ✅ 倒T線反轉做多
         ✅ 昨日收倒T線: 1.00 == 1.00
         ✅ 昨日股價在MA5之上: 105.50 > 103.20
         ✅ 昨日量能大於均量: 12345 > 8900
         ✅ 今日低點不破昨日低點: 104.00 >= 103.80
         ✅ 今日收盤站上昨日實體中點: 108.00 > 104.65

  ⚠️  警示 / 出場訊號
  ────────────────────────────────────────────────────────────────
    ❌ 仙人指路黑K警示
    ❌ 爆大量後量縮新高黑K
    ❌ 多頭跌破五日線量縮出場

  ⚙️  需盤中資料 / 待實作（無法自動檢驗）
  ────────────────────────────────────────────────────────────────
    ⚙️  1H MACD遞減+爆大量新高出清  [規則 3]  — 需 1h 資料
    ⚙️  大漲但廣度轉弱  [規則 4]  — 需大盤廣度資料
    ⚙️  多頭大漲後關緊閉預警  [規則 5]  — 需 tick 資料
    ⚙️  多頭回補缺口先跌破缺口高點  [規則 8]  — 缺口偵測邏輯待實作
    ⚙️  五分K底底高頂部失守出場  [規則 10]  — 需 5m 資料
    ⚙️  五分K底底高站上20MA做多  [規則 11]  — 需 5m 資料
    ⚙️  獲利加減碼規則  [規則 1]  — 人工規則
  ```

### `config/signals.json` 訊號設定檔

獨立於 `config/strategies.json` 之外，結構如下：

```json
{
  "signals": [
    {
      "signal_id": "shooting_star_reversal_buy",
      "name": "倒T線反轉做多",
      "direction": "long",           // long / warning / observation / position_mgmt
      "source_rule": "規則 2/6",
      "is_active": true,
      "requires_intraday": false,    // true 時 check-stock 不自動運算，僅列出
      "params": {
        "min_history_days": 25,
        "conditions": [ ... ]        // 條件格式與 strategies.json 相同
      }
    }
  ]
}
```

| `direction` 值 | 意義 |
|:---|:---|
| `long` | 做多進場訊號 |
| `warning` | 警示 / 出場訊號 |
| `observation` | 觀察型（無條件判斷，人工觀察） |
| `position_mgmt` | 部位管理規則（系統不自動偵測） |

目前已設定的 11 條訊號來源：規則 1–12（規則 1 為部位管理，規則 3/4/5/8/10/11 需盤中資料，規則 2/6/7/9/12 可用日線自動偵測）。

---

## 5. 日線與分鐘歷史回測

### `import-minute-bars`
- **指令範例**：`./.venv/bin/python -m sentinel import-minute-bars --csv data/raw/minute_bars.csv`
- **功能**：將下載的原始 1 分鐘 K 線 CSV 轉換並匯入為 5 分鐘 K 線。
- **執行邏輯**：使用 `pandas` 依照 `5T` 聚合 1m K 線並取出 `(Open, High, Low, Close, Volume)`，接著採用 Bulk Insert `ON CONFLICT DO NOTHING` 的極速寫入模式，灌入 `intraday.db` 的 `minute_bars` 資料表。
- **輸出欄位 (Minute Bar)**：
  - `market`, `symbol`, `trading_date`, `bar_time` (該 5m K線時間), `open`, `high`, `low`, `close`, `volume`。

### `backtest`
- **指令範例 (日線)**：`./.venv/bin/python -m sentinel backtest --start-date 2024-01-01 --end-date 2026-03-24 --execution-model daily --initial-capital 100000`
- **指令範例 (指定股票)**：`./.venv/bin/python -m sentinel backtest --symbol 2330 --execution-model daily`
- **指令範例 (資金限制)**：`./.venv/bin/python -m sentinel backtest --initial-capital 1000000 --position-size 100000`
- **指令範例 (明日之星)**：`./.venv/bin/python -m sentinel backtest --start-date 2024-03-01 --end-date 2026-03-24 --execution-model minute_bar --strategy-mode tomorrow_star`
- **功能**：套用條件篩選與交易模擬引擎，得出策略的長期績效報告與逐筆明細。
- **參數說明**：
  - `--initial-capital`：初始本金。若未指定，則為「無限資金」模式。
  - `--position-size`：單筆交易投入金額（預設 100,000）。限制模式下，若餘額不足將跳過訊號。
  - `--symbol`：指定單一股票代碼進行回測。
- **執行邏輯**：
  - **日線回測 (`--execution-model daily`)**：先以 `run` 的邏輯掃出訊號後，進行模擬交易：
    - **進場**：訊號產生日之 **隔日開盤價 (`Open`)**。
    - **出場**：滿足以下任一條件即模擬賣出：
      1.  **固定持有**：達到 `strategies.json` 內設定的 `holding_period_days` 天數，以 **當日收盤價 (`Close`)** 出場。
      2.  **動態停損 (Trailing Stop)**：若持倉期間 **收盤價跌破前一日實體 K 線低點** (`Close < min(Prev_Open, Prev_Close)`)，則以該日 **收盤價** 提前出場。
  - **分鐘精確回測 (`--execution-model minute_bar`)**：使用 `minute_bars` 進行高解析度追蹤：
    - 進場：突破 / 跌破 5分K 5日均線之價格。
    - 出場：達到設定之停利 (`+3%`)、動態追漲停 (`limit_up_pct`) 或跌破日均線的嚴格保護停損。
    - **明日之星模式 (`--strategy-mode tomorrow_star`)**：針對「明日之星」專用的 13:00 歷史訊號還原回測。
      - **標的過濾**：自動排除 6 碼代號（權證/ETF），僅鎖定 4 碼標準股票。
- **輸出欄位說明**：
  - `總報酬率`：累計複利報酬百分比。
  - `年化報酬 (CAGR)`：折算為每年的幾何平均報酬率。
  - `最大回撤 (MDD)`：淨值從最高點回落的最大幅度。在無限資金模式下，MDD 可能會因為多筆負報酬疊加而出現誇張數值；在資金限制模式下則較具參考價值。
  - `report.csv` (績效總表)：包含勝率、平均報酬、MDD 等核心數據。
  - `trades.csv` (逐筆明細)：包含每筆交易的進出場日期與原因。

---

## 6. 資料庫與系統狀態查詢

透過 `inspect` 指令族來觀測系統運作狀態：

- `inspect status`：顯示各 Table 中最舊、最新時間與資料總筆數。
  - **範例**：`./.venv/bin/python -m sentinel inspect status`
- `inspect completeness`：比對交易日曆與 `stocks` 主表，找出特定日期缺少資料的股票清單與涵蓋率。
  - **範例**：`./.venv/bin/python -m sentinel inspect completeness --date 2024-03-21`
- `inspect logs`：顯示 Pipeline 執行歷史，包含成功與失敗次數、花費時間等 (`jobs` / `quarantine`)。
  - **範例**：`./.venv/bin/python -m sentinel inspect logs --type jobs --limit 20`
- `inspect results`：調閱過去特定日期的選股明細，支援 `--direction`，欄位同 `scan_results`。
  - **範例**：`./.venv/bin/python -m sentinel inspect results --date 2024-03-21 --direction long`

---

## 7. 「明日之星」日內當沖模組 (Intraday)

這是一套專門追蹤日內大戶動態且高度自動化的選股及模擬交易模組，專司「13:00 爆量買入，隔日早盤開高獲利了結」的隔日沖策略。

### `scheduler`
- **指令範例**：`./.venv/bin/python -m sentinel scheduler`
- **功能**：啟動常駐背景服務，自動打理盤中所有排程任務。
- **執行邏輯**：透過 `APScheduler` 註冊排程，遇到假日自動跳過：
  - `09:00`：執行 `update-intraday-trades --real-time` 自動平倉昨日留倉。
  - `09:00 ~ 13:35`：每 5 分鐘執行 `capture-intraday-snapshot` 截取市場即時量能。
  - `13:00`：即刻打 API 取得快照，執行 `run-intraday` 進行爆發標的篩選並推送 Telegram 通知。

### `update-intraday-stats`
- **指令範例**：`./.venv/bin/python -m sentinel update-intraday-stats --lookback-days 180`
- **功能**：回溯統計各股「強勢收盤後隔日跳空開高」的歷史勝率。
- **執行邏輯**：比對近半年的日線資料，找出漲幅 $\ge$ 5% 的日子，統計其下個交易日「開盤價 > 昨收」的機率，並要求至少發生過 5 次以上。寫入 `intraday_indicators` 作為盤中決策參考機率。
- **輸出欄位 (Intraday Indicator)**：`symbol`, `indicator` (`overnight_win_rate`), `value`, `samples`。

### `capture-intraday-snapshot`
- **指令範例**：`./.venv/bin/python -m sentinel capture-intraday-snapshot --time 12:00`
- **功能**：透過 MIS 證交所 API 抓取全市場所有個股的當下「瞬時成交量」與「最後成交價」。
- **輸出欄位 (Intraday Snapshot)**：`snapshot_time` (快照時間), `symbol`, `current_price`, `accumulated_volume` (累積量)。

### `run-intraday`
- **指令範例**：`./.venv/bin/python -m sentinel run-intraday --top 300 --min-gain 0.075`
- **功能**：每日 13:00 啟動，使用即時/快照資料做高勝率過濾。
- **過濾邏輯** (須同時滿足)：
  1. 股價 $\le$ 1000 元。
  2. 現價漲幅 $\ge$ 7.5% 且「現價 > 開盤價」 (收紅 K)。
  3. 今日累積量 $\ge$ 1.5倍 的五日均量 (MA5 Volume)。
  4. 午盤爆發比 $\ge$ 1.0 = `(12:00~13:00 的增量) / (09:00~12:00 的早盤量)`。
  5. 漲停委託吃單 (Optional)：判斷 13:00 時點的最後成交量是否高於委買單量的 30%。
- **輸出**：過濾結果顯示於終端機，可配合 `--notify-telegram` 推送通知給使用者。

### `add-intraday-trade`
- **指令範例**：`./.venv/bin/python -m sentinel add-intraday-trade --symbol 2330 --price 600`
- **功能**：手動選取 `run-intraday` 的結果加入模擬交易日誌（預定隔日結算）。
- **輸入**：`--symbol`, `--price` 等。市場 (TWSE/TPEX) 系統會利用 `stocks` 表自動判斷補齊。

### `update-intraday-trades`
- **指令範例**：`./.venv/bin/python -m sentinel update-intraday-trades --real-time --price-type last`
- **功能**：將尚未結算 (status=`open`) 的部位進行出場結算並計算獲利。
- **邏輯與輸入**：
  - `--price-type open | last`: 指定結算使用「今日開盤價」還是「當下最新成交價」。例如 09:00 自動排程固定使用 `open`，若盤中手動執行則建議 `--price-type last`。
  - `--real-time`: 代表向外打 API 抓即時報價，若省略則去撈 DB 資料。

### `inspect intraday-trades`
- **指令範例**：`./.venv/bin/python -m sentinel inspect intraday-trades`
- **功能**：瀏覽當沖模擬交易簿之結果。
- **輸出欄位**：`id`, `entry_date`, `symbol`, `entry_price`, `exit_date`, `exit_price`, `return_pct` (報酬率), `status` (狀態：open/win/loss)。
