"""
交易所抽象接口：定义所有交易所必须实现的方法签名

所有交易所适配器（Bitget、Binance 等）都必须继承此基类。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExchangeAPI(ABC):
    """交易所统一接口"""

    # 子类必须设置
    HOST: str = ""
    PRODUCT_TYPE: str = ""

    # ---- 账户 ----

    @abstractmethod
    def get_accounts(self, product_type: str) -> dict:
        """获取账户信息，返回格式: {"data": [{"accountEquity": "..."}]}"""

    @abstractmethod
    def set_leverage(self, symbol: str, product_type: str, margin_coin: str,
                     leverage=None, long_leverage=None, short_leverage=None,
                     hold_side=None) -> dict:
        """调整合约杠杆倍数"""

    @abstractmethod
    def open_count(self, symbol: str, product_type: str, margin_coin: str,
                   open_amount: str, open_price: str, leverage: str) -> dict:
        """查询可开数量，返回格式: {"data": {"size": "..."}}"""

    # ---- 订单 ----

    @abstractmethod
    def live_order(self, symbol: str, product_type: str, margin_mode: str,
                   margin_coin: str, side: str, size, order_type: str,
                   trade_side: str, price: str = "",
                   preset_stop_loss: str = "") -> dict:
        """下单（市价/限价），返回格式: {"data": {"orderId": "..."}}"""

    @abstractmethod
    def get_order_detail(self, symbol: str, product_type: str,
                         order_id: str) -> dict:
        """获取订单详情"""

    @abstractmethod
    def get_orders_pending(self, product_type: str) -> dict:
        """获取挂单列表"""

    # ---- 持仓 ----

    @abstractmethod
    def get_all_position(self, product_type: str) -> dict:
        """获取所有持仓，返回格式: {"data": [...]}"""

    @abstractmethod
    def get_history_position(self, product_type: str,
                             start_time: str) -> dict:
        """获取历史仓位"""

    @abstractmethod
    def get_fill_history(self, product_type: str, start_time) -> dict:
        """获取成交历史"""

    # ---- 行情 ----

    @abstractmethod
    def get_all_symbol(self, product_type: str) -> dict:
        """获取所有交易对，返回格式: {"data": [{"symbol": "..."}]}"""

    @abstractmethod
    def get_klines_url(self, symbol: str, product_type: str,
                       granularity: str, limit: str = "100",
                       end_time: str = "") -> str:
        """构造 K 线请求 URL"""

    @abstractmethod
    def get_history_fund_rate(self, symbol: str, product_type: str,
                              page_size: str = "20") -> dict:
        """获取历史资金费率"""

    @abstractmethod
    def get_contracts(self, symbol: str, product_type: str) -> dict:
        """获取合约信息（价格精度等）"""
