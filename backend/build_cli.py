"""把 CLI + MCP 服务打包为独立的 subcraft 命令行发行版（不含桌面客户端）。

用法:
  python backend/build_cli.py             # 输出 backend/dist/subcraft/（onedir：subcraft[.exe] + _internal/）

体积：只打包 CLI/MCP 真正用到的部分；PyAV、hf_xet、onnxruntime 附带工具等全部剔除。

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

EXCLUDES = [
    "av", "hf_xet", "torch", "nvidia", "PIL", "aiohttp",
    "onnxruntime.quantization", "onnxruntime.transformers", "onnxruntime.tools", "onnxruntime.training",
    "uvloop", "watchfiles", "httptools",
    "numpy.f2py", "numpy.distutils", "numpy.testing", "numpy.typing",
    "tkinter", "unittest", "pydoc_data", "lib2to3", "idlelib", "ensurepip", "distutils",
    "setuptools", "pip", "pkg_resources", "test",
]


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
        f"--runtime-hook={backend / 'pyi_rth_noav.py'}",
        "--collect-all=faster_whisper",          # 含 Silero VAD 模型
        "--collect-all=ctranslate2",
        "--collect-binaries=onnxruntime",        # 只要运行库，不要 quantization/transformers/tools
        "--hidden-import=onnxruntime.capi._pybind_state",
        "--collect-submodules=huggingface_hub",  # 惰性导入，需显式收集
        "--collect-submodules=mcp.server",
        "--collect-submodules=mcp.shared",
        "--hidden-import=mcp.types",
        "--collect-submodules=app",
        "--hidden-import=cli",
        "--hidden-import=mcp_server",
    ]
    if sys.platform != "win32":
        opts.append("--strip")                   # 去掉 .so 调试符号
    # 用不到的大件：PyAV 由运行时钩子占位；hf_xet 缺失时 huggingface_hub 自动回退普通 HTTP 下载
    for mod in EXCLUDES:
        opts.append(f"--exclude-module={mod}")
    PyInstaller.__main__.run(opts)
    print(f"\n输出: {backend / 'dist' / 'subcraft'}")


if __name__ == "__main__":
    main()
