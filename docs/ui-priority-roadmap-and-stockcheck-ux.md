# Sentinel UI 優化路線圖 + Stock Check 改版規格（給 Claude Code）

> 日期：2026-05-10

---

## A. 優先級路線圖（P0 / P1 / P2）

## P0（立即改善，直接影響日常操作）
1. `Run（今日）` 改為 `Run（最新收盤日）`，並修正執行邏輯。  
2. 快捷任務完成後自動導流結果頁（run/sync/run-intraday）。  
3. 首頁「策略命中摘要」補足語境（掃描日、總命中、CTA）。  
4. Stock Check 結果改為「可解釋訊號卡」，不再只顯示原始文字片段。

## P1（高價值優化）
1. 任務去重防呆：同參數任務執行中時阻止重複送出。  
2. 任務與結果綁定：Task Center 每筆任務可 `Open Result`。  
3. 參數模板（Preset）：run/backtest/intraday 常用組合一鍵套用。  
4. 失敗訊息可行動化：DB 未啟動、日期無資料等給「下一步按鈕」。

## P2（體驗精修）
1. 行動版表格卡片化（先摘要，展開看明細）。  
2. URL query 參數化（可分享同一篩選視圖）。  
3. 首頁與結果區加 `last updated at`。  
4. 策略摘要增加近 5~10 交易日趨勢。

---

## B. Stock Check 問題診斷（現況）

目前 `ui/pages/4_Stock_Check.py` + `parse_check_stock_output()` 的問題：
1. 以關鍵字切行分類（`觸發/未觸發/警示`），缺乏規則 ID 與訊號名稱的結構。  
2. 同一訊號的條件細節可能分散在多行，無法聚合顯示。  
3. 「未觸發」只看到結果，看不到是哪些條件沒過。  
4. 「需盤中資料」與「待實作」沒有被獨立呈現。  
5. 使用者不知道下一步是什麼（例如調整日期、改看完整輸出、回測交叉驗證）。

---

## C. Stock Check 改版目標

把「文字輸出閱讀」升級成「規則判讀面板」：
1. 一眼知道：哪個訊號觸發、為何觸發/未觸發。  
2. 針對未觸發訊號，能看到失敗條件。  
3. 盤中資料需求訊號獨立列出，避免誤解成 bug。  
4. 可以快速採取下一步（看 K 線、看同日掃描、重跑指定日期）。

---

## D. Stock Check 新介面規格（請直接實作）

## D.1 結果頁分區
1. `摘要列`：
   - 股票代號/名稱
   - 檢驗日期
   - 觸發數 / 未觸發數 / 警示數 / 需盤中資料數
2. `做多進場訊號`（卡片列表）
3. `警示/出場訊號`（卡片列表）
4. `未觸發訊號`（可展開）
5. `需盤中資料 / 待實作`（獨立區）
6. `完整原始輸出`（debug 用，預設收合）

## D.2 訊號卡片內容（每張）
每張卡片固定欄位：
- `signal_id`
- `name`
- `direction`（long / warning / observation / position_mgmt）
- `status`（triggered / not_triggered / needs_intraday / not_supported）
- `source_rule`（例如規則 2/6）
- `conditions_summary`：
  - 通過條件數 / 總條件數
  - 失敗條件前 1~3 條（可展開全看）
- `values_snapshot`：條件計算實值（例如 `今日低點 104 >= 昨日低點 103.8`）

## D.3 視覺語意
- `triggered`：綠色（通過）
- `warning`：黃橘（警示）
- `not_triggered`：灰色（未達）
- `needs_intraday`：藍灰（需外部資料）

## D.4 互動行為
1. 篩選器：`全部 / 只看觸發 / 只看警示 / 只看未觸發 / 只看需盤中`。  
2. 排序：預設 `觸發 > 警示 > 未觸發 > 需盤中`。  
3. 快捷操作：
   - `帶入此日期到 Daily Scan`
   - `查看該股近期 K 線`
   - `複製本次檢驗參數`

---

## E. 資料與解析層調整

## E.1 解析策略升級
目前 parser 只做關鍵字切行；請改為「區塊解析 + 訊號聚合」。

建議新增：
- `ui/services/parsers.py::parse_check_stock_output_v2(stdout, stderr)`

輸出格式至少包含：
```json
{
  "meta": {
    "symbol": "2492",
    "name": "華新科",
    "date": "2025-10-21"
  },
  "signals": [
    {
      "signal_id": "shooting_star_reversal_buy",
      "name": "倒T線反轉做多",
      "direction": "long",
      "status": "triggered",
      "source_rule": "規則 2/6",
      "passed_count": 5,
      "total_count": 5,
      "failed_conditions": [],
      "condition_lines": ["..."],
      "needs_intraday": false
    }
  ],
  "raw": "..."
}
```

## E.2 若 CLI 輸出無法穩定解析
請在 UI 層做降級策略：
1. 先顯示目前可解析欄位。  
2. 無法解析者歸入「未結構化輸出」區塊。  
3. 不可因解析失敗導致頁面空白。

---

## F. 驗收標準（Stock Check）

1. 新使用者可在 15 秒內回答：
   - 哪些訊號觸發？
   - 哪些是警示？
   - 哪些需要盤中資料所以無法判斷？
2. 任一未觸發訊號可看到「至少一條失敗條件」。
3. 完整原始輸出仍可查看（除錯不退化）。
4. 行動版可正常閱讀訊號卡（不橫向爆版）。

---

## G. 請 Claude 的實作順序

1. 先完成 P0 的前三項（run 最新收盤日、導流、策略摘要語境）。
2. 接著完成 Stock Check 改版（本文件 D/E/F）。
3. 最後補 P1 的任務去重與 Open Result。

---

## H. 回報格式

請 Claude 完成後回覆：
1. 變更檔案列表。  
2. P0/P1 已完成項目勾選。  
3. Stock Check 前後對照截圖或描述（至少 3 個情境）。  
4. 已知限制與下一步建議。
