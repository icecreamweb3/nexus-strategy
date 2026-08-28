#!/usr/bin/env python3
"""在 Windows 上使用 PyInstaller 打包 Nexus Strategy Live。"""
import argparse
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
REQUIRED_MODULES = {
    "PyInstaller": "pyinstaller",
    "PyQt5": "PyQt5",
    "dotenv": "python-dotenv",
    "openpyxl": "openpyxl",
    "binance": "python-binance",
    "websocket": "websocket-client",
    "websockets": "websockets",
    "certifi": "certifi",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build Nexus Strategy Live Windows executable")
    parser.add_argument("--name", default="NexusStrategyLive", help="输出程序名称")
    parser.add_argument("--onedir", action="store_true", help="生成目录包而不是单文件")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口以便排错")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.platform != "win32":
        print("错误：Windows .exe 必须在 Windows 系统上构建。", file=sys.stderr)
        print("请在 Windows 中运行 scripts\\build_exe.bat。", file=sys.stderr)
        return 2

    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") * 8 != 64:
        print("错误：打包必须使用 64 位 Python 3.12。", file=sys.stderr)
        print("请运行 scripts\\build_exe.bat，由脚本选择正确解释器。", file=sys.stderr)
        return 2

    missing = [package for module, package in REQUIRED_MODULES.items()
               if importlib.util.find_spec(module) is None]
    if missing:
        print(f"缺少打包依赖：{', '.join(missing)}", file=sys.stderr)
        print(f'请使用当前解释器安装："{sys.executable}" -m pip install -r requirements.txt',
              file=sys.stderr)
        return 2

    data_separator = os.pathsep
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(PROJECT_ROOT / "build"),
        "--specpath",
        str(PROJECT_ROOT),
        "--add-data",
        f"{PROJECT_ROOT / 'app' / 'lang'}{data_separator}app/lang",
        # 显式收集全部运行依赖、Qt插件、子模块、数据文件和包元数据。
        "--collect-all", "PyQt5",
        "--collect-all", "openpyxl",
        "--collect-all", "dotenv",
        "--collect-all", "binance",
        "--collect-all", "websocket",
        "--collect-all", "websockets",
        "--collect-data", "certifi",
        # Live 版本依赖的项目包显式收集，防止动态回调模块被分析遗漏。
        "--collect-submodules", "app.client",
        "--collect-submodules", "app.live",
        "--collect-submodules", "app.storage",
        "--copy-metadata", "PyQt5",
        "--copy-metadata", "openpyxl",
        "--copy-metadata", "python-dotenv",
        "--copy-metadata", "python-binance",
        "--copy-metadata", "websocket-client",
        "--copy-metadata", "websockets",
        "--copy-metadata", "certifi",
        "--hidden-import", "openpyxl",
        "--hidden-import", "openpyxl.cell._writer",
        "--hidden-import", "openpyxl.styles",
        "--hidden-import", "et_xmlfile",
        "--onedir" if args.onedir else "--onefile",
        "--console" if args.console else "--windowed",
    ]

    icon = PROJECT_ROOT / "assets" / "nexus.ico"
    if icon.exists():
        command.extend(["--icon", str(icon)])
    command.append(str(PROJECT_ROOT / "main.py"))

    print("正在构建 Windows 可执行文件……")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    output_dir = DIST_DIR / args.name if args.onedir else DIST_DIR
    env_example = PROJECT_ROOT / ".env.example"
    if env_example.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(env_example, output_dir / ".env.example")
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (output_dir / "data").mkdir(parents=True, exist_ok=True)

    executable = output_dir / f"{args.name}.exe"
    print(f"构建完成：{executable}")
    print("Live运行依赖（PyQt5、Binance、WebSocket、SQLite及证书）已包含。")
    print("目标电脑无需安装Python或pip依赖。")
    print("请将 .env.example 复制为 .env 并填写 Binance API 配置。")
    print("实盘日志写入 logs，订单和持仓数据库写入 data。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
