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
    import sentinel.cli
    import sentinel.intraday.scheduler

    for mod in (sentinel.intraday.scheduler, sentinel.cli):
        source = inspect.getsource(mod)
        assert "5675544561" not in source, mod.__name__
        assert "-5018674933" not in source, mod.__name__
        assert "AAG7ANUJ" not in source, mod.__name__
