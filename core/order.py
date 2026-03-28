"""
下单模块：开仓、平仓、统一下单入口
"""
from __future__ import annotations

from time import sleep
from typing import TYPE_CHECKING

from ..api.factory import get_exchange
from ..infra.config import get_config
from ..infra.logger import log, notify
from ..infra.util import get_human_time
from .copy_trading import close_track_by_symbol, sync_tpsl_to_track

if TYPE_CHECKING:
    from ..models import AccountState


def _wait_for_filled(symbol: str, order_info: dict) -> dict:
    """市价单等待完全成交，每 5 秒轮询一次"""
    ex = get_exchange()
    sleep(5)
    for _ in range(60):  # 最多等 5 分钟
        detail = ex.get_order_detail(symbol, ex.PRODUCT_TYPE, order_info["data"]["orderId"])
        if detail["data"]["state"] == "filled":
            return detail
        sleep(5)
    raise TimeoutError(f"{symbol} 订单未在 5 分钟内成交")


def _ms_to_days(ms: int | float) -> float:
    return ms / 1000 / 60 / 60 / 24


def close_position(symbol: str, side: str, state: AccountState) -> float:
    """
    平仓通用逻辑
    :param side: 'long' 平多 / 'short' 平空
    :return: 本次盈亏
    """
    cfg = get_config()
    ex = get_exchange()

    # 带单模式：先通过带单 API 平仓，确保跟单者同步
    if cfg.get("copy_trading_enabled", False):
        close_track_by_symbol(symbol)
    available = state.position[symbol]["available"]
    order_side = "buy" if side == "long" else "sell"
    label = "平多" if side == "long" else "平空"
    log.info("下单量：%su  %s", available, label)

    order_info = ex.live_order(
        symbol, ex.PRODUCT_TYPE, "isolated", "USDT",
        order_side, available, "market", "close",
    )
    notify(f"orderInfo: {order_info}")
    detail = _wait_for_filled(symbol, order_info)
    notify(f"orderDetail: {detail}")

    profit = float(detail["data"]["totalProfits"])
    notify(
        f"时间: {get_human_time(detail['data']['cTime'])} {symbol} {label}, "
        f"价格: {detail['data']['priceAvg']} "
        f"持仓量:{detail['data']['baseVolume']} "
        f"手续费:{detail['data']['fee']} 盈亏: {profit}"
    )

    state.update_drawdown(profit)
    state.position_type = ""

    notify(f"当前最大回撤：{state.max_drawdown}")
    notify(f"资产最高峰：{state.largest_balance}")
    notify(f"账户总额：{state.balance}")

    # 更新持仓时间统计
    label_cn = "做多" if side == "long" else "做空"
    duration = state.reset_position_time(side)
    notify(f"{label_cn}天数：{_ms_to_days(duration)}")
    total_key = "all_long_position_time" if side == "long" else "all_short_position_time"
    notify(f"总{label_cn}天数: {_ms_to_days(getattr(state, total_key))}")

    state.position_balance = state.balance
    return profit


