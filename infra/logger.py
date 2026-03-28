"""
日志框架：统一使用 logging 模块，Telegram 作为 handler 推送重要信息
"""
from __future__ import annotations

import logging

from .send_msg import send_telegram


class TelegramHandler(logging.Handler):
    """将 WARNING 及以上级别的日志推送到 Telegram"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            send_telegram(msg)
        except Exception:
            self.handleError(record)


def setup_logger(name: str = "bitget_bot", level: int = logging.DEBUG) -> logging.Logger:
    """创建并配置 logger"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 控制台 handler — DEBUG 及以上
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(console)

    # Telegram handler — WARNING 及以上
    tg = TelegramHandler()
    tg.setLevel(logging.WARNING)
    tg.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(tg)

    return logger


# 全局 logger 实例
log = setup_logger()


def notify(msg: str) -> None:
    """主动推送到 Telegram（不受日志级别限制），同时记录 INFO"""
    send_telegram(msg)
    log.info(msg)
