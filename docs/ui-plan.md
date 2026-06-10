# Sentinel Web UI 規劃存檔

> 建立日期：2026-05-06  
> 狀態：Phase 1 已完成

## 背景

Sentinel 原為純 CLI 系統（30+ 子指令，`argparse` 驅動）。使用者必須記憶指令旗標、手動讀 CSV/SQLite 驗證結果。決定新增本機 Streamlit 儀表板以簡化日常操作。

## 決策記錄

| 問題 | 決策 | 理由 |
|---|---|---|
| UI 框架 | Streamlit | 單 Python 檔可跑、與 SQLAlchemy/pandas 原生相容、不需前後端兩套 |
| API 層 | 無（直接讀 DB） | 本機單人使用，無需 REST；長期轉雲端再抽 FastAPI |
| 圖表庫 | Plotly | `st.plotly_chart` 互動 K 線；`go.Candlestick` 內建 |
| 長任務 | subprocess + JobRun 輪詢 | 避免 Streamlit thread 阻塞 UI |
| 部署情境 | localhost 單人 | 無需 auth、HTTPS |

## 架構設計

```
ui/
├── app.py                      # 首頁 Overview（掃描摘要、JobRun、資料新鮮度）
├── pages/
│   ├── 1_📊_Scan_Results.py   # 選股結果篩選表格 + CSV 匯出
│   ├── 2_📈_Stock_Detail.py   # K 線 + 技術指標疊加 + 命中史
│   ├── 3_⚙️_Strategies.py    # 策略啟停編輯（Phase 2）
│   ├── 4_🧪_Backtest.py       # 回測表單 + 報表（Phase 2）
│   ├── 5_⏱_Intraday.py        # 盤中監控（Phase 3）
│   └── 6_🩺_System_Health.py  # DB 連線 / 磁碟 / 隔離資料
├── components/
│   ├── charts.py               # candlestick_chart（Plotly）
│   ├── filters.py              # 市場/策略/日期選擇器
│   └── tables.py               # ScanResult / JobRun 表格
└── services/
    ├── db.py                   # @st.cache_resource engine（重用 sentinel.db）
    └── queries.py              # 所有 SELECT，回傳 pd.DataFrame
```

## 分階段交付

### Phase 1（已完成）
- `app.py` Overview：掃描命中摘要、策略命中圖、資料新鮮度、JobRun
- `pages/1` 選股結果：篩選 + 表格 + signals 明細 + CSV 匯出
- `pages/2` 個股 K 線 + MA/BB/RSI 疊加 + 命中史
- `pages/6` 系統健康：DB 連線、磁碟、隔離資料、Job 歷史

### Phase 2（待開發）
- `pages/3` 策略管理：`strategies.json` 啟停 + `st.data_editor` 條件編輯 + dry-run 預覽
- `pages/4` 回測：表單啟動 + `subprocess` + PnL 圖 / 回撤 / 勝率

### Phase 3（待開發）
- `pages/5` 盤中監控：`IntradaySnapshot` autorefresh + `IntradayTrade` 部位表
- 匯出 TradingView watchlist txt
- `st.autorefresh` 每 30 秒刷新盤中頁

## 關鍵實作約定

- DB session 以 `@st.cache_resource` 共用，避免每次 rerun 重連
- 所有 query 函式回傳 `pd.DataFrame`（空資料回 `pd.DataFrame()`，不 raise）
- 超過 5 秒的任務（backtest / sync）走 `subprocess.Popen` + JobRun 輪詢
- 寫回 `strategies.json` 前先備份 `.bak` + jsonschema 驗證，失敗則 rollback
- 不修改現有 CLI；UI 純讀 + 觸發既有指令

## 依賴

```toml
[project.optional-dependencies]
ui = [
    "streamlit>=1.32",
    "plotly>=5.18",
    "jsonschema>=4.21",
]
```

安裝：`python3 -m pip install -e ".[ui]"`  
（注意：若 `.venv/bin/pip` shebang 壞掉，改用 `.venv/bin/python3 -m pip install`）
