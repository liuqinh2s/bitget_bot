"""
环境配置：代理设置与敏感信息

注意：所有敏感信息（API Key、Secret、Telegram Token 等）
     应通过环境变量注入，切勿硬编码在代码中。
"""
import os

# ---- 代理配置 ----
NEED_PROXY: bool = os.getenv("BITGET_NEED_PROXY", "false").lower() == "true"

_PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
_PROXY_PORT = os.getenv("PROXY_PORT", "7890")

PROXIES = {
    "http": f"http://{_PROXY_HOST}:{_PROXY_PORT}",
    "https": f"http://{_PROXY_HOST}:{_PROXY_PORT}",
}

# ---- Bitget API 配置 ----
API_KEY: str = os.getenv("BITGET_API_KEY", "")
API_SECRET: str = os.getenv("BITGET_API_SECRET", "")
API_PASSPHRASE: str = os.getenv("BITGET_API_PASSPHRASE", "")

# ---- Telegram 配置 ----
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS: list[str] = os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
