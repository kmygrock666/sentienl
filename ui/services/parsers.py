"""CLI 輸出解析器（stdout/stderr → 結構化資料）。"""
from __future__ import annotations

import re
from typing import Any


def parse_sync_output(stdout: str, stderr: str) -> dict[str, Any]:
    """解析 sync / sync-calendar / sync-stocks 的輸出摘要。"""
    result: dict[str, Any] = {"lines": stdout.strip().splitlines(), "rows": None, "markets": []}
    # 嘗試從 JSON log 行中提取 rows / markets
    for line in stdout.splitlines() + stderr.splitlines():
        m = re.search(r'"rows"\s*:\s*(\d+)', line)
        if m:
            result["rows"] = int(m.group(1))
        m = re.search(r'"markets"\s*:\s*\[([^\]]+)\]', line)
        if m:
            result["markets"] = [s.strip().strip('"') for s in m.group(1).split(",")]
    return result


def parse_run_output(stdout: str, stderr: str) -> dict[str, Any]:
    """解析 run（Pipeline）的輸出摘要。"""
    result: dict[str, Any] = {"lines": stdout.strip().splitlines(), "hits": None, "trading_date": None}
    for line in stdout.splitlines() + stderr.splitlines():
        m = re.search(r'"total_hits"\s*:\s*(\d+)', line)
        if m:
            result["hits"] = int(m.group(1))
        m = re.search(r'"trading_date"\s*:\s*"([^"]+)"', line)
        if m:
            result["trading_date"] = m.group(1)
    return result


def parse_inspect_output(stdout: str, stderr: str) -> dict[str, Any]:
    """解析 inspect 指令輸出（文字表格）。"""
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    return {"lines": lines, "raw": stdout}


def parse_check_stock_output(stdout: str, stderr: str) -> dict[str, Any]:
    """解析 check-stock 輸出，分類觸發/未觸發訊號。"""
    triggered = []
    not_triggered = []
    warnings = []
    for line in stdout.splitlines():
        line_up = line.upper()
        # 先判斷「未觸發」以免 "TRIGGERED" 誤判 "NOT TRIGGERED"
        is_not = (
            "✗" in line
            or "NOT TRIGGERED" in line_up
            or "未觸發" in line
        )
        is_warn = "WARNING" in line_up or "警示" in line
        is_yes = (
            not is_not
            and ("✓" in line or "TRIGGERED" in line_up or "觸發" in line)
        )
        if is_not:
            not_triggered.append(line.strip())
        elif is_warn:
            warnings.append(line.strip())
        elif is_yes:
            triggered.append(line.strip())
    return {
        "triggered": triggered,
        "not_triggered": not_triggered,
        "warnings": warnings,
        "raw": stdout,
    }


def parse_generic_output(stdout: str, stderr: str) -> dict[str, Any]:
    """通用解析：回傳原始行列表。"""
    return {"lines": stdout.strip().splitlines(), "raw": stdout}


def parse_check_stock_output_v2(stdout: str, stderr: str) -> dict[str, Any]:
    """解析 check-stock CLI 輸出為結構化訊號列表（v2）。

    輸出格式:
    {
      "meta": {"symbol": str, "name": str, "date": str},
      "signals": [
        {
          "name": str,
          "direction": "long" | "warning" | "intraday",
          "status": "triggered" | "not_triggered" | "needs_intraday",
          "source_rule": str,
          "reason": str,            # for intraday only
          "conditions": [{"passed": bool, "text": str}, ...],
          "passed_count": int,
          "total_count": int,
        }
      ],
      "triggered_count": int,
      "warning_count": int,
      "not_triggered_count": int,
      "needs_intraday_count": int,
      "raw": str,
    }
    """
    lines = stdout.splitlines()

    # --- Extract meta ---
    meta: dict[str, str] = {"symbol": "", "name": "", "date": ""}
    for line in lines:
        m = re.search(r'個股訊號檢驗\s*[—\-]\s*(.+?)\s*（(\d{4}-\d{2}-\d{2})）', line)
        if m:
            name_sym = m.group(1).strip()
            meta["date"] = m.group(2)
            parts = name_sym.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].isdigit():
                meta["name"] = parts[0].strip()
                meta["symbol"] = parts[1].strip()
            else:
                meta["name"] = name_sym
            break

    # --- Parse sections ---
    signals: list[dict[str, Any]] = []
    current_section: str | None = None
    current_signal: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current_signal
        if current_signal:
            signals.append(current_signal)
            current_signal = None

    for line in lines:
        stripped = line.strip()

        # Section headers
        if "📈" in line and "做多進場" in line:
            flush(); current_section = "long"; continue
        if "⚠️" in line and "警示" in line:
            flush(); current_section = "warning"; continue
        if "⚙️" in line and "需盤中" in line:
            flush(); current_section = "intraday"; continue

        # Skip decorative lines and blanks
        if not stripped or re.match(r'^[─═╔╚╗╝║\s]+$', stripped):
            continue

        if current_section in ("long", "warning"):
            # Signal line starts with status emoji
            if stripped.startswith(("✅", "❌", "🔴")):
                flush()
                if stripped.startswith("✅"):
                    status, direction = "triggered", "long"
                elif stripped.startswith("🔴"):
                    status, direction = "triggered", "warning"
                else:
                    status = "not_triggered"
                    direction = current_section
                name = re.sub(r'^[✅❌🔴]\s*', '', stripped).strip()
                current_signal = {
                    "name": name, "direction": direction, "status": status,
                    "source_rule": "", "reason": "",
                    "conditions": [], "passed_count": 0, "total_count": 0,
                }
            elif current_signal and len(line) > 0 and (line[0] == " " or line[0] == "\t"):
                # Indented condition line
                passed = "✅" in line
                text = re.sub(r'^\s+✅?\s*', '', line).strip()
                if text:
                    current_signal["conditions"].append({"passed": passed, "text": text})
                    current_signal["total_count"] += 1
                    if passed:
                        current_signal["passed_count"] += 1

        elif current_section == "intraday" and "⚙️" in stripped:
            flush()
            m = re.match(r'⚙️\s+(.+?)\s+\[([^\]]*)\]\s+[—\-]\s*(.*)', stripped)
            if m:
                name, source_rule, reason = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            else:
                name = re.sub(r'^⚙️\s*', '', stripped).strip()
                source_rule = reason = ""
            current_signal = {
                "name": name, "direction": "intraday", "status": "needs_intraday",
                "source_rule": source_rule, "reason": reason,
                "conditions": [], "passed_count": 0, "total_count": 0,
            }

    flush()

    triggered_count = sum(1 for s in signals if s["status"] == "triggered" and s["direction"] == "long")
    warning_count = sum(1 for s in signals if s["status"] == "triggered" and s["direction"] == "warning")
    not_triggered_count = sum(1 for s in signals if s["status"] == "not_triggered")
    needs_intraday_count = sum(1 for s in signals if s["status"] == "needs_intraday")

    return {
        "meta": meta,
        "signals": signals,
        "triggered_count": triggered_count,
        "warning_count": warning_count,
        "not_triggered_count": not_triggered_count,
        "needs_intraday_count": needs_intraday_count,
        "raw": stdout,
    }
