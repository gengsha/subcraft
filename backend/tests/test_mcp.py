"""MCP 服务测试：工具注册与 schema、会话轨道流转、任务池、stdio 端到端连通。"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.app.mcp import tools
from backend.app.mcp.compat import ToolError
from backend.app.mcp.server import server
from backend.app.mcp.state import JOBS, SESSION

BACKEND_DIR = Path(__file__).resolve().parent.parent
MCP_ENTRY = BACKEND_DIR / "mcp_server.py"

CORE_TOOLS = {
    "subcraft_status", "subcraft_probe_media", "subcraft_list_fonts", "subcraft_transcribe", "subcraft_translate",
    "subcraft_load_subtitle_file", "subcraft_generate_subtitles", "subcraft_list_tracks", "subcraft_get_segments",
    "subcraft_edit_segments", "subcraft_delete_segments", "subcraft_clean_empty_segments", "subcraft_set_style",
    "subcraft_build_ass", "subcraft_export_subtitle_files", "subcraft_export_video", "subcraft_preview_frame",
    "subcraft_job_status", "subcraft_save_project", "subcraft_load_project", "subcraft_clear_session",
}

SRT_SAMPLE = (
    "1\n00:00:01,000 --> 00:00:03,000\n你好，世界\n\n"
    "2\n00:00:03,500 --> 00:00:05,000\n第二条字幕\n\n"
    "3\n00:00:06,000 --> 00:00:07,000\n   \n"
)


@pytest.fixture(autouse=True)
def clean_session():
    SESSION.clear()
    yield
    SESSION.clear()


def _make_srt(tmp_path: Path, name: str = "demo.zh.srt") -> Path:
    p = tmp_path / name
    p.write_text(SRT_SAMPLE, encoding="utf-8")
    return p


def _make_video(tmp_path: Path, duration: int = 2) -> Path:
    """生成一段带画面的测试视频（依赖 ffmpeg）。"""
    from backend.app.services import ffmpeg_tool

    ffmpeg, _ = ffmpeg_tool.find_ffmpeg()
    src = tmp_path / "src.mp4"
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
        "-c:v", "libx264", str(src),
    ], check=True, capture_output=True)
    return src


# ------------------------------------------------------------------ 注册与 schema

def test_all_tools_registered():
    names = [fn.__name__ for fn in tools.TOOLS]
    assert len(names) == len(set(names)), "工具名重复"
    assert CORE_TOOLS <= set(names), f"缺少工具: {CORE_TOOLS - set(names)}"


def _snake(obj, name: str):
    """mcp 2.x 用 snake_case 字段，1.x 用 camelCase。"""
    return getattr(obj, name, None) if hasattr(obj, name) else getattr(obj, _camel(name))


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.title() for w in rest)


def test_server_tool_schemas():
    """ctx 参数不能出现在输入 schema 里，docstring 要成为工具描述。"""
    listing = asyncio.run(server.list_tools())
    by_name = {t.name: t for t in listing}
    assert CORE_TOOLS <= set(by_name)
    schema = _snake(by_name["subcraft_transcribe"], "input_schema")
    assert "ctx" not in schema["properties"]
    assert "video_path" in schema["properties"]
    assert "wait" in schema["properties"]
    assert schema["required"] == ["video_path"]
    assert by_name["subcraft_status"].description.startswith("SubCraft")
    props = _snake(by_name["subcraft_set_style"], "input_schema")["properties"]
    assert {"font_size", "primary_color", "alignment", "pos_x"} <= set(props)
    # 可选参数为 anyOf[integer, null]，必选参数直接是 type
    variants = props["alignment"].get("anyOf") or [props["alignment"]]
    assert any(v.get("type") == "integer" for v in variants)


def test_status_exposes_env_without_secrets():
    st = tools.subcraft_status()
    assert st["app"].startswith("SubCraft")
    assert isinstance(st["ffmpeg_ready"], bool)
    assert st["whisper"]["models"] and "large-v3-turbo" in st["whisper"]["models"]
    assert st["languages"]["zh"] == "中文"
    for p in st["ai_providers"]:
        assert "api_key" not in p, "不得回显 API Key"


def test_list_fonts_filter():
    res = tools.subcraft_list_fonts(limit=5)
    assert res["returned"] <= 5 and res["returned"] <= res["total"]
    assert tools.subcraft_list_fonts(keyword="不存在的字体xyz")["total"] == 0


# ------------------------------------------------------------------ 会话轨道流转

def test_load_edit_export_roundtrip(tmp_path):
    loaded = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path)))
    tid = loaded["track_id"]
    assert loaded["language"] == "zh"          # 从文件名推断
    assert loaded["segment_count"] == 2        # 空段被丢弃

    page = tools.subcraft_get_segments(tid)
    assert page["total"] == 2
    assert page["segments"][0] == {"index": 0, "start": 1.0, "end": 3.0,
                                   "duration": 2.0, "text": "你好，世界"}

    hits = tools.subcraft_get_segments(tid, keyword="第二条")
    assert hits["total_matches"] == 1 and hits["segments"][0]["index"] == 1

    edited = tools.subcraft_edit_segments(tid, [
        {"index": 0, "text": "哈罗，世界"},
        {"index": 1, "start": 4.0, "end": 3.0},      # 非法：结束早于开始
        {"index": 99, "text": "越界"},
    ])
    assert edited["applied"] == 1 and edited["invalid_count"] == 2
    assert tools.subcraft_get_segments(tid)["segments"][0]["text"] == "哈罗，世界"

    styled = tools.subcraft_set_style(tid, font_size=40, primary_color="#FFCC00", alignment=8, margin_v=40)
    assert styled["style"]["font_size"] == 40 and styled["style"]["alignment"] == 8

    ass = tools.subcraft_build_ass(track_ids=[tid], bilingual=False)["ass"]
    assert "哈罗，世界" in ass and ",40,&H0000CCFF," in ass

    out = tools.subcraft_export_subtitle_files(str(tmp_path / "out"), track_ids=[tid],
                                         base_name="demo", formats=["srt", "ass"], bilingual=False)
    assert out["count"] == 2
    for f in out["files"]:
        assert Path(f).is_file() and Path(f).stat().st_size > 0
    assert any(f.endswith("demo.zh.srt") for f in out["files"])

    deleted = tools.subcraft_delete_segments(tid, [0])
    assert deleted["deleted"] == 1 and deleted["remaining"] == 1
    assert tools.subcraft_list_tracks()["count"] == 1


def test_bilingual_export_merges_two_tracks(tmp_path):
    """双轨导出应额外产出 bilingual 文件，翻译轨套用副语言样式。"""
    src = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path, "a.zh.srt")), language="zh")
    trn = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path, "b.en.srt")), language="en",
                                      role="translation")
    res = tools.subcraft_export_subtitle_files(str(tmp_path / "bi"), formats=["srt"], bilingual=True,
                                         primary_id=src["track_id"])
    names = [Path(f).name for f in res["files"]]
    assert "a.zh.srt" not in names                     # base_name 默认 subtitle
    assert any(n.endswith("bilingual.srt") for n in names)
    assert len(res["files"]) == 3                      # zh + en + bilingual
    assert SESSION.get(trn["track_id"]).track.role == "translation"


def test_unknown_track_raises_tool_error():
    with pytest.raises(ToolError) as e:
        tools.subcraft_get_segments("t404")
    assert "轨道不存在" in str(e.value)
    with pytest.raises(ToolError):
        tools.subcraft_export_subtitle_files(str(Path(".")), track_ids=[])


def test_style_validation():
    # 直接在会话里造一条轨道，不依赖字幕文件
    st = SESSION.create([], language="zh", origin="manual")
    with pytest.raises(ToolError):
        tools.subcraft_set_style(st.id, primary_color="红色")
    with pytest.raises(ToolError):
        tools.subcraft_set_style(st.id, font_size=9999)
    with pytest.raises(ToolError):
        tools.subcraft_set_style(st.id, alignment=12)
    with pytest.raises(ToolError):
        tools.subcraft_set_style(st.id)                      # 什么都没改
    res = tools.subcraft_set_style(st.id, pos_x=100, pos_y=200)
    assert res["style"]["pos"] == [100.0, 200.0]
    assert tools.subcraft_set_style(st.id, clear_pos=True)["style"]["pos"] is None
    assert tools.subcraft_set_style(st.id, reset=True)["reset"] is True


def test_clean_empty_segments():
    from backend.app.models import Segment

    st = SESSION.create([
        Segment(start=0, end=1, text="正常"),
        Segment(start=1, end=2, text="  "),
        Segment(start=2, end=3, text="——"),
    ], language="zh")
    res = tools.subcraft_clean_empty_segments(st.id)
    assert res["total_removed"] == 2
    assert [s.text for s in st.track.segments] == ["正常"]


def test_project_save_and_load(tmp_path):
    from backend.app.models import Segment

    SESSION.create([Segment(start=0, end=1, text="存档内容")], language="zh", label="中文轨")
    saved = tools.subcraft_save_project(str(tmp_path / "p.json"))
    assert Path(saved["path"]).is_file()

    SESSION.clear()
    assert tools.subcraft_list_tracks()["count"] == 0
    loaded = tools.subcraft_load_project(saved["path"])
    assert loaded["tracks"][0]["segment_count"] == 1
    assert tools.subcraft_get_segments(loaded["loaded"][0])["segments"][0]["text"] == "存档内容"


# ------------------------------------------------------------------ 任务池

def test_job_runner_records_progress_and_result():
    def job(cb):
        cb(0.5, "半程")
        return {"ok": True}

    jid = JOBS.submit(job, "测试任务")
    for _ in range(100):
        snapshot = JOBS.get(jid)
        if snapshot["status"] != "running":
            break
        time.sleep(0.05)
    assert snapshot["status"] == "done" and snapshot["result"] == {"ok": True}
    assert JOBS.view(jid).get("result") is None        # 轮询视图默认不带 result
    assert JOBS.recent(5)[0]["job_id"] == jid


def test_run_job_wait_and_detach():
    async def main():
        detached = await tools._run_job(None, "后台", lambda cb: {"v": 1}, wait=False)
        waited = await tools._run_job(None, "等待", lambda cb: (cb(0.3, "跑"), {"v": 2})[1], wait=True)
        return detached, waited

    detached, waited = asyncio.run(main())
    assert detached["status"] == "running" and detached["job_id"]
    assert waited["status"] == "done" and waited["v"] == 2


def test_run_job_propagates_error():
    async def main():
        def boom(cb):
            raise RuntimeError("识别炸了")
        return await tools._run_job(None, "识别", boom, wait=True)

    with pytest.raises(ToolError) as e:
        asyncio.run(main())
    assert "识别炸了" in str(e.value)


def test_job_status_tool():
    jid = JOBS.submit(lambda cb: {"done": 1}, "x")
    time.sleep(0.3)
    assert tools.subcraft_job_status(jid)["status"] == "done"
    assert tools.subcraft_job_status()["count"] >= 1
    with pytest.raises(ToolError):
        tools.subcraft_job_status("不存在的任务")


# ------------------------------------------------------------------ 需要 ffmpeg 的部分

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    and not (BACKEND_DIR.parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe").exists(),
    reason="无 ffmpeg 可用",
)


@needs_ffmpeg
def test_probe_and_export_video_soft(tmp_path):
    from backend.app.services import ffmpeg_tool

    src = _make_video(tmp_path)
    info = tools.subcraft_probe_media(str(src))
    assert info["width"] == 320 and info["duration"] > 0

    loaded = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path)), video_path=str(src))
    out = tmp_path / "soft.mkv"
    res = asyncio.run(tools.subcraft_export_video(None, str(out), track_ids=[loaded["track_id"]],
                                            mode="soft", wait=True))
    assert res["status"] == "done" and out.is_file() and out.stat().st_size > 0
    assert ffmpeg_tool.probe(str(out)).video_codec == "h264"     # 视频流直接复制


@needs_ffmpeg
def test_export_video_rejects_bad_args(tmp_path):
    from backend.app.services import ffmpeg_tool

    if not ffmpeg_tool.find_ffmpeg():
        pytest.skip("无 ffmpeg 可用")
    src = _make_video(tmp_path)
    loaded = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path)), video_path=str(src))
    with pytest.raises(ToolError):
        asyncio.run(tools.subcraft_export_video(None, str(tmp_path / "x.txt"),
                                          track_ids=[loaded["track_id"]]))
    with pytest.raises(ToolError):
        asyncio.run(tools.subcraft_export_video(None, str(src), track_ids=[loaded["track_id"]]))


@needs_ffmpeg
def test_preview_frame_returns_image(tmp_path):
    from backend.app.services import ffmpeg_tool

    ff = ffmpeg_tool.find_ffmpeg()
    if not ff:
        pytest.skip("无 ffmpeg 可用")
    if not ffmpeg_tool._has_filter(ff[0], "ass") and not ffmpeg_tool._has_filter(ff[0], "subtitles"):
        pytest.skip("当前 ffmpeg 无 libass 滤镜")
    src = _make_video(tmp_path)
    loaded = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path)), video_path=str(src))
    jpg = tmp_path / "frame.jpg"
    img = tools.subcraft_preview_frame(time=1.5, track_ids=[loaded["track_id"]],
                                 video_path=str(src), out_path=str(jpg))
    assert _snake(img.to_image_content(), "mime_type") == "image/jpeg"
    assert len(img.data) > 1000
    assert jpg.is_file() and jpg.stat().st_size > 1000


# ------------------------------------------------------------------ stdio 端到端

def test_stdio_end_to_end(tmp_path):
    """真实拉起 MCP 子进程：initialize → list_tools → call_tool（含错误消息回传）。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def main():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(MCP_ENTRY)],
            env={**os.environ, "SUBCRAFT_DATA_DIR": str(tmp_path), "PYTHONIOENCODING": "utf-8"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert _snake(init, "server_info").name == "subcraft"
                assert init.instructions and "subcraft_transcribe" in init.instructions

                listing = await session.list_tools()
                names = {t.name for t in listing.tools}
                assert CORE_TOOLS <= names

                ok = await session.call_tool("subcraft_status", {})
                assert not _snake(ok, "is_error")
                payload = json.loads(ok.content[0].text)
                assert payload["app"].startswith("SubCraft")
                assert payload["session_tracks"] == []

                srt = _make_srt(tmp_path)
                loaded = await session.call_tool("subcraft_load_subtitle_file", {"path": str(srt)})
                assert not _snake(loaded, "is_error")
                tid = json.loads(loaded.content[0].text)["track_id"]

                segs = await session.call_tool("subcraft_get_segments", {"track_id": tid})
                assert json.loads(segs.content[0].text)["segments"][0]["text"] == "你好，世界"

                bad = await session.call_tool("subcraft_get_segments", {"track_id": "t404"})
                assert _snake(bad, "is_error") and "轨道不存在" in bad.content[0].text

    asyncio.run(main())


def test_add_translation_by_agent(tmp_path):
    """调用方 AI 自己翻译：分批写入、越界校验、缺失统计，时间轴沿用源轨。"""
    src = tools.subcraft_load_subtitle_file(str(_make_srt(tmp_path)))
    sid = src["track_id"]
    first = tools.subcraft_add_translation(sid, "en", ["Hello, world"])
    tid = first["track_id"]
    assert first["applied"] == 1 and first["missing"] == [1] and "next_step" in first
    second = tools.subcraft_add_translation(sid, "en", [{"index": 1, "text": "Second"}, {"index": 9, "text": "x"}],
                                            track_id=tid)
    assert second["applied"] == 1 and second["missing_count"] == 0 and len(second["invalid"]) == 1
    a = tools.subcraft_get_segments(sid)["segments"]
    b = tools.subcraft_get_segments(tid)["segments"]
    assert [(s["start"], s["end"]) for s in a] == [(s["start"], s["end"]) for s in b]
    assert b[1]["text"] == "Second"
    with pytest.raises(ToolError):
        tools.subcraft_add_translation(sid, "xx", ["a"])
