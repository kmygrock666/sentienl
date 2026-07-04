import inspect

import pytest

from sentinel.config import Settings
from sentinel.intraday.notifiers import TelegramNotifier
from sentinel.intraday.scheduler import IntradayScheduler


@pytest.mark.unit
def test_notifier_disabled_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 Telegram 憑證時不得 fallback 到任何內建 token，通知功能應停用。"""
    monkeypatch.setattr(
        "sentinel.intraday.scheduler.Settings",
        lambda: Settings(_env_file=None, tg_token=None, tg_chat_id=None),
    )
    scheduler = IntradayScheduler("sqlite://")
    assert scheduler.notifier is None


@pytest.mark.unit
def test_notifier_enabled_with_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sentinel.intraday.scheduler.Settings",
        lambda: Settings(_env_file=None, tg_token="test-token", tg_chat_id="123"),
    )
    scheduler = IntradayScheduler("sqlite://")
    assert isinstance(scheduler.notifier, TelegramNotifier)


@pytest.mark.unit
def test_no_hardcoded_token_in_source() -> None:
    """確保洩漏過的 token 片段不再出現在原始碼。"""
    from pathlib import Path

    import sentinel.cli
    import sentinel.intraday.scheduler
    import sentinel.services

    sources = {
        "sentinel.intraday.scheduler": inspect.getsource(sentinel.intraday.scheduler),
    }
    for package in (sentinel.cli, sentinel.services):
        package_dir = Path(package.__file__).parent
        for source_path in sorted(package_dir.glob("*.py")):
            sources[f"{package.__name__}/{source_path.name}"] = source_path.read_text(
                encoding="utf-8"
            )

    for name, source in sources.items():
        assert "5675544561" not in source, name
        assert "-5018674933" not in source, name
        assert "AAG7ANUJ" not in source, name
