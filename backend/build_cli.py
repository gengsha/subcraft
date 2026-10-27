"""把 CLI + MCP 服务打包为独立的 subcraft 命令行发行版（不含桌面客户端）。

用法:
  python backend/build_cli.py             # 输出 backend/dist/subcraft/（onedir：subcraft[.exe] + _internal/）

为什么用 onedir 而不是 onefile：onefile 每次运行都要解压到系统临时目录（_MEIxxxx），
被强制结束时会残留；onedir 直接运行，不在用户机器上额外产生文件。
发行版只做 CPU 识别（不含 CUDA 运行库）；ffmpeg 不随包分发，
Windows 首次需要时自动下载到可执行文件旁的 tools/，Linux 请用包管理器安装。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
    import PyInstaller.__main__

    backend = ROOT / "backend"
    opts = [
        str(backend / "subcraft_entry.py"),
        "--name=subcraft",
        "--onedir",
        "--console",
        "--noconfirm",
        "--clean",
        f"--distpath={backend / 'dist'}",
        f"--workpath={backend / 'build-cli'}",
        f"--specpath={backend / 'build-cli'}",
        f"--paths={backend}",
        "--collect-all=faster_whisper",
        "--collect-all=ctranslate2",
        "--collect-all=tokenizers",
        "--collect-all=onnxruntime",
        "--collect-all=av",
        "--collect-all=huggingface_hub",
        "--collect-submodules=mcp.server",
        "--collect-submodules=mcp.shared",
        "--hidden-import=mcp.types",
        "--collect-submodules=app",
        "--hidden-import=cli",
        "--hidden-import=mcp_server",
        # CLI / MCP 用不到的大件
        "--exclude-module=tkinter",
        "--exclude-module=nvidia",
        "--exclude-module=torch",
        "--exclude-module=uvloop",
        "--exclude-module=watchfiles",
        "--exclude-module=httptools",
    ]
    PyInstaller.__main__.run(opts)
    print(f"\n输出: {backend / 'dist' / 'subcraft'}")


if __name__ == "__main__":
    main()
