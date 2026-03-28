"""
Telegram 消息推送模块
"""
from __future__ import annotations

import requests

from .env import TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS

_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def send_telegram(msg: str = "") -> None:
    """向所有配置的 Telegram 群组发送消息"""
    for chat_id in TELEGRAM_CHAT_IDS:
        if not chat_id:
            continue
        try:
            resp = requests.get(_URL, params={"text": msg, "chat_id": chat_id}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            # 避免循环依赖，这里只用 print
            print(f"send_telegram 异常 chat_id={chat_id}: {e}")