def open_position(symbol: str, price: float, cut: dict, side: str,
                  state: AccountState) -> None:
    """
    开仓通用逻辑
    :param side: 'long' 做多 / 'short' 做空
    """
    ex = get_exchange()
    cfg = get_config()
    hold_side = "long" if side == "long" else "short"
    leverage_info = ex.set_leverage(
        symbol, ex.PRODUCT_TYPE, "USDT", None,
        cfg.get("leverage", 10), None, hold_side,
    )
    notify(f"调整杠杆：{leverage_info}")

    min_usdt = cfg.get("min_usdt", 10)
    position_balance = min_usdt if state.is_shutdown else state.position_balance
    order_side = "buy" if side == "long" else "sell"
    cut_key = "buy" if side == "long" else "sell"
    label = "开多" if side == "long" else "开空"
    log.info("下单量：%su  %s", position_balance, label)

    # 预设止损
    preset_stop_loss = ""
    if cut[cut_key]["loss"] > 0:
        contracts = ex.get_contracts(symbol, ex.PRODUCT_TYPE)
        price_place = contracts["data"][0]["pricePlace"]
        if side == "long":
            sl_price = price * (1 - cut[cut_key]["loss"])
        else:
            sl_price = price * (1 + cut[cut_key]["loss"])
        preset_stop_loss = f"{sl_price:.{price_place}f}"
        notify(f"挂单亏{cut[cut_key]['loss'] * 100}%平仓")

    order_info = ex.live_order(
        symbol, ex.PRODUCT_TYPE, "isolated", "USDT",
        order_side, position_balance / price, "market", "open",
        "", preset_stop_loss,
    )
    notify(f"orderInfo: {order_info}")
    detail = _wait_for_filled(symbol, order_info)
    notify(f"orderDetail: {detail}")

    filled_price = float(detail["data"]["priceAvg"])
    base_volume = detail["data"]["baseVolume"]

    # 预设止盈
    if cut[cut_key]["profit"] > 0:
        contracts = ex.get_contracts(symbol, ex.PRODUCT_TYPE)
        price_place = contracts["data"][0]["pricePlace"]
        if side == "long":
            tp_price = filled_price * (1 + cut[cut_key]["profit"])
        else:
            tp_price = filled_price * (1 - cut[cut_key]["profit"])
        tp_info = ex.live_order(
            symbol, ex.PRODUCT_TYPE, "isolated", "USDT",
            order_side, base_volume, "limit", "close",
            f"{tp_price:.{price_place}f}",
        )
        notify(f"挂单赚{cut[cut_key]['profit'] * 100}%平仓 orderInfo: {tp_info}")

    state.position_type = "BUY" if side == "long" else "SELL"
    state.position_symbol = symbol

    # 带单模式：同步止盈止损到带单订单
    if cfg.get("copy_trading_enabled", False):
        tp_str = ""
        sl_str = ""
        if cut[cut_key]["profit"] > 0:
            contracts = ex.get_contracts(symbol, ex.PRODUCT_TYPE)
            pp = contracts["data"][0]["pricePlace"]
            if side == "long":
                tp_str = f"{filled_price * (1 + cut[cut_key]['profit']):.{pp}f}"
            else:
                tp_str = f"{filled_price * (1 - cut[cut_key]['profit']):.{pp}f}"
        if cut[cut_key]["loss"] > 0 and preset_stop_loss:
            sl_str = preset_stop_loss
        sync_tpsl_to_track(symbol, tp_str, sl_str)

    duration = state.reset_no_position_time()
    notify(f"空仓天数：{_ms_to_days(duration)}")
    notify(f"总空仓天数: {_ms_to_days(state.all_no_position_time)}")

    notify(
        f"时间: {get_human_time(detail['data']['cTime'])} {symbol} {label}, "
        f"价格: {filled_price} 开仓量:{detail['data']['quoteVolume']}u "
        f"持仓量:{base_volume} 手续费:{detail['data']['fee']}"
    )


def order(symbol: str, data: list, order_type: str,
          state: AccountState, only_close: bool = False,
          cut: dict | None = None) -> None:
    """
    统一下单入口

    :param symbol:     交易对
    :param data:       K 线数据列表
    :param order_type: 'BUY'（做多）或 'SELL'（做空）
    :param state:      账户状态
    :param only_close: True 时只平仓不开新仓
    :param cut:        止盈止损配置
    """
    if cut is None:
        cut = {"buy": {"profit": 0, "loss": 0}, "sell": {"profit": 0, "loss": 0}}

    price = float(data[-1][4])
    profit = 0.0

    try:
        if order_type == "BUY":
            pos = state.position.get(symbol)
            if pos and pos["holdSide"] == "long":
                return  # 已持有多仓
            if pos and pos["holdSide"] == "short":
                profit = close_position(symbol, "long", state)
            if not only_close:
                open_position(symbol, price, cut, "long", state)
        else:
            pos = state.position.get(symbol)
            if pos and pos["holdSide"] == "short":
                return  # 已持有空仓
            if pos and pos["holdSide"] == "long":
                profit = close_position(symbol, "long", state)
            if not only_close:
                open_position(symbol, price, cut, "short", state)

        state.record_profit(profit, order_type)
    except TimeoutError as e:
        log.error("order 超时: %s %s - %s", symbol, order_type, e)
        notify(f"下单超时: {symbol} {order_type} - {e}")
    except KeyError as e:
        log.error("order 数据缺失: %s %s - %s", symbol, order_type, e)
    except (ConnectionError, OSError) as e:
        log.error("order 网络异常: %s %s - %s", symbol, order_type, e)
        notify(f"下单网络异常: {symbol} {order_type} - {e}")
    except Exception as e:
        log.error("order 未知异常: %s %s - %s", symbol, order_type, e)
