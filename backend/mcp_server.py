"""SubCraft 字幕生成器 MCP 服务入口。

用法:
  python backend/mcp_server.py                     # stdio 传输（MCP 客户端标准拉起方式）
  python backend/mcp_server.py --list-tools        # 自检：打印已注册工具清单后退出
  python backend/mcp_server.py --transport streamable-http --port 47660   # HTTP 传输（可选）

MCP 客户端配置示例（Claude Desktop / Cursor / Qoder 的 mcpServers）:
  {"subcraft": {"command": "python", "args": ["E:/projects/subcraft/backend/mcp_server.py"]}}
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保无论工作目录在哪都能 import app 包（与 run.py 一致的自举方式）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.asr import _setup_cuda_dlls

_setup_cuda_dlls()          # GPU 识别需要把 CUDA 运行库目录加入 DLL 搜索路径


def _print_tools() -> None:
    from app.mcp.tools import TOOLS

    for fn in TOOLS:
        doc = (fn.__doc__ or "").strip().splitlines()
        print(f"{fn.__name__}  —  {doc[0] if doc else ''}")
    print(f"\n共 {len(TOOLS)} 个工具")


def main() -> None:
    parser = argparse.ArgumentParser(description="SubCraft MCP Server")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "streamable-http", "sse"], help="传输方式，默认 stdio")
    parser.add_argument("--host", default="127.0.0.1", help="非 stdio 传输的监听地址")
    parser.add_argument("--port", type=int, default=47660, help="非 stdio 传输的监听端口")
    parser.add_argument("--list-tools", action="store_true", help="打印工具清单后退出（自检用）")
    args = parser.parse_args()

    if args.list_tools:
        _print_tools()
        return

    from app.mcp.server import server

    if args.transport == "stdio":
        # stdio 模式下 stdout 是协议通道，任何 print 都会破坏通信；日志走 stderr
        server.run(transport="stdio")
    else:
        server.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
