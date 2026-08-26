# Nexus Strategy — 交易策略回测系统

基于 PyQt5 的 K线策略回测桌面软件，支持 CSV/Excel 数据与中英文界面切换。

## 功能

1. **策略回测**：导入 K线 CSV/Excel（OHLCV），按可配置策略参数回测
   - 成交量、单根涨跌、连续K线、累计涨跌、ATR和逆势影线过滤（均可勾选启用）
   - 开单参数：仓位、手续费、百分比止盈止损、加仓、交易方向、最长持仓等；信号后下一根连续K线开盘成交
2. **回测结果**：总交易笔数、总盈亏、总手续费、做多/做空笔数、最大区间亏损值、最大亏损区间 (#i-#j)
3. **交易明细**：逐笔记录（类型/方向/开平仓K线与价格/盈亏/手续费），可导出 CSV
4. **回测日志**：分页、关键词搜索、仅显示触发交易、导出
5. **国际化**：菜单栏「语言 / Language」运行时切换中英文

## 安装与运行

```bash
pip install -r requirements.txt

cp .env.example .env   # 可选：设置默认界面语言

# 生成示例数据并运行
python scripts/gen_sample_data.py
python main.py
```

## 打包 Windows EXE

Windows 环境安装依赖后运行：

```bat
scripts\build_exe.bat
```

默认生成单文件 GUI 程序 `dist\NexusStrategy.exe`，并复制 `.env.example` 到输出目录。可选参数：

```bat
scripts\build_exe.bat --console       rem 保留控制台，便于排错
scripts\build_exe.bat --onedir        rem 生成目录形式
scripts\build_exe.bat --name MyTrader rem 修改程序名称
```

Windows EXE 需要在 Windows 上构建。程序启动后会在 EXE 所在目录创建 `logs` 文件夹；如需设置默认语言，可将 `.env.example` 复制为 `.env` 后修改 `UI_LANGUAGE`。

## 配置（.env）

| 变量 | 说明 |
| --- | --- |
| `UI_LANGUAGE` | 默认界面语言：`zh_CN` 或 `en_US`（简写 `zh` / `en` 亦可），缺省为 `zh_CN` |

## K线 CSV 格式

支持表头自动识别（`open_time/open/high/low/close/volume` 或中文列名），无表头时按
`时间,开,高,低,收,量` 顺序解析。也支持 `.xlsx`。

## 日志

应用日志写入 `logs/trade.log`（RotatingFileHandler，单文件 5MB × 5 份）；每次回测另行生成带执行时间戳的 `logs/backtest_*.log` K线明细文件。

## 目录结构

```
app/
├── config.py          # .env 配置加载
├── logger.py          # 交易日志
├── i18n.py + lang/    # 中英文语言包
├── backtest/          # 数据加载、回测引擎、结果统计
└── ui/                # 主窗口与回测页
scripts/gen_sample_data.py
```
