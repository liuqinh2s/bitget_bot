"""
=============================================================================
Bitget 合约自动化交易机器人（实盘）— 主编排模块

职责：
    - 初始化 AccountState
    - 编排市场扫描 → 选币 → 下单 → 仓位监控的完整流程
    - 各子模块：strategy / scanner / order / position / data_fetcher
=============================================================================
"""
from __future__ import annotations

import asyncio
import time
from time import sleep

from ..api.bitget_api import (
    PRODUCT_TYPE, getAllPosition, getAccounts, openCount, getFillHistory,
)
from ..infra.config import get_config
from .data_fetcher import get_all_data, compute_indicators
from ..infra.logger import log, notify
from ..models import AccountState
from .order import order
from .position import cut_profit, track_price
from .scanner import (
    detect_volume_anomaly, select_by_fund_rate, select_by_volume,
    select_by_volume_surge, find_fairy_guide, find_leading_coins,
)
from .strategy import (
    is_15m_trend_up, is_1h_trend_up, is_4h_trend_up, is_1d_trend_up,
    is_btc_trend_up, is_btc_trend_down,
)
from ..infra.util import get_time_ms

# 时间常量（毫秒）
MS_15M = 15 * 60 * 1000
MS_1D = 24 * 60 * 60 * 1000


# =============================================================================
#  数据校验与过滤
# =============================================================================

def _is_too_new(sym: dict) -> bool:
    """币种数据是否太少（K 线不足 20 根）"""
    try:
        for tf in ("4H", "1H", "15m"):
            if tf not in sym or len(sym[tf].get("data") or []) < 20:
                return True
        return False
    except (KeyError, TypeError) as e:
        log.warning("_is_too_new 异常: %s", e)
        return True


def _is_rubbish(sym: dict) -> bool:
    """连续三天振幅小于 10% 的低波动币"""
    for i in range(-3, 0):
        if float(sym["1D"]["data"][i][2]) > float(sym["1D"]["data"][i][3]) * 1.1:
            return False
    return True


def _has_no_data(sym: dict) -> bool:
    """是否存在空数据的周期"""
    return any(len(sym[tf]["data"]) <= 0 for tf in ("1D", "4H", "1H", "15m"))


def _is_data_fresh(sym: dict, key: str, old_data_symbols: dict) -> bool:
    """检查各周期数据是否足够新"""
    try:
        now = int(get_time_ms())
        freshness = {"15m": MS_15M, "1H": 60 * 60 * 1000, "4H": 4 * 60 * 60 * 1000, "1D": MS_1D}
        for tf, max_age in freshness.items():
            if now - int(sym[tf]["data"][-1][0]) > max_age:
                old_data_symbols[tf].append(key)
                return False
        return True
    except (KeyError, IndexError, ValueError) as e:
        log.warning("_is_data_fresh 异常 %s: %s", key, e)
        return False


def _is_shutdown(state: AccountState) -> bool:
    """是否应该进入关停模式（回撤 > 10% 或 24 小时内爆仓超 2 次）"""
    cfg = get_config()
    if state.max_drawdown > cfg.get("max_drawdown_threshold", 0.1):
        return True
    try:
        fill_history = getFillHistory(PRODUCT_TYPE, int(get_time_ms()) - MS_1D)
        burst_count = 0
        fill_list = fill_history.get("data", {}).get("fillList")
        if fill_list:
            burst_count = sum(
                1 for x in fill_list
                if x["tradeSide"] in ("burst_close_long", "burst_close_short")
            )
        return burst_count > cfg.get("max_burst_count", 2)
    except (KeyError, TypeError) as e:
        log.warning("_is_shutdown 检查异常: %s", e)
        return False


def _min_price_7d(sym: dict) -> float:
    """近 7 日最低价"""
    days = min(7, len(sym["1D"]["data"]))
    return min(float(sym["1D"]["data"][-i][3]) for i in range(1, days + 1))


# =============================================================================
#  选币下单
# =============================================================================

