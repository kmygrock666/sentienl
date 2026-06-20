# 每日盤後資料功能設計

**日期：** 2026-06-20
**狀態：** 已核准，待實作

---

## 背景與目標

現有 Data Sync 頁面包含所有資料同步指令（初始化、曆史補資料、每日盤後），使用頻率差異很大。每日盤後作業（股價、法人買賣超、主力分點）需要固定在收盤後執行，應有獨立的頁面讓操作更流暢，並搭配防呆機制避免重複撈取。

---

## 範圍

1. 新頁面 `ui/pages/12_Daily_Fetch.py`
2. 首頁快捷操作新增導航按鈕
3. `ui/services/queries.py` 新增兩個 freshness query

---

## 新頁面設計

### 頁面位置
`ui/pages/12_Daily_Fetch.py`
側欄顯示為「📥 每日盤後」

### Section 1：今日股價同步

- 指令：`SYNC`（TWSE + TPEX，`sync` 自動補到今日）
- 防呆邏輯：
  - 優先：呼叫 `get_data_freshness(engine)` 取各市場最新日期
  - 若 TWSE 與 TPEX 最新日期均等於今日 → 顯示 `✅ 已同步` badge，按鈕改灰色「重新同步」
  - DB 不可用時 fallback：查 task store 今日是否有 `command_id == "sync"` 且 `status == "success"` 的記錄
- 按鈕：`▶ 同步今日股價`

### Section 2：三大法人買賣超

- 指令：`SYNC_INSTITUTIONAL`，日期欄位預填今日
- 防呆邏輯：
  - 呼叫 `get_latest_institutional_date(engine)` 取 `InstitutionalFlow.trading_date` 最大值
  - 若等於今日 → 顯示 `✅ 已同步` badge，按鈕改灰色「重新同步」
  - Fallback：今日 task store 是否有 `sync-institutional` 成功記錄
- 按鈕：`▶ 同步今日法人資料`

### Section 3：主力分點同步

使用 `st.tabs(["批次（關注清單）", "單一臨時"])` 分兩個 tab。

#### Tab A：批次（關注清單）

- 讀取 `data/ui_watchlist.json`（`[{"symbol": "2330", "name": "台積電"}, ...]`）
- 若清單為空 → 提示「請先至個股訊號檢驗頁加入關注清單」並附 page_link
- 呼叫 `get_latest_main_force_dates(engine, symbols)` 取各個股最新日期
- 顯示清單表格（代號、名稱、最新主力資料日、是否已同步今日）
- 可透過 checkbox 排除特定個股
- 按鈕：`▶ 批次同步`
  - 對每支未排除的個股各 `launch_task(SYNC_MAIN_FORCE, {...})` 啟動背景任務
  - 日期預填今日（start-date = end-date = today）
  - 送出後顯示「已送出 N 個任務，請至 Task Center 追蹤」

#### Tab B：單一臨時

- 欄位：股票代號（必填）、開始日期、結束日期（預填今日）
- 無防呆（臨時操作，可重複執行）
- 按鈕：`▶ 同步`，短任務（`is_long_task=False`）等待結果後顯示

---

## 首頁快捷操作

`ui/app.py` 修改：

- 現有 4 欄（`qa1, qa2, qa3, qa4`）改為 5 欄
- 新增第 5 欄按鈕：`📥 每日盤後`
- 點擊後執行 `st.switch_page("pages/12_Daily_Fetch.py")`（純導航，不啟動任務）

---

## 新增 Query

`ui/services/queries.py` 新增：

```python
def get_latest_institutional_date(engine: Engine) -> date | None:
    """查詢 InstitutionalFlow 最新 trading_date。"""
    with Session(engine) as s:
        return s.query(func.max(InstitutionalFlow.trading_date)).scalar()

def get_latest_main_force_dates(engine: Engine, symbols: list[str]) -> dict[str, date | None]:
    """批次查詢各個股 MainForceDaily 最新 trading_date，回傳 {symbol: date}。"""
    with Session(engine) as s:
        rows = (
            s.query(MainForceDaily.symbol, func.max(MainForceDaily.trading_date))
            .filter(MainForceDaily.symbol.in_(symbols))
            .group_by(MainForceDaily.symbol)
            .all()
        )
    result = {sym: None for sym in symbols}
    for sym, d in rows:
        result[sym] = d
    return result
```

---

## 防呆機制總結

| 操作 | 防呆判斷來源 | 觸發條件 | UI 行為 |
|---|---|---|---|
| 股價同步 | `get_data_freshness()` | TWSE & TPEX 均為今日 | 按鈕灰色「重新同步」 |
| 法人買賣超 | `get_latest_institutional_date()` | 最新日期為今日 | 按鈕灰色「重新同步」 |
| 主力批次 | `get_latest_main_force_dates()` | 各股最新日期為今日 | 清單各列顯示 ✅，仍可勾選強制跑 |
| DB 不可用 | task store | 今日有對應成功記錄 | 同上（降級判斷） |

「重新同步」（灰色按鈕）仍可按，不彈 confirm dialog，直接執行。

---

## 不在範圍內

- Data Sync 頁面改動（INIT_DB 位置維持現狀）
- 排程自動觸發
- Telegram 通知整合
