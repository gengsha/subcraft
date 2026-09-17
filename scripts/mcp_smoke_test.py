"""MCP 服务端到端冒烟测试：以真实 MCP 客户端（stdio 子进程）跑通完整链路。

用法:
  .\\.venv\\Scripts\\python.exe scripts\\mcp_smoke_test.py                 # 导入→编辑→样式→导出→封装→预览帧
  .\\.venv\\Scripts\\python.exe scripts\\mcp_smoke_test.py --asr           # 追加真实语音识别（首次会下载 whisper 模型）
  .\\.venv\\Scripts\\python.exe scripts\\mcp_smoke_test.py --asr --media D:\\demo.mp4 --target-lang zh

依赖：项目 .venv 已安装 `mcp`（见 backend/requirements-mcp.txt）；ffmpeg 位于 tools/ffmpeg 或系统 PATH。
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MCP_ENTRY = ROOT / "backend" / "mcp_server.py"

sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters        # noqa: E402
from mcp.client.stdio import stdio_client                   # noqa: E402

SRT_SAMPLE = (
    "1\n00:00:00,300 --> 00:00:01,800\nHello world, this is SubCraft.\n\n"
    "2\n00:00:02,000 --> 00:00:03,600\nSubtitle pipeline smoke test.\n\n"
    "3\n00:00:04,000 --> 00:00:04,600\n   \n"
)
TTS_TEXT = (
    "Hello world. This is the SubCraft subtitle generator. "
    "The quick brown fox jumps over the lazy dog. "
    "Speech recognition test, one two three."
)

STEPS: list[str] = []
# 进度回调仅部分 SDK 版本支持，按签名探测一次
_SUPPORTS_PROGRESS = "progress_callback" in inspect.signature(ClientSession.call_tool).parameters


def _field(obj: Any, name: str) -> Any:
    """mcp 2.x 用 snake_case 字段，1.x 用 camelCase。"""
    if hasattr(obj, name):
        return getattr(obj, name)
    head, *rest = name.split("_")
    return getattr(obj, head + "".join(w.title() for w in rest))


def log(step: str, msg: str) -> None:
    STEPS.append(step)
    print(f"[{len(STEPS):02d}] {step:<22} {msg}")


async def call(session: ClientSession, name: str, show_progress: bool = False, **args: Any) -> Any:
    """调用工具并解出 JSON 结果；失败抛 RuntimeError（含服务端回传的中文错误）。"""
    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        print(f"      … {progress:.0f}%  {message or ''}", flush=True)

    kwargs = {"progress_callback": on_progress} if (show_progress and _SUPPORTS_PROGRESS) else {}
    res = await session.call_tool(name, args, **kwargs)
    texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
    body = texts[0] if texts else ""
    if _field(res, "is_error"):
        raise RuntimeError(f"{name} 调用失败: {body}")
    images = [c for c in res.content if getattr(c, "type", "") == "image"]
    if images and not body:
        return {"__image_bytes__": len(_field(images[0], "data") or "")}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


# ------------------------------------------------------------------ 测试素材

def ffmpeg_bin() -> str:
    bundled = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit("未找到 ffmpeg（tools/ffmpeg/bin 或系统 PATH）")
    return found


def make_media(work: Path, with_speech: bool) -> Path:
    """生成 5 秒测试视频；with_speech 时用 Windows SAPI 合成一段英文语音。"""
    ff = ffmpeg_bin()
    out = work / "sample.mp4"
    audio = work / "voice.wav"
    if with_speech:
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.SetOutputToWaveFile('{audio}');$s.Speak('{TTS_TEXT}');$s.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                       capture_output=True)
        if not audio.exists():
            raise SystemExit("TTS 语音合成失败")
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=15",
                        "-i", str(audio), "-c:v", "libx264", "-c:a", "aac", "-shortest",
                        str(out)], check=True, capture_output=True)
    else:
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=15",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)],
                       check=True, capture_output=True)
    return out


def make_srt(work: Path) -> Path:
    p = work / "sample.en.srt"
    p.write_text(SRT_SAMPLE, encoding="utf-8")
    return p


# ------------------------------------------------------------------ 冒烟流程

async def run(args: argparse.Namespace) -> None:
    work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="subcraft-mcp-smoke-"))
    work.mkdir(parents=True, exist_ok=True)
    media = Path(args.media) if args.media else make_media(work, with_speech=args.asr)
    srt = make_srt(work)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if args.data_dir:
        env["SubCraft_DATA_DIR"] = str(args.data_dir)

    params = StdioServerParameters(command=sys.executable, args=[str(MCP_ENTRY)], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            log("initialize", f"{_field(init, 'server_info').name} / 协议 {_field(init, 'protocol_version')}")

            listing = await session.list_tools()
            log("list_tools", f"{len(listing.tools)} 个工具: {', '.join(sorted(t.name for t in listing.tools)[:6])} ...")

            st = await call(session, "subcraft_status")
            log("subcraft_status", f"ffmpeg={st['ffmpeg_ready']} cuda={st['cuda_available']} "
                             f"厂商={len(st['ai_providers'])} deepl={st['deepl_configured']}")

            info = await call(session, "subcraft_probe_media", path=str(media))
            log("subcraft_probe_media", f"{info['width']}x{info['height']} {info['duration']:.2f}s {info['video_codec']}")

            loaded = await call(session, "subcraft_load_subtitle_file", path=str(srt),
                                language="en", video_path=str(media))
            tid = loaded["track_id"]
            log("subcraft_load_subtitle_file", f"{tid} 语言={loaded['language']} 段数={loaded['segment_count']}")

            segs = await call(session, "subcraft_get_segments", track_id=tid)
            log("subcraft_get_segments", f"首段: {segs['segments'][0]}")

            edited = await call(session, "subcraft_edit_segments", track_id=tid,
                                edits=[{"index": 0, "text": "Hello world — SubCraft MCP."},
                                       {"index": 99, "text": "越界项"}])
            log("subcraft_edit_segments", f"applied={edited['applied']} invalid={edited['invalid_count']}")

            await call(session, "subcraft_set_style", track_id=tid, font_size=42,
                       primary_color="#FFE680", outline=2.5, alignment=2, margin_v=36)
            log("subcraft_set_style", "字号 42 / 颜色 #FFE680 / 底部居中")

            ass = await call(session, "subcraft_build_ass", track_ids=[tid], bilingual=False)
            log("subcraft_build_ass", f"{ass['chars']} 字符, 分辨率 {ass['width']}x{ass['height']}")

            out_dir = work / "out"
            exported = await call(session, "subcraft_export_subtitle_files", out_dir=str(out_dir),
                                  track_ids=[tid], base_name="smoke", formats=["srt", "ass"],
                                  bilingual=False)
            log("subcraft_export_subtitle_files", "\n" + "\n".join(f"      - {f}" for f in exported["files"]))

            mkv = out_dir / "smoke.soft.mkv"
            video = await call(session, "subcraft_export_video", show_progress=True, out_path=str(mkv),
                               track_ids=[tid], mode="soft", video_path=str(media))
            log("subcraft_export_video(soft)", f"{video['out_path']} {video['size_mb']}MB 耗时 {video['elapsed_sec']}s")

            jpg = out_dir / "preview.jpg"
            await call(session, "subcraft_preview_frame", time=1.0, track_ids=[tid],
                       video_path=str(media), out_path=str(jpg))
            log("subcraft_preview_frame", f"JPEG {jpg.stat().st_size // 1024}KB → {jpg}")

            saved = await call(session, "subcraft_save_project", path=str(out_dir / "smoke.json"))
            log("subcraft_save_project", f"{saved['path']} ({saved['size_kb']}KB)")

            if args.asr:
                # 异步模式：wait=false 拿 job_id，再用 subcraft_job_status 轮询
                detached = await call(session, "subcraft_transcribe", video_path=str(media),
                                      engine="local", model=args.model,
                                      language=args.source_lang or None, wait=False)
                log("subcraft_transcribe(wait=false)", f"job_id={detached['job_id']} status={detached['status']}")
                job = detached
                for _ in range(600):
                    await asyncio.sleep(0.5)
                    job = await call(session, "subcraft_job_status", job_id=detached["job_id"])
                    if job["status"] != "running":
                        break
                if job["status"] != "done":
                    raise RuntimeError(f"后台任务失败: {job.get('error')}")
                res = job["result"]
                asr_tid = res["track_id"]
                log("subcraft_job_status", f"识别完成 {asr_tid} 语言={res['language']} "
                                     f"段数={res['segment_count']} 耗时 {job['elapsed_sec']}s")
                for s in res["preview"][:3]:
                    print(f"      · [{s['start']:.2f}-{s['end']:.2f}] {s['text']}")

                # 一键流水线：识别 → 导出字幕 → 软字幕封装
                pipe = await call(session, "subcraft_generate_subtitles", show_progress=True,
                                  video_path=str(media), out_dir=str(out_dir), base_name="pipe",
                                  formats=["srt", "ass"], engine="local", whisper_model=args.model,
                                  source_lang=args.source_lang or None, export_video="soft")
                log("subcraft_generate_subtitles",
                    f"{pipe['segment_count']} 段 / 轨 {pipe['source_track_id']} "
                    f"耗时 {pipe['elapsed_sec']}s\n"
                    + "\n".join(f"      - {f}" for f in pipe["files"]))

                # 单独验证翻译工具（需已配置厂商，不重复消耗流水线额度）
                if args.target_lang:
                    if not st["ai_providers"] and not st["deepl_configured"]:
                        log("subcraft_translate", "跳过：未配置翻译厂商（在 SubCraft 客户端设置里添加）")
                    else:
                        tr = await call(session, "subcraft_translate", show_progress=True,
                                        track_id=asr_tid, target_lang=args.target_lang)
                        log("subcraft_translate", f"{tr['track_id']} → {tr['language']} "
                                            f"段数={tr['segment_count']} 对齐={tr['aligned']}")
                        bi = await call(session, "subcraft_export_subtitle_files", out_dir=str(out_dir),
                                        base_name="smoke-bilingual", formats=["ass", "srt"],
                                        primary_id=asr_tid)
                        log("双语导出", "\n" + "\n".join(f"      - {f}" for f in bi["files"]))

            cleared = await call(session, "subcraft_clear_session")
            log("subcraft_clear_session", f"清空 {cleared['cleared']} 条轨道")

            try:
                await call(session, "subcraft_get_segments", track_id=tid)
                raise AssertionError("预期 subcraft_get_segments 在清空后报错")
            except RuntimeError as e:
                log("错误回传", str(e))

    print(f"\n冒烟测试通过：{len(STEPS)} 步全部成功，产物在 {work}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SubCraft MCP 冒烟测试")
    parser.add_argument("--asr", action="store_true", help="追加真实语音识别（用 TTS 合成语音，首次会下载模型）")
    parser.add_argument("--model", default="tiny", help="Whisper 模型，默认 tiny（冒烟够用且下载快）")
    parser.add_argument("--media", help="用指定媒体文件代替自动生成的测试视频")
    parser.add_argument("--source-lang", help="识别时指定源语言码（如 en）")
    parser.add_argument("--target-lang", help="识别后追加翻译到该语言（需已配置翻译厂商）")
    parser.add_argument("--workdir", help="产物输出目录，默认系统临时目录")
    parser.add_argument("--data-dir", help="覆盖 SubCraft_DATA_DIR（隔离真实配置）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
