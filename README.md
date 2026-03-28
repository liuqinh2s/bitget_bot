# Bitget 合约自动化交易机器人

基于 Bitget 交易所 API 的 USDT 永续合约自动化交易机器人，通过多周期技术指标共振 + 成交量异动检测筛选交易机会，并通过 Telegram 实时推送交易通知。

## 项目结构

```
bitget_bot/
├── main.py                      # 入口文件
├── __init__.py
├── models.py                    # 数据模型（Candle、AccountState）
├── config.yaml                  # 交易参数配置文件
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── core/                        # 核心交易逻辑
│   ├── live_trading.py          #   主编排（扫描 → 选币 → 下单 → 监控）
│   ├── strategy.py              #   趋势判断（多周期）、BTC 方向过滤
│   ├── scanner.py               #   成交量异动检测、辅助选币
│   ├── order.py                 #   开仓、平仓、统一下单入口
│   ├── position.py              #   仓位管理（止盈止损、价格追踪）
│   └── data_fetcher.py          #   异步 K 线获取、技术指标计算
├── api/                         # API 与网络层
│   ├── bitget_api.py            #   Bitget REST API 封装
│   └── retry.py                 #   重试装饰器
├── analysis/                    # 技术指标计算
│   ├── bollinger_bands.py       #   布林带
│   ├── macd.py                  #   MACD
│   └── ma.py                    #   简单移动平均线
├── infra/                       # 基础设施
│   ├── logger.py                #   日志框架（logging + Telegram handler）
│   ├── config.py                #   配置管理（YAML 加载、热加载）
│   ├── send_msg.py              #   Telegram 消息推送
│   ├── env.py                   #   环境配置（API 密钥、代理）
│   └── util.py                  #   工具函数（时间处理）
└── README.md
```

## 策略概述

```
主循环（每 15 分钟）
  ├── 拉取全市场 K 线数据（1D / 4H / 1H / 15m）
  ├── 计算技术指标（布林带、MACD、MA）
  ├── 筛选交易信号
  │   ├── 成交量异动检测（15m / 1H / 4H）
  │   ├── 多周期趋势共振（15m + 1H + 4H + 1D 同时看多）
  │   ├── BTC 大盘方向过滤
  │   └── 防追高过滤（布林带宽度、7 日涨幅）
  ├── 执行下单
  └── 辅助分析（资金费率、龙头币、仙人指路形态）

持仓监控（每 1 分钟）
  ├── 价格追踪（记录最高/最低价）
  └── 动态止盈
      ├── 阶梯回撤止盈（涨 6%~50% 对应不同回撤容忍度）
      ├── 时间止损（超 2 天亏损 / 超 3 天盈利不足 6%）
      └── 布林上轨下弯平仓
```

## 快速开始

### 1. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的 API 密钥：

```bash
cp .env.example .env
```

### 3. 调整交易参数

编辑 `config.yaml` 调整杠杆、止盈档位、ban list 等参数，支持运行时热加载。

### 4. 运行

```bash
python3 -m bitget_bot.main
```

## 风控机制

| 机制 | 触发条件 | 动作 |
|------|---------|------|
| 最大回撤关停 | 回撤 > 10% | 进入关停模式，仅开最小仓位 |
| 爆仓保护 | 24h 内爆仓 > 2 次 | 进入关停模式 |
| 时间止损 | 多仓持仓 > 2 天仍亏损 | 平仓 |
| 阶梯回撤止盈 | 涨幅 6%~50% | 按档位允许不同回撤幅度 |
| 布林上轨下弯 | 日线上轨拐头 | 平多仓 |
| 48h 亏损 ban | 48h 内亏损平仓的币种 | 不再交易该币种 |

## 架构改进

本次重构相比初始版本的主要改进：

1. **AccountState 类** — 替代全局 `account` 字典，状态变更通过方法完成
2. **模块拆分** — `live_trading.py` 从 ~1300 行拆分为 6 个职责单一的模块
3. **Candle dataclass** — 结构化 K 线数据模型（`models.py`）
4. **logging 框架** — 统一日志管理，Telegram 作为 WARNING handler
5. **配置外部化** — 交易参数移至 `config.yaml`，支持热加载
6. **异常处理细化** — 捕获具体异常类型，关键路径异常上报
7. **重试装饰器** — 统一处理网络异常的自动重试
8. **API 层修复** — `_post()` 不再同时传 `data` 和 `json`，使用 `Session` 复用连接
9. **requirements.txt** — 依赖声明
