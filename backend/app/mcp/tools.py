"""MCP 工具实现：把 SubCraft 的识别 / 翻译 / 编辑 / 导出能力暴露给 AI 客户端。

约定：
- 工具名 = 函数名（统一 `subcraft_` 前缀，避免与其他 MCP 服务重名），描述取函数 docstring
- 预期内的失败一律抛 `ToolError`（普通异常会被 SDK 收敛成无细节的 "Error executing tool"）
- 长任务支持 `wait=False`：立即返回 `job_id`，再用 `subcraft_job_status` 轮询进度
- 字幕段统一为 `{index, start, end, text}`，index 是轨道内 0 基序号，时间单位秒
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..config import data_dir, store
from ..models import LANGUAGES, Segment, SubtitleStyle
from ..routers import export as export_router
from ..services import ffmpeg_tool, fonts, subtitle_parser, translator
from .compat import Context, Image, ToolError
from .state import (
    DEFAULT_PAGE_SIZE,
    JOBS,
    MAX_SEGMENTS_PER_CALL,
    MAX_TEXT_CHARS,
    SESSION,
    SessionTrack,
    translation_style,
)

TOOLS: list[Callable[..., Any]] = []
ProgressCb = Callable[[float, str], None]

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# mcp>=2 的 report_progress 支持 message 参数，1.x 只有 (progress, total)
try:
    _PROGRESS_TAKES_MESSAGE = "message" in inspect.signature(Context.report_progress).parameters
except (TypeError, ValueError):       # pragma: no cover - 拿不到签名时保守处理
    _PROGRESS_TAKES_MESSAGE = False
# 只剩这些字符的字幕段视为「空段」（识别常见产物：音乐符、破折号、空白等）
_FILLER_CHARS = " \t\r\n\u3000-\u2014\u2013.\u00b7\u3001,\uff0c!\uff01?\uff1f\"'\u2019\u2018\u201c\u201d()\uff08\uff09[]\u3010\u3011~\uff5e*\u2026"


def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """把函数登记为 MCP 工具（由 server.py 批量注册）。"""
    TOOLS.append(fn)
    return fn


# ---------------------------------------------------------------- 基础工具函数

def _fail(msg: str) -> Any:
    raise ToolError(msg)


def _existing(path: str, kind: str = "文件") -> Path:
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.exists():
        _fail(f"{kind}不存在: {p}")
    return p.resolve()


def _ids_text() -> str:
    ids = SESSION.ids()
    return "、".join(ids) if ids else "（无，先用 subcraft_transcribe 或 subcraft_load_subtitle_file 建轨）"


def _track(track_id: str) -> SessionTrack:
    st = SESSION.get(track_id)
    if st is None:
        _fail(f"轨道不存在: {track_id}；当前会话轨道: {_ids_text()}")
    return st  # type: ignore[return-value]


def _tracks(track_ids: list[str] | None) -> list[SessionTrack]:
    items = SESSION.resolve(track_ids)
    if not items:
        _fail(f"没有可用的字幕轨: {_ids_text()}")
    missing = [i for i in (track_ids or []) if i not in {x.id for x in items}]
    if missing:
        _fail(f"轨道不存在: {'、'.join(missing)}；当前会话轨道: {_ids_text()}")
    return items


def _pick(items: list[SessionTrack], track_id: str | None, field: str) -> str | None:
    """校验并归一轨道 id 参数（primary_id / burn_track_id）。"""
    if track_id is None:
        return None
    if track_id not in {x.id for x in items}:
        _fail(f"{field} 不在给定轨道中: {track_id}（可选: {'、'.join(x.id for x in items)}）")
    return track_id


def _seg_view(index: int, s: Segment) -> dict[str, Any]:
    return {
        "index": index,
        "start": round(s.start, 3),
        "end": round(s.end, 3),
        "duration": round(max(s.end - s.start, 0.0), 3),
        "text": s.text,
    }


def _video_of(items: list[SessionTrack]) -> str | None:
    for st in items:
        if st.video_path:
            return st.video_path
    return None


def _play_size(items: list[SessionTrack], width: int, height: int) -> tuple[int, int]:
    """ASS 画布尺寸：显式给定优先，其次探测源视频，最后回退 1920x1080。"""
    if width > 0 and height > 0:
        return int(width), int(height)
    vp = _video_of(items)
    if vp and Path(vp).exists():
        try:
            info = ffmpeg_tool.probe(vp)
            if info.width and info.height:
                return info.width, info.height
        except Exception:
            pass
    return 1920, 1080


def _guess_language(path: Path) -> str | None:
    """从文件名猜语言码：`movie.zh.srt` / `EP01_en.ass` → zh / en。"""
    for tok in re.split(r"[._\-\s()+]+", path.stem.lower()):
        if tok in LANGUAGES and tok != "auto":
            return tok
    return None


def _guess_language_from_segments(segments: list[Segment]) -> str | None:
    """粗略判断字幕文本语言（无语言元信息时用）。"""
    text = "".join(s.text for s in segments[:50])
    if not text:
        return None
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return None


def _scaled(cb: ProgressCb, lo: float, hi: float, prefix: str = "") -> ProgressCb:
    """把子任务进度 [0,1] 映射到总进度 [lo,hi]。"""
    def inner(p: float, msg: str) -> None:
        cb(lo + (hi - lo) * min(max(p, 0.0), 1.0), f"{prefix}{msg}")
    return inner


def _ensure_ffmpeg(cb: ProgressCb | None = None) -> None:
    """确保 ffmpeg 就绪（Windows 下缺失时自动下载）；必须在任务线程里调用，不能阻塞事件循环。"""
    if not ffmpeg_tool.find_ffmpeg():
        ffmpeg_tool.ensure_ffmpeg(cb)


async def _report(ctx: Context | None, progress: float, message: str) -> None:
    """上报进度（带文字说明）；客户端未传 progressToken 或 SDK 不支持 message 时静默降级。

    注：MCP 的 logging 能力已被 SEP-2577 废弃，因此进度文字统一走 report_progress 的 message 字段。
    """
    if ctx is None:
        return
    value = round(progress * 100, 1)
    try:
        if _PROGRESS_TAKES_MESSAGE:
            await ctx.report_progress(value, 100.0, message)
        else:
            await ctx.report_progress(value, 100.0)
    except Exception:
        pass


async def _run_job(ctx: Context | None, label: str, fn: Callable[[ProgressCb], Any],
                   wait: bool = True) -> dict[str, Any]:
    """提交长任务到线程池；wait=True 时轮询并把进度转发给 MCP 客户端。"""
    job_id = JOBS.submit(fn, label)
    if not wait:
        return {
            "job_id": job_id, "status": "running", "label": label, "progress": 0.0,
            "message": f"{label}已在后台启动",
            "hint": "用 subcraft_job_status(job_id) 查询进度与结果；结果中的 track_id 可直接用于后续工具",
        }
    last = -1.0
    while True:
        job = JOBS.get(job_id)
        if job is None:
            _fail(f"任务已丢失: {job_id}")
        if job["progress"] != last:
            last = job["progress"]
            await _report(ctx, last, f"{label} {int(last * 100)}% {job['message']}")
        if job["status"] == "done":
            result = job.get("result")
            out = dict(result) if isinstance(result, dict) else {"result": result}
            out.update(job_id=job_id, status="done", elapsed_sec=job["elapsed_sec"])
            return out
        if job["status"] == "error":
            _fail(f"{label}失败（job_id={job_id}）: {job['error']}")
        await asyncio.sleep(0.4)


# ---------------------------------------------------------------- 环境与信息

@tool
def subcraft_status() -> dict:
    """SubCraft 字幕生成器自检：ffmpeg / CUDA 是否就绪、已配置的翻译厂商与模型、可用 Whisper 模型、语言码表、当前会话轨道。

    开始任何字幕工作前建议先调用一次，确认翻译厂商已配置（api_key_set=true）且 ffmpeg_ready=true。
    翻译厂商的 API Key 在 SubCraft 桌面客户端「设置」里配置，本服务直接复用同一份本地配置。
    """
    from ..routers.config import _masked
    from ..services import asr

    cfg = _masked(store.all())
    found = ffmpeg_tool.find_ffmpeg()
    return {
        "app": "SubCraft MCP",
        "ffmpeg": found[0] if found else None,
        "ffmpeg_ready": found is not None,
        "cuda_available": asr.is_cuda_available(),
        "data_dir": str(data_dir()),
        "whisper": {
            "model": cfg.get("whisper_model"),
            "device": cfg.get("whisper_device"),
            "models": list(asr.WHISPER_MODELS),
        },
        "ai_providers": [
            {"id": p.get("id"), "name": p.get("name"), "model": p.get("model"),
             "base_url": p.get("base_url"), "api_key_set": p.get("api_key_set")}
            for p in cfg.get("ai_providers", []) or []
        ],
        "deepl_configured": bool(cfg.get("deepl_api_key_set")),
        "translate": {"batch_size": cfg.get("translate_batch_size"),
                      "concurrency": cfg.get("translate_concurrency")},
        "languages": LANGUAGES,
        "session_tracks": SESSION.ids(),
        "supported_subtitle_files": list(subtitle_parser.SUPPORTED_SUFFIXES),
    }


@tool
def subcraft_probe_media(path: str | None = None, video_path: str | None = None) -> dict:
    """探测音视频文件：时长（秒）、分辨率、视频/音频编码、文件大小。

    Args:
        path: 媒体文件绝对路径
        video_path: 同 path（与其他工具参数名保持一致的别名，二选一）
    """
    path = path or video_path
    if not path:
        _fail("请提供 path（媒体文件绝对路径）")
    p = _existing(path, "媒体文件")
    try:
        info = ffmpeg_tool.probe(str(p))
    except Exception as e:
        _fail(f"探测失败: {e}")
    return info.model_dump()


@tool
def subcraft_list_fonts(keyword: str = "", limit: int = 60) -> dict:
    """列出系统已安装字体名，供 subcraft_set_style 的 font_name 使用。

    Args:
        keyword: 过滤关键字（不区分大小写），如 "YaHei"、"Noto Sans CJK"
        limit: 最多返回条数
    """
    names = sorted(fonts.list_fonts())
    if keyword:
        kw = keyword.lower()
        names = [n for n in names if kw in n.lower()]
    limit = max(1, min(int(limit), 500))
    return {"total": len(names), "returned": min(len(names), limit), "fonts": names[:limit]}


# ---------------------------------------------------------------- 识别 / 翻译 / 导入

@tool
async def subcraft_transcribe(ctx: Context, video_path: str, engine: str = "local",
                        model: str | None = None, language: str | None = None,
                        label: str | None = None, wait: bool = True) -> dict:
    """语音识别（ASR）：把视频/音频里的人声转成带时间轴的字幕轨。

    Args:
        video_path: 媒体文件绝对路径（mp4/mkv/mov/avi/webm/ts/flv/mp3/wav 等）
        engine: local=本地 faster-whisper（离线、可 GPU 加速）；openai=OpenAI 兼容云端 Whisper API
        model: Whisper 模型名 tiny/base/small/medium/large-v3-turbo/large-v3；留空用客户端默认配置
        language: 指定源语言码（zh/en/ja/ko...）可提升准确率；留空或 auto=自动检测
        label: 轨道显示名，留空按语言自动生成
        wait: 长视频建议 False，立即拿 job_id 后用 subcraft_job_status 轮询

    返回 track_id（后续翻译/导出都用它）、检测到的语言、段数与前 10 段预览。
    """
    p = _existing(video_path, "媒体文件")
    try:
        info = ffmpeg_tool.probe(str(p))
    except Exception as e:
        _fail(f"无法读取媒体文件: {e}")
    eng = "openai" if str(engine).lower() in ("openai", "cloud", "api") else "local"
    lang = None if language in (None, "", "auto") else str(language)
    if eng == "local" and model and model not in ("tiny", "base", "small", "medium",
                                                 "large-v3-turbo", "large-v3"):
        _fail(f"未知的 Whisper 模型: {model}（可选 tiny/base/small/medium/large-v3-turbo/large-v3）")

    def job(cb: ProgressCb) -> dict:
        from ..services import asr

        _ensure_ffmpeg(_scaled(cb, 0.0, 0.02, "[准备] "))
        segments, detected = asr.transcribe(str(p), info.duration, eng, model, lang, None, None, cb)
        if not segments:
            raise RuntimeError("未识别到语音内容（可换更大的 Whisper 模型，或显式指定 language）")
        st = SESSION.create(
            segments, language=detected or "und", role="source", label=label or "",
            video_path=str(p), duration=info.duration, origin="transcribe",
        )
        return {
            "track_id": st.id, "language": st.track.language, "segment_count": len(segments),
            "duration": round(info.duration, 2), "video_path": str(p),
            "preview": [_seg_view(i, s) for i, s in enumerate(segments[:10])],
        }

    out = await _run_job(ctx, "语音识别", job, wait)
    if out.get("track_id"):
        out["next_steps"] = [
            "subcraft_get_segments 分页查看全部字幕",
            "subcraft_translate 翻译成目标语言",
            "subcraft_export_subtitle_files 导出 srt/ass",
        ]
    return out


@tool
async def subcraft_translate(ctx: Context, track_id: str, target_lang: str, provider: str = "ai",
                       provider_id: str | None = None, model: str | None = None,
                       api_key: str | None = None, base_url: str | None = None,
                       wait: bool = True) -> dict:
    """把一条字幕轨翻译成目标语言，生成新的翻译轨（时间轴与段数严格对齐）。

    Args:
        track_id: 源轨道 id（来自 subcraft_transcribe / subcraft_load_subtitle_file）
        target_lang: 目标语言码，如 zh/en/ja/ko/fr/de/es/ru（完整表见 subcraft_status）
        provider: ai=已配置的 OpenAI 兼容厂商（DeepSeek/Kimi/Qwen/GLM/OpenRouter 等）；deepl=DeepL
        provider_id: 指定厂商配置 id（留空用第一个）；id 列表见 subcraft_status
        model: 覆盖厂商默认模型名
        api_key/base_url: 临时覆盖凭据（一般留空，复用客户端已保存的配置）
        wait: False 时立即返回 job_id

    翻译轨会自动套用副语言样式（字号 0.7 倍、淡黄色），可用 subcraft_set_style 调整。
    """
    st = _track(track_id)
    if not st.track.segments:
        _fail(f"轨道 {track_id} 没有字幕段，无法翻译")
    if target_lang not in LANGUAGES or target_lang == "auto":
        _fail(f"无效的目标语言码: {target_lang}（可选: {', '.join(k for k in LANGUAGES if k != 'auto')}）")
    prov = "deepl" if str(provider).lower() == "deepl" else "openai"
    source_lang = st.track.language if st.track.language not in ("", "und") else "auto"
    batch = int(store.get("translate_batch_size", 25) or 25)
    conc = int(store.get("translate_concurrency", 4) or 4)

    def job(cb: ProgressCb) -> dict:
        translated = translator.translate_segments(
            st.track.segments, source_lang, target_lang, prov, provider_id,
            api_key, base_url, model, batch_size=batch, concurrency=conc, progress_cb=cb,
        )
        new = SESSION.create(
            translated, language=target_lang, role="translation",
            style=translation_style(st.track.style), video_path=st.video_path,
            duration=st.duration, origin="translate",
        )
        return {
            "track_id": new.id, "source_track_id": st.id, "language": target_lang,
            "segment_count": len(translated), "aligned": len(translated) == len(st.track.segments),
            "preview": [_seg_view(i, s) for i, s in enumerate(translated[:10])],
        }

    out = await _run_job(ctx, "字幕翻译", job, wait)
    if out.get("track_id"):
        out["next_steps"] = [
            "subcraft_export_subtitle_files(bilingual=true) 导出双语字幕",
            "subcraft_export_video(mode='hard') 压制硬字幕成片",
            "subcraft_preview_frame 看一帧真实烧录效果",
        ]
    return out


@tool
def subcraft_load_subtitle_file(path: str, language: str | None = None, label: str | None = None,
                          role: str = "source", video_path: str | None = None) -> dict:
    """导入已有字幕文件（.srt / .vtt / .ass / .ssa）为一条会话轨道。

    Args:
        path: 字幕文件绝对路径
        language: 语言码；留空时依次从文件名、文本内容推断
        label: 轨道显示名
        role: source=源语言轨 / translation=翻译轨
        video_path: 关联的视频路径（用于导出时自动取分辨率、压制成片）

    导入后即可用 subcraft_translate 翻译、subcraft_edit_segments 校对、subcraft_export_* 重新导出。
    """
    p = _existing(path, "字幕文件")
    try:
        segments = subtitle_parser.parse_file(p)
    except ValueError as e:
        _fail(str(e))
    lang = language or _guess_language(p) or _guess_language_from_segments(segments) or "und"
    video = str(_existing(video_path, "媒体文件")) if video_path else None
    duration = 0.0
    if video:
        try:
            duration = ffmpeg_tool.probe(video).duration
        except Exception:
            duration = segments[-1].end if segments else 0.0
    st = SESSION.create(
        segments, language=lang, role=role, label=label or "", video_path=video,
        duration=duration or (segments[-1].end if segments else 0.0), origin="file",
    )
    return {
        "track_id": st.id, "file": str(p), "language": lang, "segment_count": len(segments),
        "preview": [_seg_view(i, s) for i, s in enumerate(segments[:5])],
    }


@tool
async def subcraft_generate_subtitles(ctx: Context, video_path: str, target_lang: str | None = None,
                                out_dir: str | None = None, base_name: str | None = None,
                                formats: list[str] | None = None, engine: str = "local",
                                whisper_model: str | None = None, source_lang: str | None = None,
                                provider: str = "ai", provider_id: str | None = None,
                                bilingual: bool = True, export_video: str | None = None,
                                wait: bool = True) -> dict:
    """一条龙流水线：识别视频语音 → 可选翻译 → 导出字幕文件（可选压制成片）。

    Args:
        video_path: 媒体文件绝对路径
        target_lang: 目标语言码；留空则只做识别不翻译
        out_dir: 输出目录，默认与视频同目录
        base_name: 输出文件名前缀，默认取视频文件名
        formats: 字幕格式数组，可选 "srt" / "ass"，默认两者都导
        engine / whisper_model / source_lang: 识别参数，含义同 subcraft_transcribe
        provider / provider_id: 翻译厂商，含义同 subcraft_translate
        bilingual: 是否额外导出双语合并字幕（需要 target_lang）
        export_video: "soft"=封装软字幕 MKV（无损、秒级）；"hard"=烧录硬字幕 MP4（重编码、较慢）；留空=不出成片
        wait: False 时立即返回 job_id

    返回创建的所有 track_id、写出的文件列表与统计信息。
    """
    p = _existing(video_path, "媒体文件")
    out_root = Path(out_dir).expanduser() if out_dir else p.parent
    out_root.mkdir(parents=True, exist_ok=True)
    base = re.sub(r'[\\/:*?"<>|]', "_", base_name or p.stem)
    fmts = [f.lower() for f in (formats or ["srt", "ass"])]
    bad = [f for f in fmts if f not in ("srt", "ass")]
    if bad:
        _fail(f"不支持的字幕格式: {'、'.join(bad)}（仅 srt / ass）")
    mode = export_video.lower() if export_video else None
    if mode and mode not in ("soft", "hard"):
        _fail(f"export_video 只能是 'soft' / 'hard' / 留空，收到: {export_video}")
    if target_lang is not None and (target_lang not in LANGUAGES or target_lang == "auto"):
        _fail(f"无效的目标语言码: {target_lang}")

    def job(cb: ProgressCb) -> dict:
        from ..services import asr

        _ensure_ffmpeg(_scaled(cb, 0.0, 0.03, "[准备] "))
        info = ffmpeg_tool.probe(str(p))
        w, h = (info.width or 1920), (info.height or 1080)
        lang = None if source_lang in (None, "", "auto") else source_lang
        segments, detected = asr.transcribe(
            str(p), info.duration, "openai" if str(engine).lower() in ("openai", "cloud") else "local",
            whisper_model, lang, None, None, _scaled(cb, 0.0, 0.45, "[识别] "),
        )
        if not segments:
            raise RuntimeError("未识别到语音内容")
        src = SESSION.create(segments, language=detected or "und", role="source",
                             video_path=str(p), duration=info.duration, origin="transcribe")
        items = [src]
        translated_id = None
        if target_lang:
            translated = translator.translate_segments(
                segments, src.track.language if src.track.language != "und" else "auto", target_lang,
                "deepl" if str(provider or "ai").lower() == "deepl" else "openai", provider_id,
                None, None, None,
                batch_size=int(store.get("translate_batch_size", 25) or 25),
                concurrency=int(store.get("translate_concurrency", 4) or 4),
                progress_cb=_scaled(cb, 0.45, 0.8, "[翻译] "),
            )
            trn = SESSION.create(translated, language=target_lang, role="translation",
                                 style=translation_style(src.track.style), video_path=str(p),
                                 duration=info.duration, origin="translate")
            items.append(trn)
            translated_id = trn.id

        cb(0.82, "[导出] 写字幕文件...")
        res = export_router.export_subtitles(export_router.SubtitleExportRequest(
            tracks=[x.track for x in items], bilingual=bilingual and translated_id is not None,
            primary_id=src.id, width=w, height=h,
            out_dir=str(out_root), base_name=base, formats=fmts,
        ))
        files = list(res.get("files", []))

        video_out = None
        if mode:
            video_out = str(out_root / f"{base}.{'hard.mp4' if mode == 'hard' else 'soft.mkv'}")
            req = export_router.VideoExportRequest(
                tracks=[x.track for x in items], bilingual=bilingual and translated_id is not None,
                primary_id=src.id, width=w, height=h, video_path=str(p),
                out_path=video_out, mode=mode,
            )
            if mode == "soft":
                cb(0.88, "[压制] 封装软字幕...")
                subs = export_router.build_soft_sub_files(req, Path(video_out).parent, Path(video_out).stem)
                ffmpeg_tool.mux_subtitles(str(p), subs, Path(video_out), default_index=0)
                for f, _, _ in subs:
                    f.unlink(missing_ok=True)
            else:
                sub = export_router.write_burn_ass(
                    req, "burn", Path(video_out).stem, None, Path(video_out).parent)
                fonts_dir = export_router.fonts_dir_for(req)
                try:
                    ffmpeg_tool.burn_subtitles(
                        str(p), sub, Path(video_out), _scaled(cb, 0.88, 0.99, "[压制] "), fonts_dir)
                finally:
                    sub.unlink(missing_ok=True)
            files.append(video_out)
        cb(0.99, "完成")
        return {
            "source_track_id": src.id, "translation_track_id": translated_id,
            "language": src.track.language, "segment_count": len(segments),
            "duration": round(info.duration, 2), "resolution": [w, h],
            "files": files, "out_dir": str(out_root), "video_out": video_out,
        }

    out = await _run_job(ctx, "字幕生成流水线", job, wait)
    if out.get("files"):
        out["next_steps"] = ["subcraft_get_segments 校对文本", "subcraft_preview_frame 检查烧录效果",
                             "subcraft_export_video 单独重新压制"]
    return out


# ---------------------------------------------------------------- 查看与编辑

@tool
def subcraft_list_tracks() -> dict:
    """列出当前会话里的所有字幕轨（id、语言、角色、段数、样式要点、关联视频）。

    其他工具的 track_id / track_ids / primary_id 都取自这里。
    """
    items = SESSION.all()
    return {
        "count": len(items),
        "tracks": [st.summary() for st in items],
        "running_jobs": [j for j in JOBS.recent(5) if j["status"] == "running"],
    }


@tool
def subcraft_get_segments(track_id: str, offset: int = 0, limit: int = DEFAULT_PAGE_SIZE,
                    keyword: str | None = None) -> dict:
    """分页读取字幕段（校对/审阅字幕内容用）。

    Args:
        track_id: 轨道 id
        offset: 起始序号（0 基）
        limit: 返回条数上限，最大 200
        keyword: 只返回文本包含该关键字的段（跨全轨道搜索，忽略 offset/limit 之外的分页语义）

    返回的 index 即 subcraft_edit_segments / subcraft_delete_segments 使用的序号。
    """
    st = _track(track_id)
    segs = st.track.segments
    limit = max(1, min(int(limit), MAX_SEGMENTS_PER_CALL))
    offset = max(0, int(offset))
    if keyword:
        kw = keyword.lower()
        hits = [_seg_view(i, s) for i, s in enumerate(segs) if kw in s.text.lower()]
        return {
            "track_id": track_id, "keyword": keyword, "total_matches": len(hits),
            "returned": min(len(hits), limit), "segments": hits[offset: offset + limit],
            "track_segment_count": len(segs),
        }
    page = [_seg_view(i, segs[i]) for i in range(offset, min(offset + limit, len(segs)))]
    return {
        "track_id": track_id, "language": st.track.language, "total": len(segs),
        "offset": offset, "limit": limit, "returned": len(page), "segments": page,
        "next_offset": offset + len(page) if offset + len(page) < len(segs) else None,
    }


@tool
def subcraft_edit_segments(track_id: str, edits: list[dict]) -> dict:
    """批量修改字幕段：改文本、改起止时间（一次调用可改多段，适合整轨校对）。

    Args:
        track_id: 轨道 id
        edits: 修改项数组，每项形如 {"index": 12, "text": "新文本", "start": 30.5, "end": 33.0}；
               index 必填（0 基，取自 subcraft_get_segments），text/start/end 只改给出的字段，时间单位秒。
               文本内可用 \\n 表示字幕换行。

    返回成功条数、被忽略的非法项与轨道摘要。
    """
    st = _track(track_id)
    segs = st.track.segments
    if not isinstance(edits, list) or not edits:
        _fail("edits 不能为空，示例: [{'index': 0, 'text': '你好'}]")
    applied, invalid = 0, []
    for raw in edits:
        if not isinstance(raw, dict) or "index" not in raw:
            invalid.append({"edit": raw, "reason": "缺少 index"})
            continue
        try:
            idx = int(raw["index"])
        except (TypeError, ValueError):
            invalid.append({"edit": raw, "reason": "index 不是整数"})
            continue
        if not (0 <= idx < len(segs)):
            invalid.append({"index": idx, "reason": f"越界（0-{len(segs) - 1}）"})
            continue
        seg = segs[idx]
        start = float(raw["start"]) if raw.get("start") is not None else seg.start
        end = float(raw["end"]) if raw.get("end") is not None else seg.end
        if end <= start:
            invalid.append({"index": idx, "reason": f"结束时间 {end} 不晚于开始时间 {start}"})
            continue
        if "text" in raw and raw["text"] is not None:
            seg.text = str(raw["text"]).replace("\\n", "\n").strip()
        seg.start, seg.end = round(start, 3), round(end, 3)
        applied += 1
    segs.sort(key=lambda s: (s.start, s.end))
    return {"track_id": track_id, "applied": applied, "invalid": invalid[:20],
            "invalid_count": len(invalid), "track": st.summary(), "note": "已按时间重新排序"}


@tool
def subcraft_delete_segments(track_id: str, indexes: list[int]) -> dict:
    """删除指定序号的字幕段（如广告口播、误识别的噪声段）。

    Args:
        track_id: 轨道 id
        indexes: 要删除的 0 基序号数组（取自 subcraft_get_segments）；删除后序号会重排
    """
    st = _track(track_id)
    drop = {int(i) for i in indexes if isinstance(i, (int, float)) or str(i).lstrip("-").isdigit()}
    before = len(st.track.segments)
    keep = [s for i, s in enumerate(st.track.segments) if i not in drop]
    if len(keep) == before:
        _fail(f"没有匹配的序号可删除（轨道共 {before} 段）")
    st.track.segments = keep
    return {"track_id": track_id, "deleted": before - len(keep), "remaining": len(keep),
            "track": st.summary()}


@tool
def subcraft_clean_empty_segments(track_id: str | None = None) -> dict:
    """清理空白字幕段（文本为空或只有空白/标点）。

    Args:
        track_id: 指定轨道；留空则清理会话内全部轨道
    """
    items = _tracks([track_id] if track_id else None)
    cleaned = {}
    for st in items:
        before = len(st.track.segments)
        st.track.segments = [s for s in st.track.segments if s.text.strip(_FILLER_CHARS)]
        if before - len(st.track.segments):
            cleaned[st.id] = before - len(st.track.segments)
    return {"cleaned": cleaned, "total_removed": sum(cleaned.values()),
            "tracks": [st.summary() for st in items]}


@tool
def subcraft_set_style(track_id: str, font_name: str | None = None, font_size: int | None = None,
                 primary_color: str | None = None, outline_color: str | None = None,
                 back_color: str | None = None, bold: bool | None = None,
                 italic: bool | None = None, outline: float | None = None,
                 shadow: float | None = None, alignment: int | None = None,
                 margin_v: int | None = None, margin_l: int | None = None,
                 margin_r: int | None = None, pos_x: float | None = None,
                 pos_y: float | None = None, clear_pos: bool = False,
                 reset: bool = False) -> dict:
    """设置某条轨道的字幕样式（字体、字号、颜色、描边、阴影、位置）。

    Args:
        track_id: 轨道 id
        font_name: 字体名，需系统已安装（用 subcraft_list_fonts 确认）
        font_size: 字号（像素，8-200）
        primary_color/outline_color/back_color: 文字/描边/阴影颜色，格式 #RRGGBB
        bold/italic: 粗体、斜体
        outline: 描边粗细（0-10）；shadow: 阴影距离（0-10）
        alignment: ASS 九宫格对齐 1-9（1左下 2下中 3右下 4左中 7左上 8上中 9右上），默认 2
        margin_v/margin_l/margin_r: 垂直/左/右边距（像素）
        pos_x/pos_y: 绝对定位坐标（像素，原点为画面左上角）；设置后忽略 alignment/margin
        clear_pos: 清除绝对定位，回到 alignment + margin 模式
        reset: 恢复该轨道默认样式（其余参数忽略）

    双语字幕建议：主语言 alignment=2（底部居中），翻译轨 alignment=8（顶部居中）或调小 margin_v 叠放。
    """
    st = _track(track_id)
    style = st.track.style
    if reset:
        st.track.style = SubtitleStyle()
        return {"track_id": track_id, "style": st.summary()["style"], "reset": True}

    values: dict[str, Any] = {}
    for name, val in (
        ("font_name", font_name), ("font_size", font_size), ("primary_color", primary_color),
        ("outline_color", outline_color), ("back_color", back_color), ("bold", bold),
        ("italic", italic), ("outline", outline), ("shadow", shadow), ("alignment", alignment),
        ("margin_v", margin_v), ("margin_l", margin_l), ("margin_r", margin_r),
        ("pos_x", pos_x), ("pos_y", pos_y),
    ):
        if val is not None:
            values[name] = val
    if clear_pos:
        values.update(pos_x=None, pos_y=None)

    warnings: list[str] = []
    for key in ("primary_color", "outline_color", "back_color"):
        v = values.get(key)
        if isinstance(v, str) and not _COLOR_RE.match(v):
            _fail(f"{key} 颜色格式应为 #RRGGBB，收到: {v}")
    if "font_size" in values and not 8 <= int(values["font_size"]) <= 200:
        _fail(f"font_size 应在 8-200 之间，收到: {values['font_size']}")
    if "alignment" in values and not 1 <= int(values["alignment"]) <= 9:
        _fail(f"alignment 应在 1-9 之间（ASS 九宫格），收到: {values['alignment']}")
    for key in ("outline", "shadow"):
        if key in values and not 0 <= float(values[key]) <= 10:
            _fail(f"{key} 应在 0-10 之间，收到: {values[key]}")
    if "font_name" in values and not fonts.font_file(values["font_name"]):
        warnings.append(f"系统未找到字体「{values['font_name']}」，渲染时会回退默认字体（用 subcraft_list_fonts 查询）")
    if not values:
        _fail("没有要修改的样式字段")

    st.track.style = style.model_copy(update=values)
    return {"track_id": track_id, "style": st.summary()["style"], "applied": sorted(values),
            "warnings": warnings}


# ---------------------------------------------------------------- 导出与预览

@tool
def subcraft_build_ass(track_ids: list[str] | None = None, bilingual: bool = True,
                 primary_id: str | None = None, width: int = 0, height: int = 0,
                 max_chars: int = MAX_TEXT_CHARS) -> dict:
    """生成 ASS 字幕源码文本（不落盘），用于检查样式与双语排版是否符合预期。

    Args:
        track_ids: 参与的轨道；留空=会话内全部轨道
        bilingual: 是否把主/副语言合并到同一 Dialogue（行内覆盖实现双字体）
        primary_id: 主语言轨道 id（双语时决定谁在上）
        width/height: ASS 画布尺寸；0=自动（探测关联视频，否则 1920x1080）
        max_chars: 返回文本最大长度，超出会截断
    """
    items = _tracks(track_ids)
    w, h = _play_size(items, width, height)
    ass = export_router.preview_ass(export_router.PreviewRequest(
        tracks=[x.track for x in items], bilingual=bilingual and len(items) >= 2,
        primary_id=_pick(items, primary_id, "primary_id"), width=w, height=h,
    ))["ass"]
    truncated = len(ass) > max_chars
    return {"width": w, "height": h, "chars": len(ass), "truncated": truncated,
            "ass": ass[:max_chars] + ("\n... (已截断)" if truncated else "")}


@tool
def subcraft_export_subtitle_files(out_dir: str, track_ids: list[str] | None = None,
                             base_name: str | None = None, formats: list[str] | None = None,
                             bilingual: bool = True, primary_id: str | None = None,
                             width: int = 0, height: int = 0) -> dict:
    """导出字幕文件到磁盘：每条轨道一个单语文件，双语时额外导出合并文件。

    Args:
        out_dir: 输出目录（不存在会自动创建）
        track_ids: 要导出的轨道；留空=会话内全部
        base_name: 文件名前缀，默认 "subtitle"；最终形如 `<base>.zh.srt` / `<base>.bilingual.ass`
        formats: ["srt", "ass"] 子集，默认两者都导
        bilingual: 是否额外导出双语合并字幕（至少两条轨道时生效）
        primary_id: 双语时的主语言轨道 id
        width/height: ASS 画布尺寸；0=自动

    返回写出的文件绝对路径列表。
    """
    items = _tracks(track_ids)
    out = Path(out_dir).expanduser()
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _fail(f"无法创建输出目录 {out}: {e}")
    fmts = [f.lower() for f in (formats or ["srt", "ass"])]
    bad = [f for f in fmts if f not in ("srt", "ass")]
    if bad:
        _fail(f"不支持的字幕格式: {'、'.join(bad)}（仅 srt / ass）")
    w, h = _play_size(items, width, height)
    res = export_router.export_subtitles(export_router.SubtitleExportRequest(
        tracks=[x.track for x in items], bilingual=bilingual,
        primary_id=_pick(items, primary_id, "primary_id"), width=w, height=h,
        out_dir=str(out), base_name=base_name or "subtitle", formats=fmts,
    ))
    files = list(res.get("files", []))
    return {"files": files, "count": len(files), "out_dir": str(out), "resolution": [w, h],
            "tracks": [x.id for x in items]}


@tool
async def subcraft_export_video(ctx: Context, out_path: str, track_ids: list[str] | None = None,
                          mode: str = "soft", video_path: str | None = None,
                          bilingual: bool = True, primary_id: str | None = None,
                          burn_track_id: str | None = None, width: int = 0, height: int = 0,
                          wait: bool = True) -> dict:
    """导出带字幕的视频：软字幕封装（无损、秒级）或硬字幕烧录（重编码、兼容性最好）。

    Args:
        out_path: 输出文件绝对路径；soft 建议 .mkv，hard 建议 .mp4
        track_ids: 参与的字幕轨；留空=会话内全部
        mode: soft=封装 ASS/SRT 软字幕轨（画质无损）；hard=用 ffmpeg 把字幕烧进画面（libx264 CRF18）
        video_path: 源视频；留空则用轨道关联的视频
        bilingual: soft 模式是否加双语轨 / hard 模式是否烧双语
        primary_id: 双语时的主语言轨道 id
        burn_track_id: hard 模式只烧某一条轨（留空=双语优先，否则主轨）
        width/height: ASS 画布尺寸；0=自动
        wait: hard 模式耗时长，可传 False 后用 subcraft_job_status 轮询
    """
    items = _tracks(track_ids)
    src = video_path or _video_of(items)
    if not src:
        _fail("缺少源视频：请传 video_path，或使用带视频关联的轨道（subcraft_transcribe 产生的轨道自带）")
    src_p = _existing(src, "媒体文件")
    out_p = Path(out_path).expanduser()
    if out_p.suffix.lower() not in (".mkv", ".mp4", ".mov", ".webm", ".ts"):
        _fail(f"输出扩展名可疑: {out_p.suffix}（soft 建议 .mkv，hard 建议 .mp4）")
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if str(out_p.resolve()) == str(src_p):
        _fail("输出路径不能与源视频相同")
    if mode.lower() not in ("soft", "hard"):
        _fail(f"mode 只能是 soft / hard，收到: {mode}")
    w, h = _play_size(items, width, height)
    req = export_router.VideoExportRequest(
        tracks=[x.track for x in items], bilingual=bilingual,
        primary_id=_pick(items, primary_id, "primary_id"), width=w, height=h,
        video_path=str(src_p), out_path=str(out_p), mode=mode.lower(),
        burn_track_id=_pick(items, burn_track_id, "burn_track_id"),
    )

    def job(cb: ProgressCb) -> dict:
        if req.mode == "soft":
            cb(0.05, "生成字幕轨...")
            subs = export_router.build_soft_sub_files(req, out_p.parent, out_p.stem)
            cb(0.3, "封装中（视频流直接复制，不重编码）...")
            ffmpeg_tool.mux_subtitles(str(src_p), subs, out_p, default_index=0)
            for f, _, _ in subs:
                f.unlink(missing_ok=True)
            cb(0.99, "完成")
        else:
            cb(0.05, "生成字幕轨...")
            sub = export_router.write_burn_ass(req, "burn", out_p.stem, req.burn_track_id, out_p.parent)
            try:
                ffmpeg_tool.burn_subtitles(
                    str(src_p), sub, out_p, _scaled(cb, 0.08, 0.98),
                    export_router.fonts_dir_for(req),
                )
            finally:
                sub.unlink(missing_ok=True)
            cb(0.99, "完成")
        size = out_p.stat().st_size if out_p.exists() else 0
        return {"out_path": str(out_p), "mode": req.mode, "size_mb": round(size / 1048576, 2),
                "tracks": [t.id for t in req.tracks]}

    return await _run_job(ctx, "视频导出", job, wait)


@tool
def subcraft_preview_frame(time: float = 0.0, track_ids: list[str] | None = None,
                     video_path: str | None = None, bilingual: bool = True,
                     primary_id: str | None = None, burn_track_id: str | None = None,
                     width: int = 0, height: int = 0, out_path: str | None = None) -> Image:
    """渲染指定时间点的真实烧录效果预览图（与硬字幕导出同一 ffmpeg 管线），用于确认字号/位置/颜色。

    Args:
        time: 预览时间点（秒）；建议取某句字幕的中间时刻
        track_ids / video_path / bilingual / primary_id / burn_track_id / width / height: 同 subcraft_export_video
        out_path: 额外把预览图保存到该路径（.jpg）；留空则只回传图片

    返回 JPEG 图片，可直接肉眼确认字幕是否越界、遮挡或过小。
    """
    items = _tracks(track_ids)
    src = video_path or _video_of(items)
    if not src:
        _fail("缺少源视频：请传 video_path")
    src_p = _existing(src, "媒体文件")
    w, h = _play_size(items, width, height)
    req = export_router.PreviewFrameRequest(
        tracks=[x.track for x in items], bilingual=bilingual,
        primary_id=_pick(items, primary_id, "primary_id"), width=w, height=h,
        video_path=str(src_p), burn_track_id=_pick(items, burn_track_id, "burn_track_id"),
        time=max(0.0, float(time)),
    )
    try:
        data_url = export_router.preview_frame(req)["image"]
    except Exception as e:
        _fail(f"预览帧渲染失败: {e}")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    if out_path:
        dst = Path(out_path).expanduser()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
    return Image(data=raw, format="jpeg")


# ---------------------------------------------------------------- 任务与会话

@tool
def subcraft_job_status(job_id: str | None = None) -> dict:
    """查询后台任务（wait=False 提交的识别/翻译/导出）的进度与结果。

    Args:
        job_id: 任务 id；留空则返回最近的任务列表
    """
    if job_id:
        job = JOBS.view(job_id, with_result=True)
        if job is None:
            _fail(f"任务不存在: {job_id}")
        return job
    recent = JOBS.recent(10)
    return {"count": len(recent), "jobs": recent}


@tool
def subcraft_save_project(path: str | None = None) -> dict:
    """把当前会话的全部轨道（含样式与来源视频）保存为 JSON 工程文件，便于下次继续。

    Args:
        path: 保存路径；留空则存到 SubCraft 数据目录下的 `mcp/project_<时间>.json`
    """
    items = SESSION.all()
    if not items:
        _fail("会话中没有轨道可保存")
    if path:
        dst = Path(path).expanduser()
    else:
        dst = data_dir() / "mcp" / f"project_{datetime.now():%Y%m%d_%H%M%S}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(SESSION.dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(dst), "tracks": [x.id for x in items],
            "size_kb": round(dst.stat().st_size / 1024, 1)}


@tool
def subcraft_load_project(path: str, replace: bool = False) -> dict:
    """载入 subcraft_save_project 保存的工程文件，恢复轨道继续编辑/导出。

    Args:
        path: 工程 JSON 路径
        replace: true=先清空当前会话再载入；false=追加（重名轨道自动换 id）
    """
    p = _existing(path, "工程文件")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"工程文件解析失败: {e}")
    if replace:
        SESSION.clear()
    try:
        ids = SESSION.load(data)
    except Exception as e:
        _fail(f"工程载入失败: {e}")
    if not ids:
        _fail("工程文件中没有轨道")
    return {"path": str(p), "loaded": ids, "tracks": [st.summary() for st in SESSION.resolve(ids)]}


@tool
def subcraft_clear_session() -> dict:
    """清空当前会话的所有字幕轨（不影响已导出到磁盘的文件）。"""
    n = SESSION.clear()
    return {"cleared": n, "tracks": []}
