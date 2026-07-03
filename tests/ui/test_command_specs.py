"""測試 CommandSpec 的 argv 組裝與驗證邏輯。"""

from __future__ import annotations

import sys


def test_build_argv_basic() -> None:
    """基本 argv 組裝：必填欄位正確附加。"""
    from ui.services.command_specs import RUN, build_argv

    params = {
        "start-date": "2024-01-01",
        "end-date": "2024-01-31",
    }
    argv = build_argv(RUN, params)
    assert "--start-date" in argv
    assert "2024-01-01" in argv
    assert "--end-date" in argv
    assert "2024-01-31" in argv


def test_build_argv_multiselect() -> None:
    """multiselect 欄位應重複附加 --flag value 多次。"""
    from ui.services.command_specs import RUN, build_argv

    params = {
        "start-date": "2024-01-01",
        "end-date": "2024-01-31",
        "market": ["TWSE", "TPEX"],
    }
    argv = build_argv(RUN, params)
    market_flags = [argv[i + 1] for i, a in enumerate(argv) if a == "--market"]
    assert "TWSE" in market_flags
    assert "TPEX" in market_flags


def test_build_argv_checkbox_true() -> None:
    """checkbox 欄位為 True 時應只附加旗標（無值）。"""
    from ui.services.command_specs import RUN, build_argv

    params = {
        "start-date": "2024-01-01",
        "end-date": "2024-01-31",
        "skip-indicators": True,
    }
    argv = build_argv(RUN, params)
    assert "--skip-indicators" in argv
    idx = argv.index("--skip-indicators")
    assert idx == len(argv) - 1 or argv[idx + 1].startswith("--")


def test_build_argv_checkbox_false() -> None:
    """checkbox 欄位為 False 時不應附加旗標。"""
    from ui.services.command_specs import RUN, build_argv

    params = {
        "start-date": "2024-01-01",
        "end-date": "2024-01-31",
        "skip-indicators": False,
    }
    argv = build_argv(RUN, params)
    assert "--skip-indicators" not in argv


def test_build_argv_empty_optional() -> None:
    """空字串選填欄位不應附加至 argv。"""
    from ui.services.command_specs import SYNC, build_argv

    params = {"direction": ""}
    argv = build_argv(SYNC, params)
    assert "--direction" not in argv


def test_argv_to_preview_quoting() -> None:
    """argv_to_preview 應正確處理含空格的路徑。"""
    from ui.services.command_specs import argv_to_preview

    argv = ["python", "-m", "sentinel", "--strategy-path", "/path/with space/strategies.json"]
    preview = argv_to_preview(argv)
    assert (
        "'/path/with space/strategies.json'" in preview
        or '"/path/with space/strategies.json"' in preview
    )


def test_validate_date_range_valid() -> None:
    """日期區間合法時，validator 應回傳 None。"""
    from ui.services.command_specs import RUN

    err = RUN.validator({"start-date": "2024-01-01", "end-date": "2024-01-31"})
    assert err is None


def test_validate_date_range_invalid() -> None:
    """開始日期晚於結束日期時，validator 應回傳錯誤訊息。"""
    from ui.services.command_specs import RUN

    err = RUN.validator({"start-date": "2024-02-01", "end-date": "2024-01-01"})
    assert err is not None
    assert len(err) > 0


def test_all_specs_have_command_id() -> None:
    """所有規格都應有非空的 command_id。"""
    from ui.services.command_specs import ALL_SPECS

    for cid, spec in ALL_SPECS.items():
        assert spec.command_id == cid, f"{cid} 的 command_id 不一致"
        assert spec.description, f"{cid} 缺少 description"
        assert spec.argv_base, f"{cid} 缺少 argv_base"


def test_inspect_status_argv_contains_subcommand() -> None:
    """inspect status 的 argv 應包含 'inspect' 與 'status'。"""
    from ui.services.command_specs import INSPECT_STATUS, build_argv

    argv = build_argv(INSPECT_STATUS, {})
    assert "inspect" in argv
    assert "status" in argv


def test_sync_institutional_argv() -> None:
    """sync-institutional 應正確組裝 argv（含日期、多市場、來源模式）。"""
    from ui.services.command_specs import ALL_SPECS, SYNC_INSTITUTIONAL, build_argv

    assert ALL_SPECS["sync-institutional"] is SYNC_INSTITUTIONAL
    required = {f.name for f in SYNC_INSTITUTIONAL.fields if f.required}
    assert required == {"date"}

    params = {
        "date": "2026-06-10",
        "market": ["TWSE", "TPEX"],
        "source-mode": "auto",
    }
    argv = build_argv(SYNC_INSTITUTIONAL, params)
    assert argv[:4] == [sys.executable, "-m", "sentinel", "sync-institutional"]
    assert "--date" in argv
    assert "2026-06-10" in argv
    market_values = [argv[i + 1] for i, a in enumerate(argv) if a == "--market"]
    assert market_values == ["TWSE", "TPEX"]
    assert "--source-mode" in argv
    assert "--database-url" not in argv


def test_sync_calendar_requires_date_fields() -> None:
    """sync-calendar 應有 start-date 與 end-date 兩個 required 欄位。"""
    from ui.services.command_specs import SYNC_CALENDAR

    required = {f.name for f in SYNC_CALENDAR.fields if f.required}
    assert "start-date" in required
    assert "end-date" in required
