"""
Notification channels.

TelegramNotifier pushes messages to your phone via the Telegram Bot API.
ConsoleNotifier just prints (used for --dry-run and tests). Both share the same
send(text) interface so app.py doesn't care which is active.
"""

from __future__ import annotations

import requests

APPROACHING = "approaching"
MET = "met"

_STATUS_EMOJI = {APPROACHING: "⏳", MET: "\U0001f6a8"}  # ⏳ / 🚨


def format_signal(sig) -> str:
    """Human-readable one-liner for a Signal."""
    emoji = _STATUS_EMOJI.get(sig.status, "\U0001f4c8")
    tag = "ABOUT TO MEET" if sig.status == APPROACHING else "MET"
    return f"{emoji} [{tag}] {sig.message}"


class ConsoleNotifier:
    channel = "console"

    def send(self, text: str) -> bool:
        print(text)
        return True


class TelegramNotifier:
    """
    Sends messages through a Telegram bot.

    Setup (one time):
      1. Message @BotFather on Telegram, /newbot, copy the bot token.
      2. Start a chat with your new bot and send it any message.
      3. Get your chat id: open
         https://api.telegram.org/bot<TOKEN>/getUpdates and read
         result[].message.chat.id  (or message @userinfobot).
      4. Export TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
    """

    channel = "telegram"
    API = "https://api.telegram.org"

    def __init__(self, token: str, chat_id: str, timeout: int = 10):
        if not token or not chat_id:
            raise ValueError(
                "Telegram requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                "(set them in the environment or config)."
            )
        self.token = token
        self.chat_id = str(chat_id)
        self.timeout = timeout

    def send(self, text: str) -> bool:
        url = f"{self.API}/bot{self.token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            print(f"[error] Telegram request failed: {exc}")
            return False
        if resp.status_code != 200:
            print(f"[error] Telegram API {resp.status_code}: {resp.text[:200]}")
            return False
        return True


def build_notifier(channel: str, settings: dict):
    """Factory used by app.py based on config/CLI."""
    if channel == "console":
        return ConsoleNotifier()
    if channel == "telegram":
        return TelegramNotifier(settings.get("telegram_bot_token", ""), settings.get("telegram_chat_id", ""))
    raise ValueError(f"Unknown notification channel: {channel!r}")
