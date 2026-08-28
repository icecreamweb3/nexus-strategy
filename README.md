# Nexus Strategy — Binance 实时交易策略系统

基于 PyQt5 的 Binance USDⓈ-M 合约实时策略桌面软件，支持实时 K 线、自动下单、订单状态推送与中英文界面切换。

## 功能

1. **实时策略**：点击 Start Trading 后按当前参数自动计算所需历史窗口，通过 REST 预热并立即检测最新已收盘 K 线，随后由 WebSocket 接收实时 K 线
   - 成交量、单根涨跌、连续K线、累计涨跌、ATR和逆势影线过滤（均可勾选启用）
   - 原回测分支的组合条件检测逻辑保持不变；仅处理 Binance 标记为已收盘的 K 线
2. **实盘下单**：信号确认后调用 Binance Futures 市价下单 API；已有同 ticker 持仓时跳过新首仓
3. **交易记录**：当前持仓、持仓历史、当前委托和历史订单分栏展示；订单 WebSocket 推送与账户刷新结果持久化到 SQLite
4. **实时日志**：支持分页、关键词搜索、仅显示触发事件和导出
5. **国际化**：菜单栏「语言 / Language」运行时切换中英文

## 安装与运行

```bash
pip install -r requirements.txt

cp .env.example .env   # 填入 Binance API 配置

python main.py
```

## 打包 Windows EXE

Windows 环境直接运行：

```bat
scripts\build_exe.bat
```

构建机需要安装 **64 位 Python 3.12**。脚本会自动创建或复用专用的 `.build-venv-py312`，并通过该环境安装 `requirements.txt` 中的全部二进制依赖后再开始打包，避免系统 Python、开发虚拟环境与打包环境依赖不一致。若未安装，请从 [Python Windows 下载页](https://www.python.org/downloads/windows/) 安装并启用 Python Launcher。

默认生成单文件 GUI 程序 `dist\NexusStrategy.exe`，并复制 `.env.example` 到输出目录。Python 运行时、PyQt5（含 Qt 平台插件）、openpyxl、python-dotenv 及其递归依赖都会包含在构建产物中，目标电脑无需安装 Python 或 pip 包。可选参数：

```bat
scripts\build_exe.bat --console       rem 保留控制台，便于排错
scripts\build_exe.bat --onedir        rem 生成目录形式
scripts\build_exe.bat --name MyTrader rem 修改程序名称
```

Windows EXE 需要在 Windows 上构建。程序启动后会在 EXE 所在目录创建 `logs` 文件夹；如需设置默认语言，可将 `.env.example` 复制为 `.env` 后修改 `UI_LANGUAGE`。

## 配置（.env）

| 变量 | 说明 |
| --- | --- |
| `BINANCE_API_KEY` | Binance API Key |
| `BINANCE_API_SECRET` | Binance API Secret |
| `BINANCE_TESTNET` | `true` 使用合约测试网，建议先在测试网验证 |
| `BINANCE_SYMBOL` | 默认 ticker，例如 `BTCUSDT` |
| `UI_LANGUAGE` | 默认界面语言：`zh_CN` 或 `en_US`（简写 `zh` / `en` 亦可），缺省为 `zh_CN` |

## 日志

应用日志写入 `logs/trade.log`（RotatingFileHandler，单文件 5MB × 5 份）。每次点击 Start Trading 会另外生成 `logs/trader_live_时间戳.log`，记录该次实盘会话的策略检测和下单日志。

订单、成交和持仓数据写入 `data/nexus_strategy.sqlite3`，首次启动时自动创建表和索引。

## 目录结构

```
app/
├── config.py          # .env 配置加载
├── logger.py          # 交易日志
├── i18n.py + lang/    # 中英文语言包
├── backtest/          # 原条件检测引擎（实时模式复用）
├── client/            # Binance REST 与 K线 WebSocket 接入
├── live/              # 实时信号处理
├── storage/           # SQLite 交易数据存储
└── ui/                # 主窗口与实时策略页
```
