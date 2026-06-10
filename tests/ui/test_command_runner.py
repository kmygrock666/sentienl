"""測試 TaskRun 資料結構與 TaskStore 的基本 CRUD。"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_store(tmp_path: Path):
    from ui.services.command_runner import TaskStore

    return TaskStore(path=tmp_path / "tasks.json")


def test_taskrun_to_from_dict() -> None:
    """TaskRun 序列化與反序列化應保持一致。"""
    from ui.services.command_runner import TaskRun

    t = TaskRun(
        task_id="abc123",
        command_id="run",
        argv=["python", "-m", "sentinel", "run"],
        status="success",
        started_at="2024-01-01T00:00:00",
        ended_at="2024-01-01T00:01:00",
        exit_code=0,
        stdout_tail="完成\n",
        stderr_tail="",
    )
    d = t.to_dict()
    t2 = TaskRun.from_dict(d)
    assert t2.task_id == t.task_id
    assert t2.command_id == t.command_id
    assert t2.status == t.status
    assert t2.exit_code == 0


def test_taskrun_argv_preview() -> None:
    """argv_preview 應產生可複製的 shell 字串。"""
    from ui.services.command_runner import TaskRun

    t = TaskRun(
        task_id="x",
        command_id="run",
        argv=["python", "-m", "sentinel", "--start-date", "2024-01-01"],
    )
    preview = t.argv_preview
    assert "python" in preview
    assert "sentinel" in preview
    assert "2024-01-01" in preview


def test_taskrun_duration_str_running(monkeypatch) -> None:
    """執行中任務的 duration_str 應回傳非空字串。"""
    from ui.services.command_runner import TaskRun

    t = TaskRun(
        task_id="y",
        command_id="sync",
        argv=[],
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    assert t.duration_str != "—"


def test_taskrun_duration_str_no_start() -> None:
    """無開始時間的任務 duration_str 應回傳 '—'。"""
    from ui.services.command_runner import TaskRun

    t = TaskRun(task_id="z", command_id="sync", argv=[])
    assert t.duration_str == "—"


def test_store_save_and_get(tmp_store) -> None:
    """TaskStore 能儲存並讀回任務。"""
    from ui.services.command_runner import TaskRun

    t = TaskRun(task_id="t1", command_id="init-db", argv=[], status="success")
    tmp_store.save(t)
    result = tmp_store.get("t1")
    assert result is not None
    assert result.command_id == "init-db"
    assert result.status == "success"


def test_store_list_all_sorted(tmp_store) -> None:
    """list_all 應按 started_at 倒序排列。"""
    from ui.services.command_runner import TaskRun

    t1 = TaskRun(task_id="a", command_id="run", argv=[], started_at="2024-01-01T01:00:00")
    t2 = TaskRun(task_id="b", command_id="sync", argv=[], started_at="2024-01-02T01:00:00")
    tmp_store.save(t1)
    tmp_store.save(t2)
    tasks = tmp_store.list_all()
    assert tasks[0].task_id == "b"
    assert tasks[1].task_id == "a"


def test_store_list_by_status(tmp_store) -> None:
    """list_by_status 應只回傳特定狀態的任務。"""
    from ui.services.command_runner import TaskRun

    t1 = TaskRun(task_id="ok1", command_id="run", argv=[], status="success")
    t2 = TaskRun(task_id="ok2", command_id="sync", argv=[], status="failed")
    tmp_store.save(t1)
    tmp_store.save(t2)
    success = tmp_store.list_by_status("success")
    assert len(success) == 1
    assert success[0].task_id == "ok1"


def test_store_missing_task_returns_none(tmp_store) -> None:
    """取不存在的任務應回傳 None。"""
    result = tmp_store.get("not_exist")
    assert result is None


def test_store_empty_file_returns_empty(tmp_store) -> None:
    """空存放區 list_all 應回傳空 list。"""
    assert tmp_store.list_all() == []
