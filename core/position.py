"""
仓位管理模块：止盈止损、价格追踪
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..infra.config import get_config
from ..infra.logger import log, notify
from ..infra.util import get_time_ms

if TYPE_CHECKING:
    from ..models import AccountState

# 时间常量（毫秒）
MS_1D = 24 * 60 * 60 * 1000


def _ms_to_days(ms: int | float) -> float:
    """毫秒 → 天"""
    return ms / 1000 / 60 / 60 / 24


def cut_profit(symbol: str, sym_data: dict, state: AccountState,
               order_fn) -> bool:
    """
    动态止盈逻辑：
    - 多仓：持仓超时止损 / 布林上轨下弯 / 阶梯回撤止盈
    - 空仓：跌 5% 止盈 / 持仓超 1 天平仓
    :param order_fn: order 函数引用（避免循环导入）
    :return: True 表示已平仓
    """
    cfg = get_config()
    data = sym_data["15m"]["data"]
    price = float(data[-1][4])
    price_avg = float(state.position[symbol]["openPriceAvg"])
    price_high = float(state.price_track[symbol]["priceHigh"])
    c_time = int(state.position[symbol]["cTime"])
    hold_ms = int(data[-1][0]) - c_time

    if state.position[symbol]["holdSide"] == "long":
        # 持仓超 N 天还亏损
        timeout_loss = cfg.get("long_timeout_loss_days", 2)
        if price < price_avg and hold_ms > MS_1D * timeout_loss:
            order_fn(symbol, data, "SELL", state, only_close=True)
            notify(f"持仓超过{timeout_loss}天，还是亏损的，平仓")
            return True

        # 持仓超 N 天盈利不足
        timeout_profit = cfg.get("long_timeout_profit_days", 3)
        min_profit_pct = cfg.get("long_min_profit_pct", 0.06)
        if price < price_avg * (1 + min_profit_pct) and hold_ms > MS_1D * timeout_profit:
            order_fn(symbol, data, "SELL", state, only_close=True)
            notify(f"持仓超过{timeout_profit}天，盈利不足{min_profit_pct*100:.0f}个点，平仓")
            return True

        # 布林上轨下弯
        upper = sym_data["1D"]["bolling"]["Upper Band"]
        if upper[-1] < upper[-2]:
            order_fn(symbol, data, "SELL", state, only_close=True)
            notify("布林线上轨下弯，平仓")
            return True

        # 阶梯回撤止盈
        tiers = cfg.get("trailing_stop_tiers", [
            [1.50, 0.50], [1.40, 0.20], [1.30, 0.15],
            [1.25, 0.13], [1.20, 0.10], [1.13, 0.08], [1.06, 0.06],
        ])
        for gain_mult, pullback in tiers:
            if price_high <= price_avg * gain_mult:
                continue
            if gain_mult == 1.50:
                trigger = (price_avg + price_high) / 2
                if trigger > price:
                    pct = (price_high - price_avg) * 100 / price_avg
                    order_fn(symbol, data, "SELL", state, only_close=True)
                    notify(f"止盈单，涨{pct:.2f}%，回落一半")
                    return True
            else:
                if price_high > price * (1 + pullback):
                    order_fn(symbol, data, "SELL", state, only_close=True)
                    notify(
                        f"止盈单，涨{(gain_mult - 1) * 100:.0f}%，"
                        f"回落{pullback * 100:.0f}%"
                    )
                    return True
            break  # 只匹配最高档位

    elif state.position[symbol]["holdSide"] == "short":
        short_tp = cfg.get("short_take_profit_pct", 0.05)
        if price_avg > price * (1 + short_tp):
            order_fn(symbol, data, "BUY", state, only_close=True)
            notify(f"止盈单，跌{short_tp*100:.0f}%")
            return True

        short_timeout = cfg.get("short_timeout_days", 1)
        if hold_ms > MS_1D * short_timeout:
            order_fn(symbol, data, "BUY", state, only_close=True)
            notify(f"持仓超过{short_timeout}天，平仓")
            return True

    return False


def track_price(all_sym: dict, is_first_scan: bool, state: AccountState) -> None:
    """追踪持仓期间的最高价和最低价，用于止盈判断"""
    # 清理已平仓的记录
    for sym in list(state.price_track.keys()):
        if sym not in all_sym:
            del state.price_track[sym]

    for sym in all_sym:
        if is_first_scan:
            c_time = int(state.position[sym]["cTime"])
            for i in range(1, len(all_sym[sym]["15m"]["data"])):
                bar = all_sym[sym]["15m"]["data"][-i]
                if int(bar[0]) > c_time:
                    high, low = float(bar[2]), float(bar[3])
                    if sym in state.price_track:
                        state.price_track[sym]["priceHigh"] = max(
                            high, state.price_track[sym]["priceHigh"])
                        state.price_track[sym]["priceLow"] = min(
                            low, state.price_track[sym]["priceLow"])
                    else:
                        state.price_track[sym] = {
                            "priceHigh": high,
                            "priceLow": low,
                            "priceStart": float(all_sym[sym]["15m"]["data"][-1 - i][3]),
                        }
                    break

        bar_1m = all_sym[sym]["1m"]["data"][-1]
        high_1m, low_1m = float(bar_1m[2]), float(bar_1m[3])
        if sym in state.price_track:
            state.price_track[sym]["priceHigh"] = max(
                high_1m, state.price_track[sym]["priceHigh"])
            state.price_track[sym]["priceLow"] = min(
                low_1m, state.price_track[sym]["priceLow"])
        else:
            state.price_track[sym] = {
                "priceHigh": high_1m,
                "priceLow": low_1m,
                "priceStart": float(all_sym[sym]["15m"]["data"][-2][3]),
            }

        open_price = float(state.position[sym]["openPriceAvg"])
        if state.position[sym]["holdSide"] == "long":
            state.price_track[sym]["rate"] = (
                state.price_track[sym]["priceHigh"] - open_price
            ) / open_price
        else:
            state.price_track[sym]["rate"] = (
                open_price - state.price_track[sym]["priceLow"]
            ) / state.price_track[sym]["priceLow"]
