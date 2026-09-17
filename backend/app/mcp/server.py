"""MCP 服务端装配：注册全部 `subcraft_*` 工具并下发使用说明。

工具实现在 `tools.py`，通过 `@tool` 装饰器登记到 `TOOLS`；这里只负责建服务实例。
"""
from __future__ import annotations

from .compat import MCPServer
from .tools import TOOLS

SERVER_NAME = "subcraft"
SERVER_TITLE = "SubCraft 字幕生成器"
SERVER_VERSION = "0.1.1"

INSTRUCTIONS = """SubCraft 字幕生成器：把视频变成字幕文件与带字幕的成片（本地 faster-whisper 识别 + 多厂商 AI 翻译 + ffmpeg 封装/压制）。

标准流程：
1. subcraft_status —— 自检：ffmpeg_ready、cuda_available、已配置的翻译厂商（api_key_set）
2. subcraft_transcribe —— 识别视频语音，得到源语言 track_id
3. subcraft_translate —— 翻译成目标语言，得到翻译轨 track_id（不需要翻译可跳过）
4. subcraft_get_segments / subcraft_edit_segments —— 抽查与批量校对文本、修时间码
5. subcraft_set_style + subcraft_preview_frame —— 调字体字号颜色位置，并看一帧真实烧录效果
6. subcraft_export_subtitle_files（srt/ass）或 subcraft_export_video（soft 无损封装 / hard 烧录成片）

想一步到位就用 subcraft_generate_subtitles：识别 → 翻译 → 导出字幕（可选直接出成片）。

要点：
- 识别/翻译/压制是长任务。客户端调用有超时限制时传 wait=false 立即拿 job_id，再用 subcraft_job_status 轮询；wait=true 时会持续上报进度。
- track_id 只存在于当前 MCP 进程会话中。需要跨会话保留就先 subcraft_save_project，之后 subcraft_load_project 恢复。
- 翻译用的 API Key 复用 SubCraft 桌面客户端「设置」里保存的本地配置，本服务只读不写；也可在调用时临时传 api_key/base_url。
- 所有文件路径一律用绝对路径。字幕段格式为 {index, start, end, text}，时间单位秒，index 是轨道内 0 基序号。
- 目标语言码：zh 中文 / en 英语 / ja 日语 / ko 韩语 / fr de es ru it pt ar th vi id hi yue，完整表见 subcraft_status。
"""


def create_server() -> MCPServer:
    """构建 MCP 服务实例并注册全部工具。"""
    try:
        server = MCPServer(
            name=SERVER_NAME, instructions=INSTRUCTIONS,
            title=SERVER_TITLE, version=SERVER_VERSION,
        )
    except Exception:                       # 老版本 SDK 不认识 title/version 参数
        server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS)
    for fn in TOOLS:
        server.add_tool(fn)
    return server


server = create_server()
