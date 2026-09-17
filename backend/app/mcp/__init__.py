"""SubCraft 字幕生成器的 MCP（Model Context Protocol）服务端。

把 ASR 识别、AI 翻译、字幕编辑与导出能力封装成 MCP 工具，供 Claude / Cursor / Qoder
等 AI 客户端调用。入口见 `backend/mcp_server.py`。

注意：本包路径为 `app.mcp`，与第三方 SDK 顶层包 `mcp` 不冲突（SDK 始终以绝对导入使用）。
"""
from __future__ import annotations

__all__ = ["state", "tools", "server"]
