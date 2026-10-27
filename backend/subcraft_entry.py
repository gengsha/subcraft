"""独立 CLI 发行版入口（打包为 subcraft / subcraft.exe）。

  subcraft <命令> ...        等同于 python backend/cli.py <命令> ...
  subcraft mcp [...]         等同于 python backend/mcp_server.py [...]（stdio MCP 服务）

可执行文件旁建一个 data 目录即进入便携模式：配置、缓存与 Whisper 模型都放在其中，不写用户目录。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import portable_data_dir  # noqa: E402


def main() -> int:
    portable = portable_data_dir()
    if portable and not os.environ.get("SUBCRAFT_DATA_DIR"):
        # 模型（HuggingFace 缓存）也放进便携目录
        os.environ.setdefault("HF_HOME", str(portable / "models"))

    argv = sys.argv[1:]
    if argv[:1] == ["mcp"]:
        import mcp_server
        sys.argv = [sys.argv[0] + " mcp", *argv[1:]]
        mcp_server.main()
        return 0
    import cli
    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
