"""
市场扫描模块：成交量异动检测、辅助选币分析
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from infra.logger import notify

if TYPE_CHECKING:
    from models import AccountState


# =============================================================================
#  成交量异动检测
# =============================================================================

def _is_15m_step_up(all_sym: dict, symbol: str, j: int) -> bool:
    """15 分钟布林中轨是否阶梯式上行"""
    mid = all_sym[symbol]["15m"]["bolling"]["Middle Band"]
    for i in range(-2, 0):
        diff_cur = mid[i + j] - mid[i - 1 + j]
        diff_prev = mid[i - 1 + j] - mid[i - 2 + j]
        if diff_cur < diff_prev * 0.9999:
            return False
        if diff_prev * 0.9999 < 0:
            return False
    return True


def _is_15m_anomaly(all_sym: dict, symbol: str, j: int, direction: str) -> bool:
    """15 分钟成交量异动检测"""
    sym = all_sym[symbol]
    data = sym["15m"]["data"]

    if direction == "buy":
        upper = sym["15m"]["bolling"]["Upper Band"][-3 + j]
        lower = sym["15m"]["bolling"]["Lower Band"][-3 + j]
        if upper > lower * 1.1 and not _is_15m_step_up(all_sym, symbol, j):
            return False
        upper_1h = sym["1H"]["bolling"]["Upper Band"][-3 + j]
        lower_1h = sym["1H"]["bolling"]["Lower Band"][-3 + j]
        if upper_1h > lower_1h * 1.22:
            return False

    vol_sum_9 = sum(float(data[i + j][6]) for i in range(-11, -2))
    vol_sum_19 = vol_sum_9 + sum(float(data[i + j][6]) for i in range(-21, -11))

    bar_vol = float(data[-2 + j][6])
    bar_close = float(data[-2 + j][4])
    bar_open = float(data[-2 + j][1])

    vol_short = bar_vol >= vol_sum_9 and bar_vol >= 100_000
    vol_long = bar_vol >= vol_sum_19 and bar_vol >= 40_000

    if direction == "buy":
        price_ok = bar_open * 0.992 < bar_close < bar_open * 1.23
    else:
        price_ok = bar_open * 0.945 < bar_close < bar_open * 1.008

    return (vol_short or vol_long) and price_ok


def _is_1h_anomaly(all_sym: dict, symbol: str, j: int, direction: str) -> bool:
    """1 小时成交量异动检测"""
    data = all_sym[symbol]["1H"]["data"]
    bar_vol = float(data[-1 + j][6])
    if bar_vol < 400_000:
        return False
    vol_sum = sum(float(data[i + j][6]) for i in range(-6, -1))
    if bar_vol < vol_sum:
        return False

    bar_close = float(data[-1 + j][4])
    bar_open = float(data[-1 + j][1])
    if direction == "buy":
        return bar_open * 1.02 < bar_close < bar_open * 1.5
    return bar_open * 0.93 < bar_close < bar_open * 0.98


def _is_4h_anomaly(all_sym: dict, symbol: str, j: int, direction: str) -> bool:
    """4 小时成交量异动检测"""
    data = all_sym[symbol]["4H"]["data"]
    bar_vol = float(data[-1 + j][6])
    if bar_vol < 800_000:
        return False
    vol_sum = sum(float(data[i + j][6]) for i in range(-5, -1))
    if bar_vol < vol_sum:
        return False

    bar_close = float(data[-1 + j][4])
    bar_open = float(data[-1 + j][1])
    if direction == "buy":
        return bar_open * 1.05 < bar_close < bar_open * 2
    return bar_open * 0.91 < bar_close < bar_open * 0.96


def _has_recent_anomaly_of(check_fn, all_sym, symbol, direction, lookback):
    """检查最近 lookback 根 K 线内是否已出现过异动"""
    return any(check_fn(all_sym, symbol, i, direction) for i in range(-lookback, 0))


def _has_any_recent_anomaly(all_sym: dict, symbol: str, direction: str) -> bool:
    """近期是否已出现过任意周期的异动"""
    return (
        _has_recent_anomaly_of(_is_15m_anomaly, all_sym, symbol, direction, 7)
        or _has_recent_anomaly_of(_is_1h_anomaly, all_sym, symbol, direction, 7)
        or _has_recent_anomaly_of(_is_4h_anomaly, all_sym, symbol, direction, 5)
    )


def detect_volume_anomaly(all_sym: dict, symbol: str, direction: str,
                          anomaly_dict: dict) -> str:
    """
    检测当前 K 线是否有成交量异动
    :return: 异动周期 ('15m' / '1H' / '') 并记录到 anomaly_dict
    """
    if _has_any_recent_anomaly(all_sym, symbol, direction):
        return ""
    if _is_15m_anomaly(all_sym, symbol, 0, direction):
        anomaly_dict["15m"].append(symbol)
        return "15m"
    if _is_1h_anomaly(all_sym, symbol, 0, direction):
        anomaly_dict["1H"].append(symbol)
        return "1H"
    return ""


def batch_detect_volume_anomaly(all_sym: dict, symbols: list[str],
                                direction: str) -> list[str]:
    """批量检测成交量异动，返回异动币种列表"""
    result: dict[str, list] = {"15m": [], "1H": [], "4H": []}
    for sym in symbols:
        if _has_any_recent_anomaly(all_sym, sym, direction):
            continue
        if _is_15m_anomaly(all_sym, sym, 0, direction):
            result["15m"].append(sym)
        if _is_1h_anomaly(all_sym, sym, 0, direction):
            result["1H"].append(sym)
        if _is_4h_anomaly(all_sym, sym, 0, direction):
            result["4H"].append(sym)

    notify(
        f"15m成交量异动：{result['15m']} "
        f"1H成交量异动：{result['1H']} "
        f"4H成交量异动：{result['4H']}"
    )
    return result["15m"] + result["1H"] + result["4H"]


# =============================================================================
#  辅助分析
# =============================================================================

def select_by_fund_rate(state: AccountState) -> None:
    """筛选资金费率有利的币种"""
    from api.factory import get_exchange

    ex = get_exchange()
    for label, side_list, threshold, cmp in [
        ("上涨趋势+资金费为负", state.buy_list, -0.05, lambda t, th: t < th),
    ]:
        if not side_list:
            continue
        result = []
        for sym in side_list:
            fund_rate = ex.get_history_fund_rate(sym, ex.PRODUCT_TYPE)
            total = sum(float(x["fundingRate"]) for x in fund_rate["data"])
            if cmp(total, threshold):
                result.append(sym)
        notify(f"{label}：{result}")


def select_by_volume(all_sym: dict, state: AccountState) -> None:
    """筛选小成交量 + 不错涨跌幅的币种"""
    if state.buy_list:
        result = [
            sym for sym in state.buy_list
            if (float(all_sym[sym]["1D"]["data"][-1][2]) > float(all_sym[sym]["1D"]["data"][-1][1]) * 1.2
                and float(all_sym[sym]["1D"]["data"][-1][6]) < 6_000_000)
        ]
        notify(f"小成交量+不错的涨幅：{result}")


def select_by_volume_surge(all_sym: dict, state: AccountState) -> None:
    """筛选日成交量比前三日之和还多的币种"""
    if not state.buy_list:
        return
    result = []
    for sym in state.buy_list:
        vol_sum = sum(float(all_sym[sym]["1D"]["data"][i][6]) for i in range(-4, -1))
        bar = all_sym[sym]["1D"]["data"][-1]
        cur_vol = float(bar[6])
        cur_change = float(bar[4]) / float(bar[1])
        if cur_vol > vol_sum and (cur_vol > 10_000_000 or cur_change > 1.2):
            result.append(sym)
    notify(f"日成交量比前三日加起来还多：{result}")


def find_leading_coins(all_sym: dict) -> list[str]:
    """找出近 5 天内有 20% 以上涨幅的龙头币"""
    result = []
    for key in all_sym:
        data = all_sym[key]["1D"]["data"]
        if len(data) < 20:
            continue
        for i in range(-5, -1):
            if float(data[-1 + i][4]) > float(data[-5 + i][4]) * 1.2:
                result.append(key)
                break
    notify(f"近5天的龙头币: {result}")
    return result


def find_fairy_guide(all_sym: dict, state: AccountState) -> list[str]:
    """
    仙人指路形态：近 10 日内有一根日 K 满足：
    成交量 > 前 9 日之和，最高价涨幅 20%~60%，回落 > 8%，收阳线
    """
    result = []
    if not state.buy_list:
        return result
    for sym in state.buy_list:
        data = all_sym[sym]["1D"]["data"]
        if len(data) < 10:
            continue
        for i in range(-10, 0):
            vol_sum = sum(float(data[i + j][6]) for j in range(-10, -1))
            bar = data[i]
            o, h, c, v = float(bar[1]), float(bar[2]), float(bar[4]), float(bar[6])
            if v > vol_sum and o * 1.2 < h < o * 1.6 and h * 0.92 > c > o:
                result.append(sym)
                break
    notify(f"仙人指路：{result}")
    return result