def _select_and_order(all_sym: dict, state: AccountState) -> None:
    """根据 buy_list / sell_list 执行下单"""
    cfg = get_config()
    for direction, side_list, order_type in [
        ("buy", state.buy_list, "BUY"),
        ("sell", state.sell_list, "SELL"),
    ]:
        if not side_list:
            continue

        acc = getAccounts(PRODUCT_TYPE)
        state.update_balance(float(acc["data"][0]["accountEquity"]))

        for key in side_list:
            cur_price = all_sym[key]["15m"]["data"][-1][4]
            res = openCount(
                key, PRODUCT_TYPE, "USDT",
                str(state.position_balance), cur_price,
                str(cfg.get("leverage", 10)),
            )
            notify(f"币种：{key} 可开数量：{res['data']['size']}")

            min_size = state.position_balance * 0.1 / float(cur_price)
            if float(res["data"]["size"]) / 2 < min_size:
                notify("可开数量不足")
                continue

            cut = None if order_type == "BUY" else {
                "buy": {"profit": 0, "loss": 0},
                "sell": {"profit": 0.05, "loss": 0},
            }

            all_position = getAllPosition(PRODUCT_TYPE)
            max_long = cfg.get("max_long_positions", 3)
            max_short = cfg.get("max_short_positions", 1)
            max_positions = max_long if order_type == "BUY" else max_short
            if len(all_position["data"]) < max_positions:
                order(key, all_sym[key]["15m"]["data"], order_type, state, False, cut)

    notify(
        f"bitget 可以开多的币：{state.buy_list} "
        f"可以开空的币：{state.sell_list}"
    )


# =============================================================================
#  市场扫描
# =============================================================================

def scan_market(state: AccountState, is_four_hour: bool = False) -> dict:
    """
    扫描全市场，筛选符合策略条件的币种
    核心策略：成交量异动 + 多周期趋势共振
    """
    cfg = get_config()
    state.buy_list = {}
    state.sell_list = {}
    all_sym: dict = {}

    start_time = int(get_time_ms())
    asyncio.run(get_all_data(["1D", "4H", "1H", "15m"], all_sym, state=state))
    elapsed = (int(get_time_ms()) - start_time) / 1000
    notify(f"bitget 抓一遍所有币的数据，耗费时间：{elapsed}s")

    compute_indicators(all_sym)

    all_keys: list[str] = []
    valid_symbols: list[str] = []
    new_symbols: list[str] = []
    no_data_symbols: list[str] = []
    old_data_symbols: dict = {"15m": [], "1H": [], "4H": [], "1D": []}
    volume_anomaly: dict = {"15m": [], "1H": [], "4H": []}

    max_7d = cfg.get("max_7d_gain_mult", 2.7)
    max_boll = cfg.get("max_boll_width_mult", 2.7)
    max_upper = cfg.get("max_close_above_upper_mult", 1.1)

    for key in all_sym:
        all_keys.append(key)
        sym = all_sym[key]

        if _is_too_new(sym):
            new_symbols.append(key)
            continue
        if _has_no_data(sym):
            log.debug("存在空数据的币：%s", key)
            no_data_symbols.append(key)
            continue
        if not _is_data_fresh(sym, key, old_data_symbols):
            continue
        if key == "BTCUSDT":
            continue

        valid_symbols.append(key)

        # ---- 策略：成交量异动 + 多周期趋势向上 ----
        anomaly_tf = detect_volume_anomaly(all_sym, key, "buy", volume_anomaly)
        trend_all_up = (
            is_15m_trend_up(sym, "15m")
            and is_1h_trend_up(sym, "1H")
            and is_4h_trend_up(sym, "4H")
            and is_1d_trend_up(sym)
        )
        # 防追高
        close_price = float(sym["1D"]["data"][-1][4])
        not_overextended = (
            close_price < _min_price_7d(sym) * max_7d
            and sym["1D"]["bolling"]["Upper Band"][-1]
            < sym["1D"]["bolling"]["Lower Band"][-1] * max_boll
        )
        not_above_upper = close_price < sym["1D"]["bolling"]["Upper Band"][-1] * max_upper
        btc_ok = is_btc_trend_up(all_sym)

        if (trend_all_up and not_overextended and not_above_upper
                and btc_ok and not _is_rubbish(sym)):
            if anomaly_tf in ("15m", "1H", "4H"):
                state.buy_list[key] = f"{anomaly_tf}成交量异动 + 所有周期趋势向上"

    log.info(
        "扫描完成，全部交易对：%d 可分析：%d 新币:%s 空数据:%s 数据旧:%s",
        len(all_keys), len(valid_symbols), new_symbols, no_data_symbols, old_data_symbols,
    )
    notify(f"bitget 扫描完成，全部交易对：{len(all_keys)}")
    notify(
        f"bitget 可分析：{len(valid_symbols)} 数据旧:{old_data_symbols} "
        f"空数据:{no_data_symbols} 新币:{new_symbols}"
    )
    return all_sym


