# Nexus Strategy — 交易策略回测系统

基于 PyQt5 的桌面交易软件：K线 CSV 回测 + 币安合约实盘接口（REST + WebSocket 订单监听），支持中英文界面切换。

## 功能

1. **策略回测**：导入 K线 CSV/Excel（OHLCV），按可配置策略参数回测
   - 趋势累积策略 / K线形态策略 / 反转确认策略 / 成交比策略（均可勾选启用）
   - 开单参数：仓位、手续费、止盈止损价差、止损冷静期、限价/市价、交易方向、回看检查等
2. **回测结果**：总交易笔数、总盈亏、总手续费、做多/做空笔数、最大区间亏损值、最大亏损区间 (#i-#j)
3. **交易明细**：逐笔记录（类型/方向/开平仓K线与价格/盈亏/手续费），可导出 CSV
4. **回测日志**：分页、关键词搜索、仅显示触发交易、导出
5. **实盘交易**：币安合约 REST 下单/查余额，WebSocket 用户数据流实时监听订单状态变化
6. **国际化**：菜单栏「语言 / Language」运行时切换中英文

## 安装与运行

```bash
pip install -r requirements.txt

cp .env.example .env   # 填入 BINANCE_API_KEY / BINANCE_API_SECRET

# 生成示例数据并运行
python scripts/gen_sample_data.py
python main.py
```

## 配置（.env）

| 变量 | 说明 |
| --- | --- |
| `BINANCE_API_KEY` | 币安 API Key |
| `BINANCE_API_SECRET` | 币安 API Secret |
| `BINANCE_TESTNET` | `true` 使用合约测试网，`false` 实盘 |
| `BINANCE_SYMBOL` | 默认交易对，如 `BTCUSDT` |

## K线 CSV 格式

支持表头自动识别（`open_time/open/high/low/close/volume` 或中文列名），无表头时按
`时间,开,高,低,收,量` 顺序解析。也支持 `.xlsx`。

## 日志

交易日志写入 `logs/trade.log`（RotatingFileHandler，单文件 5MB × 5 份）。

## 目录结构

```
app/
├── config.py          # .env 配置加载
├── logger.py          # 交易日志
├── i18n.py + lang/    # 中英文语言包
├── api/               # 币安合约 REST + WebSocket 订单监听
├── backtest/          # 数据加载、回测引擎、结果统计
└── ui/                # 主窗口、回测页、实盘页
scripts/gen_sample_data.py
```
