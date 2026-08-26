#!/usr/bin/env python3
"""在 Windows 上使用 PyInstaller 打包 Nexus Strategy。"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"


def parse_args():
    parser = argparse.ArgumentParser(description="Build Nexus Strategy Windows executable")
    parser.add_argument("--name", default="NexusStrategy", help="输出程序名称")
    parser.add_argument("--onedir", action="store_true", help="生成目录包而不是单文件")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口以便排错")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.platform != "win32":
        print("错误：Windows .exe 必须在 Windows 系统上构建。", file=sys.stderr)
        print("请在 Windows 中运行 scripts\\build_exe.bat。", file=sys.stderr)
        return 2

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未安装 PyInstaller，请先运行：pip install -r requirements.txt", file=sys.stderr)
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
        "--hidden-import",
        "openpyxl",
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

    executable = output_dir / f"{args.name}.exe"
    print(f"构建完成：{executable}")
    print("程序运行日志和回测日志将在可执行文件旁的 logs 文件夹中生成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