# =============================================================================
#  仓位扫描与主循环
# =============================================================================

def _scan_position(all_position: dict, state: AccountState) -> None:
    """扫描当前持仓，获取数据并执行止盈逻辑"""
    key_list = []
    state.position = {}
    for x in all_position["data"]:
        state.position[x["symbol"]] = x
        key_list.append(x["symbol"])

    if not key_list:
        return

    all_sym: dict = {}
    is_first = state.is_first_scan_position
    limit = "300" if is_first else "41"
    asyncio.run(get_all_data(["1D", "15m", "1m"], all_sym, key_list, limit, state))
    if is_first:
        state.is_first_scan_position = False

    track_price(all_sym, is_first, state)
    compute_indicators(all_sym)

    for key in all_sym:
        cut_profit(key, all_sym[key], state, order)


def _full_scan_and_order(state: AccountState, is_four_hour: bool = False) -> dict:
    """执行完整的市场扫描 + 下单 + 辅助分析"""
    all_sym = scan_market(state, is_four_hour)
    _select_and_order(all_sym, state)
    select_by_volume(all_sym, state)
    select_by_volume_surge(all_sym, state)
    select_by_fund_rate(state)
    find_fairy_guide(all_sym, state)
    find_leading_coins(all_sym)
    return all_sym


def _loop_scan_position(all_position: dict, state: AccountState) -> None:
    """持仓期间的循环监控"""
    _scan_position(all_position, state)
    while True:
        _wait_until_next(1)
        all_position = getAllPosition(PRODUCT_TYPE)
        if not all_position["data"]:
            break
        _scan_position(all_position, state)

        now = int(time.time())
        if now % (4 * 3600) <= 60:
            _full_scan_and_order(state, is_four_hour=True)
        elif now % (15 * 60) <= 60:
            _full_scan_and_order(state)


def strategy(state: AccountState) -> None:
    """单次策略执行：更新余额 → 检查持仓 → 扫描市场 → 下单"""
    acc = getAccounts(PRODUCT_TYPE)
    state.update_balance(float(acc["data"][0]["accountEquity"]))

    all_position = getAllPosition(PRODUCT_TYPE)
    if all_position["data"]:
        _loop_scan_position(all_position, state)
    else:
        _full_scan_and_order(state)
        all_position = getAllPosition(PRODUCT_TYPE)
        if all_position["data"]:
            _loop_scan_position(all_position, state)

    # 更新持仓 / 空仓时间
    if not all_position["data"]:
        state.no_position_time += MS_15M
    elif state.position_type == "BUY":
        state.long_position_time += MS_15M
    elif state.position_type == "SELL":
        state.short_position_time += MS_15M


def _wait_until_next(minutes: int) -> None:
    """等待到下一个整分钟"""
    interval = minutes * 60
    now = int(time.time())
    remainder = now % interval
    if remainder != 0:
        sleep(interval - remainder)


def main() -> None:
    """主入口：每 15 分钟执行一次策略"""
    cfg = get_config()
    interval = cfg.get("scan_interval_minutes", 15) * 60
    state = AccountState()

    log.info("Bitget 交易机器人启动")
    while True:
        try:
            strategy(state)
            now = int(time.time())
            remainder = now % interval
            if remainder != 0:
                sleep(interval - remainder + 1)
        except Exception as e:
            log.error("主循环异常: %s", e, exc_info=True)
            notify(str(e))
