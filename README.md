# 合约自动化交易机器人

多交易所 USDT 永续合约自动化交易机器人，通过多周期技术指标共振 + 成交量异动检测筛选交易机会，支持钉钉实时通知。

## 支持功能

- **多交易所** — Bitget / Binance，通过环境变量一键切换
- **合约带单** — Bitget 交易员带单模式，自动同步开平仓和止盈止损给跟单者
- **模拟盘** — Bitget 模拟盘交易，用虚拟资金测试策略，零风险验证
- **多周期策略** — 15m / 1H / 4H / 1D 趋势共振 + BTC 大盘过滤（仅做多）
- **动态风控** — 阶梯回撤止盈、时间止损、爆仓保护、最大回撤关停
- **钉钉通知** — 交易信号、开平仓、带单状态实时推送

## 项目结构

```
├── main.py                      # 入口文件
├── models.py                    # 数据模型（Candle、AccountState）
├── config.yaml                  # 交易参数配置
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── core/                        # 核心交易逻辑
│   ├── live_trading.py          #   主编排（扫描 → 选币 → 下单 → 监控）
│   ├── strategy.py              #   趋势判断（多周期）、BTC 方向过滤
│   ├── scanner.py               #   成交量异动检测、辅助选币
│   ├── order.py                 #   开仓、平仓、统一下单入口
│   ├── position.py              #   仓位管理（止盈止损、价格追踪）
│   ├── copy_trading.py          #   带单管理（状态监控、同步止盈止损）
│   └── data_fetcher.py          #   异步 K 线获取、技术指标计算
├── api/                         # 交易所抽象与适配
│   ├── exchange.py              #   交易所统一抽象接口
│   ├── bitget_client.py         #   Bitget 适配器（含带单 API）
│   ├── bitget_api.py            #   Bitget REST API 封装（遗留）
│   ├── binance_client.py        #   Binance 适配器
│   ├── factory.py               #   交易所工厂（单例）
│   └── retry.py                 #   重试装饰器
├── analysis/                    # 技术指标计算
│   ├── bollinger_bands.py       #   布林带
│   ├── macd.py                  #   MACD
│   └── ma.py                    #   移动平均线
└── infra/                       # 基础设施
    ├── logger.py                #   日志（logging + 钉钉 handler）
    ├── config.py                #   配置管理（YAML 热加载）
    ├── send_msg.py              #   钉钉消息推送
    ├── env.py                   #   环境配置（API 密钥、代理）
    └── util.py                  #   工具函数（时间处理）
```

## 快速开始

### 1. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入对应交易所的 API 密钥：

```bash
# 交易所选择: bitget / binance
EXCHANGE=bitget

# Bitget API
BITGET_API_KEY=your_api_key
BITGET_API_SECRET=your_api_secret
BITGET_API_PASSPHRASE=your_passphrase

# Bitget 模拟盘（设为 true 启用，需使用模拟盘 API Key）
BITGET_DEMO=false

# Binance API
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

# 钉钉通知
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=your_token
DINGTALK_SECRET=your_secret
```

### 3. 调整交易参数

编辑 `config.yaml`，支持运行时热加载：

```yaml
leverage: 10
max_long_positions: 3
copy_trading_enabled: false   # 带单模式开关
```

### 4. 运行

```bash
python3 main.py
```

## 交易所切换

通过 `EXCHANGE` 环境变量切换，所有交易逻辑通过统一抽象接口调用，无需改代码：

| 环境变量 | 交易所 | 需要的密钥 |
|---------|--------|-----------|
| `EXCHANGE=bitget` | Bitget（默认） | `BITGET_API_KEY` / `SECRET` / `PASSPHRASE` |
| `EXCHANGE=binance` | Binance | `BINANCE_API_KEY` / `SECRET` |

## Bitget 模拟盘

用虚拟资金在实时行情下测试策略，适合上线前验证：

1. 登录 Bitget → 切换到模拟盘 → 个人中心 → API Key 管理 → 创建模拟盘 API Key
2. 将模拟盘 Key 填入 `.env` 的 `BITGET_API_KEY` 等字段
3. 设置 `BITGET_DEMO=true`
4. 启动后会提示 "⚠️ 当前为模拟盘模式"

## Bitget 合约带单

作为交易员（带单员），机器人下单后 Bitget 自动广播给跟单者。本模块额外保证：

- 策略触发平仓时，通过带单 API 同步平仓，确保跟单者一起平
- 开仓后自动将止盈止损同步到带单订单
- 每次策略执行时汇报当前带单状态（跟单人数、持仓详情）
- 每 4 小时汇报历史带单收益（胜率、盈亏）

启用方式：先在 Bitget 申请成为交易员，然后在 `config.yaml` 中设置 `copy_trading_enabled: true`。

## 策略概述

```
主循环（每 15 分钟）
  ├── 拉取全市场 K 线（1D / 4H / 1H / 15m）
  ├── 计算技术指标（布林带、MACD、MA）
  ├── 筛选做多信号
  │   ├── 多周期趋势共振（15m + 1H + 4H + 1D 同时看多）
  │   ├── BTC 大盘方向过滤（近 12 小时未下跌）
  │   ├── 防追高（布林带宽度、7 日涨幅）
  │   └── 波动充足
  ├── 执行下单
  └── 辅助分析（成交量异动通知、资金费率、龙头币、仙人指路形态）

持仓监控（每 1 分钟，基于内存持仓数据）
  ├── 价格追踪（记录最高价）
  └── 动态止盈
      ├── 阶梯回撤止盈（涨 6%~50% 对应不同回撤容忍度）
      ├── 时间止损（超 2 天亏损 / 超 3 天盈利不足 6%）
      └── 布林上轨下弯平仓

> 持仓信息在每次全市场扫描前从服务器同步一次，开仓/平仓后同时更新内存，避免频繁调用 API 触发限流。
```

## 风控机制

| 机制 | 触发条件 | 动作 |
|------|---------|------|
| 最大回撤关停 | 回撤 > 10% | 进入关停模式，仅开最小仓位 |
| 爆仓保护 | 24h 内爆仓 > 2 次 | 进入关停模式 |
| 时间止损 | 持仓 > 2 天仍亏损 | 平仓 |
| 阶梯回撤止盈 | 涨幅 6%~50% | 按档位允许不同回撤幅度 |
| 布林上轨下弯 | 日线上轨拐头 | 平仓 |
