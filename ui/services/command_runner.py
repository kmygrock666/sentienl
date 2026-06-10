"""任務執行器：負責背景執行 CLI 指令、追蹤狀態、保存日誌。"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

from ui.services.command_specs import CommandSpec, build_argv

# 任務狀態存放路徑（相對於專案根目錄）
_TASKS_FILE = Path(__file__).parent.parent.parent / "data" / "ui_tasks.json"
_LOG_TAIL_LINES = 100
_MAX_TASKS = 200


class TaskRun:
    """單次任務執行記錄。"""

    def __init__(
        self,
        task_id: str,
        command_id: str,
        argv: list[str],
        status: str = "pending",
        pid: Optional[int] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        exit_code: Optional[int] = None,
        stdout_path: Optional[str] = None,
        stderr_path: Optional[str] = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
        error_message: str = "",
    ) -> None:
        self.task_id = task_id
        self.command_id = command_id
        self.argv = argv
        self.status = status
        self.pid = pid
        self.started_at = started_at
        self.ended_at = ended_at
        self.exit_code = exit_code
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail
        self.error_message = error_message

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "command_id": self.command_id,
            "argv": self.argv,
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskRun":
        return cls(**d)

    @property
    def argv_preview(self) -> str:
        import shlex

        return " ".join(shlex.quote(a) for a in self.argv)

    @property
    def duration_str(self) -> str:
        if not self.started_at:
            return "—"
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.ended_at) if self.ended_at else datetime.utcnow()
            secs = (end - start).total_seconds()
            if secs < 60:
                return f"{secs:.0f}s"
            return f"{secs / 60:.1f}m"
        except Exception:
            return "—"


class TaskStore:
    """JSON 檔案後端的任務儲存庫。"""

    def __init__(self, path: Path = _TASKS_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_all(self, data: dict[str, dict]) -> None:
        # _MAX_TASKS 是軟上限：overflow 中的 running 任務會被保留，總數可能暫時超過
        if len(data) > _MAX_TASKS:
            ordered = sorted(data.values(), key=lambda d: d.get("started_at") or "", reverse=True)
            kept = ordered[:_MAX_TASKS]
            running_overflow = [d for d in ordered[_MAX_TASKS:] if d.get("status") == "running"]
            data = {d["task_id"]: d for d in kept + running_overflow}
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self, task: TaskRun) -> None:
        data = self._load_all()
        data[task.task_id] = task.to_dict()
        self._save_all(data)

    def get(self, task_id: str) -> Optional[TaskRun]:
        data = self._load_all()
        d = data.get(task_id)
        return TaskRun.from_dict(d) if d else None

    def list_all(self) -> list[TaskRun]:
        data = self._load_all()
        tasks = [TaskRun.from_dict(d) for d in data.values()]
        tasks.sort(key=lambda t: t.started_at or "", reverse=True)
        return tasks

    def list_by_status(self, status: str) -> list[TaskRun]:
        return [t for t in self.list_all() if t.status == status]


_store = TaskStore()


def get_store() -> TaskStore:
    return _store


def find_running_task(command_id: str) -> "Optional[TaskRun]":
    """Return a running task with the same command_id, or None."""
    for t in _store.list_by_status("running"):
        if t.command_id == command_id:
            return t
    return None


def _read_tail(path: Optional[str], n: int = _LOG_TAIL_LINES) -> str:
    """讀取檔案最後 n 行。"""
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return ""


def _proc_key(task_id: str) -> str:
    return f"_proc_{task_id}"


def launch_task(spec: CommandSpec, params: dict) -> TaskRun:
    """
    啟動任務（背景執行）。

    - 短任務（is_long_task=False）：同步等待完成，最長 30 秒。
    - 長任務（is_long_task=True）：非同步，立即返回 pending TaskRun。
    """
    argv = build_argv(spec, params)
    task_id = str(uuid.uuid4())[:8]

    stdout_f = tempfile.NamedTemporaryFile(
        delete=False, suffix=".stdout", mode="w", encoding="utf-8"
    )
    stderr_f = tempfile.NamedTemporaryFile(
        delete=False, suffix=".stderr", mode="w", encoding="utf-8"
    )

    task = TaskRun(
        task_id=task_id,
        command_id=spec.command_id,
        argv=argv,
        status="running",
        started_at=datetime.utcnow().isoformat(),
        stdout_path=stdout_f.name,
        stderr_path=stderr_f.name,
    )
    _store.save(task)

    cwd = str(Path(__file__).parent.parent.parent)
    proc = subprocess.Popen(
        argv,
        stdout=stdout_f,
        stderr=stderr_f,
        cwd=cwd,
        env={**os.environ},
    )
    stdout_f.close()
    stderr_f.close()

    task.pid = proc.pid
    _store.save(task)

    if not spec.is_long_task:
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        _finalize_task(task, proc)
    else:
        # 存入 session_state 供後續 poll 使用
        if "hasattr" not in dir(st):
            pass
        try:
            st.session_state[_proc_key(task_id)] = proc
        except Exception:
            pass

    return task


def poll_task(task_id: str) -> TaskRun:
    """查詢任務狀態，若已結束則更新記錄。"""
    task = _store.get(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.status != "running":
        return task

    proc: Optional[subprocess.Popen] = None
    try:
        proc = st.session_state.get(_proc_key(task_id))
    except Exception:
        pass

    if proc is not None:
        rc = proc.poll()
        if rc is not None:
            _finalize_task(task, proc)
    else:
        # session 重啟後無 Popen 物件，改用 PID 偵測
        if task.pid:
            try:
                os.kill(task.pid, 0)
                # 仍在執行中
            except (OSError, ProcessLookupError):
                # 已結束但無法取得 exit code
                task.status = "failed"
                task.ended_at = datetime.utcnow().isoformat()
                task.stdout_tail = _read_tail(task.stdout_path)
                task.stderr_tail = _read_tail(task.stderr_path)
                task.error_message = "（程序已結束，但無法取得 exit code，可能是 session 重啟導致）"
                _store.save(task)

    return _store.get(task_id) or task


def _finalize_task(task: TaskRun, proc: subprocess.Popen) -> None:
    """任務結束後更新狀態、讀取輸出。"""
    rc = proc.returncode if proc.returncode is not None else proc.wait()
    task.exit_code = rc
    task.status = "success" if rc == 0 else "failed"
    task.ended_at = datetime.utcnow().isoformat()
    task.stdout_tail = _read_tail(task.stdout_path)
    task.stderr_tail = _read_tail(task.stderr_path)
    if rc != 0:
        task.error_message = task.stderr_tail[-500:] if task.stderr_tail else "Exit code non-zero"
    _store.save(task)


def stop_task(task_id: str) -> TaskRun:
    """終止執行中的任務：先 SIGTERM，最多等 2 秒，仍存活則 SIGKILL。"""
    task = _store.get(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    if task.status != "running" or not task.pid:
        return task

    try:
        os.kill(task.pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            os.kill(task.pid, 0)  # 仍存活則繼續等；已結束會拋例外跳出
        os.kill(task.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass  # 行程已結束

    task.status = "stopped"
    task.ended_at = datetime.utcnow().isoformat()
    task.stdout_tail = _read_tail(task.stdout_path)
    task.stderr_tail = _read_tail(task.stderr_path)
    _store.save(task)
    return task


def poll_all_running() -> list[TaskRun]:
    """輪詢所有 running 狀態的任務，返回更新後的列表。"""
    running = _store.list_by_status("running")
    updated = []
    for task in running:
        updated.append(poll_task(task.task_id))
    return updated


def rerun_task(task: TaskRun) -> TaskRun:
    """以相同 argv 重新啟動一個已完成/失敗的任務。"""
    task_id = str(uuid.uuid4())[:8]

    stdout_f = tempfile.NamedTemporaryFile(
        delete=False, suffix=".stdout", mode="w", encoding="utf-8"
    )
    stderr_f = tempfile.NamedTemporaryFile(
        delete=False, suffix=".stderr", mode="w", encoding="utf-8"
    )

    new_task = TaskRun(
        task_id=task_id,
        command_id=task.command_id,
        argv=task.argv,
        status="running",
        started_at=datetime.utcnow().isoformat(),
        stdout_path=stdout_f.name,
        stderr_path=stderr_f.name,
    )
    _store.save(new_task)

    cwd = str(Path(__file__).parent.parent.parent)
    proc = subprocess.Popen(
        task.argv,
        stdout=stdout_f,
        stderr=stderr_f,
        cwd=cwd,
        env={**os.environ},
    )
    stdout_f.close()
    stderr_f.close()

    new_task.pid = proc.pid
    _store.save(new_task)

    # 判斷是否為短任務（看原始 command_id）
    from ui.services.command_specs import ALL_SPECS

    spec = ALL_SPECS.get(task.command_id)
    if spec and not spec.is_long_task:
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        _finalize_task(new_task, proc)
    else:
        try:
            st.session_state[_proc_key(task_id)] = proc
        except Exception:
            pass

    return new_task
