"""将后端打包为单文件 subcraft-backend.exe（供 Electron 生产模式拉起）。

用法:
  python backend/build_exe.py            # 完整打包（含 CUDA 运行库，体积大）
  python backend/build_exe.py --no-cuda  # 精简打包（仅 CPU 识别，体积小）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cuda", action="store_true", help="不包含 nvidia CUDA 运行库")
    args = parser.parse_args()

    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
    import PyInstaller.__main__

    opts = [
        str(ROOT / "backend" / "run.py"),
        "--name=subcraft-backend",
        "--onefile",
        "--noconsole",
        f"--distpath={ROOT / 'backend' / 'dist'}",
        f"--workpath={ROOT / 'backend' / 'build'}",
        "--clean",
        "--collect-all=uvicorn",
        "--collect-all=faster_whisper",
        "--collect-all=ctranslate2",
        "--collect-all=tokenizers",
        "--collect-all=onnxruntime",
        "--collect-all=av",
        "--collect-all=huggingface_hub",
        "--hidden-import=app.main",
        "--hidden-import=app.routers.media",
        "--hidden-import=app.routers.transcribe",
        "--hidden-import=app.routers.export",
        "--hidden-import=app.routers.config",
        "--hidden-import=app.services.asr",
        "--hidden-import=app.services.translator",
        "--hidden-import=app.services.ffmpeg_tool",
        "--hidden-import=app.services.ass_builder",
        "--hidden-import=app.services.srt_builder",
        "--hidden-import=app.services.fonts",
    ]
    if not args.no_cuda:
        opts += ["--collect-all=nvidia"]
    PyInstaller.__main__.run(opts)
    print(f"\n输出: {ROOT / 'backend' / 'dist' / 'subcraft-backend.exe'}")


if __name__ == "__main__":
    main()
