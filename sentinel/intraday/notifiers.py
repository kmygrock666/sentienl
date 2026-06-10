from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from sentinel.config import Settings

logger = logging.getLogger(__name__)


def build_telegram_notifier(settings: Settings) -> Optional[TelegramNotifier]:
    """Build a notifier from settings; return None (with a warning) when credentials are missing."""
    if settings.tg_token and settings.tg_chat_id:
        return TelegramNotifier(settings.tg_token, settings.tg_chat_id)
    logger.warning(
        "Telegram credentials not configured (TS_TG_TOKEN / TS_TG_CHAT_ID); "
        "notifications disabled."
    )
    return None


class TelegramNotifier:
    """
    Notifier for Telegram Bot API.
    """
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send_message(self, text: str) -> bool:
        """Send a text message to the Telegram chat."""
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(self.api_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_scan_results(self, results: List[Dict[str, Any]]):
        """Format and send the Tomorrow's Star scan results."""
        if not results:
            return
            
        header = "<b>🌟 明日之星 - 13:00 策略掃描結果</b>\n"
        header += f"日期：{results[0].get('trading_date', '今日')}\n"
        header += "====================\n"
        
        lines = []
        for r in results:
            line = (
                f"<b>{r['symbol']} {r['name']}</b>\n"
                f"現價：{r['close']} ({r['gain']:.2%})\n"
                f"量能比：{r['vol_surge_ratio']:.2f}x | 勝率：{r['win_rate']:.0%}\n"
                f"{'🚩 漲停' if r['is_limit_up'] else ''} {'✅ 大戶單' if r['is_great_power'] else ''}\n"
            )
            lines.append(line)
            
        footer = "\n<i>(123 法則參考：8.5% 買 1 / 9% 買 2 / 10% 買 3)</i>"
        
        # Telegram has a limit of 4096 chars per message
        full_text = header + "\n".join(lines) + footer
        self.send_message(full_text)
