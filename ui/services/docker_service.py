"""Docker Compose 服務管理（DB 容器啟停與狀態查詢）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def get_db_container_status() -> str:
    """查詢 docker compose db 容器狀態。

    Returns:
        'running'           — 容器正在運行
        'stopped'           — 容器存在但已停止
        'docker_unavailable' — Docker 不可用或 compose 檔案不存在
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "db"],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=10,
        )
        if result.returncode != 0:
            return "docker_unavailable"
        output = result.stdout.lower()
        if "up" in output or "running" in output:
            return "running"
        return "stopped"
    except FileNotFoundError:
        return "docker_unavailable"
    except subprocess.TimeoutExpired:
        return "docker_unavailable"


def start_db_container() -> tuple[bool, str]:
    """啟動 docker compose db 容器。

    Returns:
        (True, 訊息)  — 啟動成功
        (False, 訊息) — 啟動失敗
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "db"],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=120,
        )
        if result.returncode == 0:
            return True, "DB 容器已啟動，請稍候數秒讓資料庫準備就緒"
        stderr = result.stderr.strip() or result.stdout.strip()
        return False, stderr or "啟動失敗，請查看 Docker 日誌"
    except FileNotFoundError:
        return False, "找不到 docker 指令，請確認 Docker Desktop 已安裝並啟動"
    except subprocess.TimeoutExpired:
        return False, "啟動逾時（超過 120 秒），請手動執行：docker compose up -d db"
