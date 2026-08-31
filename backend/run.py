"""后端启动入口（供 Electron 拉起 / 独立调试）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保无论工作目录在哪都能 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=47653)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
