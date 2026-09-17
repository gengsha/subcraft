"""MCP SDK 兼容层：mcp>=2 的 `MCPServer` 与 mcp<2 的 `FastMCP` 接口基本一致。

统一从这里导入 `MCPServer / Context / Image / ToolError`，避免业务代码写两套分支。
"""
from __future__ import annotations

try:                                     # mcp >= 2.0
    from mcp.server.mcpserver import Context, Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ModuleNotFoundError:              # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP as MCPServer, Image  # type: ignore
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore

__all__ = ["MCPServer", "Context", "Image", "ToolError"]
