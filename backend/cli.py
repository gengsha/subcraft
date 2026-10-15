"""SubCraft 字幕生成器命令行入口（CLI）。

不依赖桌面客户端、也不依赖 MCP SDK，直接复用 services 层跑通
「识别 → 翻译 → 导出字幕 / 封装视频 → 烧录预览」全链路，适合脚本化与批处理。
翻译厂商凭据复用桌面客户端本地配置（%LOCALAPPDATA%/SubCraft/config.json）。

用法示例（仓库根目录）:
  python backend/cli.py status                                        # 环境自检
  python backend/cli.py gen video.mp4 -t zh --video soft              # 一条龙：识别+翻译+导出+封装
  python backend/cli.py gen video.mp4 -t zh --primary-target          # 双语以译文（中文）为主行
  python backend/cli.py transcribe video.mp4 -o out                   # 只识别并导出字幕文件
  python backend/cli.py translate in.en.srt -t zh -o out              # 只翻译（附带双语导出）
  python backend/cli.py export -s zh.srt -s en.srt --media v.mp4 --video hard -o out
  python backend/cli.py preview -s zh.srt -s en.srt --media v.mp4 --time 12.5 -o f.jpg

约定：进度走 stderr、结果走 stdout；`--json` 输出机器可读 JSON；预期内错误退出码 2。
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, NoReturn

# 确保无论工作目录在哪都能 import app 包（与 run.py / mcp_server.py 一致的自举方式）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import store                                    # noqa: E402
from app.models import LANGUAGES, Segment, SubtitleTrack        # noqa: E402
from app.routers import export as export_router                 # noqa: E402
from app.services import asr, ffmpeg_tool, fonts, subtitle_parser, translator  # noqa: E402
from app.services.asr import _setup_cuda_dlls                   # noqa: E402

_setup_cuda_dlls()          # GPU 识别需要把 CUDA 运行库目录加入 DLL 搜索路径

ProgressCb = Callable[[float, str], None]
Result = tuple[dict[str, Any], list[str]]   # (机器可读结果, 人类可读行)


class CliError(RuntimeError):
    """预期内失败（参数/文件/管线错误），退出码 2。"""


def _fail(msg: str) -> NoReturn:
    raise CliError(msg)


# ---------------------------------------------------------------- 基础工具函数

class Progress:
    """stderr 单行刷新进度；--quiet 时静默。结果 JSON 走 stdout，互不污染。"""

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._width = 0

    def __call__(self, p: float, msg: str) -> None:
        if self.quiet:
            return
        line = f"\r[ {min(max(p, 0.0), 1.0) * 100:5.1f}% ] {msg}"
        sys.stderr.write(line + " " * max(0, self._width - len(line)))
        self._width = len(line)
        sys.stderr.flush()

    def done(self) -> None:
        if self.quiet:
            return
        sys.stderr.write("\r" + " " * self._width + "\r")
        self._width = 0
        sys.stderr.flush()


def _scaled(cb: ProgressCb, lo: float, hi: float, prefix: str = "") -> ProgressCb:
    """把子任务进度 [0,1] 映射到总进度 [lo,hi]。"""
    def inner(p: float, msg: str) -> None:
        cb(lo + (hi - lo) * min(max(p, 0.0), 1.0), f"{prefix}{msg}")
    return inner


def _ensure_ffmpeg(cb: ProgressCb) -> None:
    """确保 ffmpeg 就绪（Windows 下缺失时自动下载）。"""
    if not ffmpeg_tool.find_ffmpeg():
        ffmpeg_tool.ensure_ffmpeg(cb)


def _existing(path: str, kind: str = "文件") -> Path:
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.exists():
        _fail(f"{kind}不存在: {p}")
    return p.resolve()


def _norm_lang(lang: str | None) -> str | None:
    return None if lang in (None, "", "auto") else str(lang)


def _check_lang(lang: str, opt: str) -> str:
    if lang not in LANGUAGES or lang == "auto":
        _fail(f"{opt} 语言码无效: {lang}（可选: {', '.join(k for k in LANGUAGES if k != 'auto')}）")
    return lang


def _check_formats(formats: str) -> list[str]:
    fmts = [f.strip().lower() for f in str(formats).split(",") if f.strip()]
    bad = [f for f in fmts if f not in ("srt", "ass")]
    if bad or not fmts:
        _fail(f"--formats 只能是 srt/ass 的逗号组合，收到: {formats}")
    return fmts


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
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[가-힯]", text):
        return "ko"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return None


_seq = 0


def _next_id() -> str:
    global _seq
    _seq += 1
    return f"c{_seq}"


def _load_track(path: Path, language: str | None, role: str,
                video: str | None, duration: float) -> SubtitleTrack:
    """把字幕文件读成一条轨道；语言依次取显式指定 / 文件名 / 文本内容。"""
    try:
        segments = subtitle_parser.parse_file(path)
    except ValueError as e:
        _fail(str(e))
    if not segments:
        _fail(f"字幕文件没有可用段落: {path}")
    lang = language or _guess_language(path) or _guess_language_from_segments(segments) or "und"
    return SubtitleTrack(
        id=_next_id(), language=lang, label=LANGUAGES.get(lang, lang) or lang,
        role="translation" if role == "translation" else "source",
        segments=segments,
    )


def _play_size(media: Path | None, width: int, height: int) -> tuple[int, int]:
    """ASS 画布尺寸：显式给定优先，其次探测源视频，最后回退 1920x1080。"""
    if width > 0 and height > 0:
        return int(width), int(height)
    if media is not None and media.exists():
        try:
            info = ffmpeg_tool.probe(str(media))
            if info.width and info.height:
                return info.width, info.height
        except Exception:
            pass
    return 1920, 1080


def _apply_sub_styles(tracks: list[SubtitleTrack], primary: SubtitleTrack) -> None:
    """非主轨套副语言样式（字号 0.7 倍 + 淡黄），与桌面端 / MCP 行为一致。"""
    from app.mcp.state import translation_style

    for t in tracks:
        if t.id != primary.id:
            t.style = translation_style(primary.style)


def _seg_view(s: Segment) -> dict[str, Any]:
    return {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text}


# ---------------------------------------------------------------- 导出动作

def _export_files(tracks: list[SubtitleTrack], primary_id: str, bilingual: bool,
                  out_dir: Path, base: str, formats: list[str],
                  w: int, h: int) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = export_router.export_subtitles(export_router.SubtitleExportRequest(
        tracks=tracks, bilingual=bilingual, primary_id=primary_id, width=w, height=h,
        out_dir=str(out_dir), base_name=base, formats=formats,
    ))
    return list(res.get("files", []))


def _export_video(tracks: list[SubtitleTrack], primary_id: str, bilingual: bool,
                  media: Path, out_path: Path, mode: str, burn_index: int | None,
                  w: int, h: int, cb: ProgressCb) -> dict[str, Any]:
    if out_path.suffix.lower() not in (".mkv", ".mp4", ".mov", ".webm", ".ts"):
        _fail(f"视频输出扩展名可疑: {out_path.suffix}（soft 建议 .mkv，hard 建议 .mp4）")
    if out_path.resolve() == media:
        _fail("视频输出路径不能与源视频相同")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    burn_id = None
    if burn_index is not None:
        if not 0 <= burn_index < len(tracks):
            _fail(f"--burn 序号越界（0-{len(tracks) - 1}）: {burn_index}")
        burn_id = tracks[burn_index].id
    req = export_router.VideoExportRequest(
        tracks=tracks, bilingual=bilingual, primary_id=primary_id, width=w, height=h,
        video_path=str(media), out_path=str(out_path), mode=mode, burn_track_id=burn_id,
    )
    if mode == "soft":
        cb(0.05, "生成字幕轨...")
        subs = export_router.build_soft_sub_files(req, out_path.parent, out_path.stem)
        cb(0.3, "封装中（视频流直接复制，不重编码）...")
        ffmpeg_tool.mux_subtitles(str(media), subs, out_path, default_index=0)
        for f, _, _ in subs:
            f.unlink(missing_ok=True)
    else:
        cb(0.05, "生成字幕轨...")
        sub = export_router.write_burn_ass(req, "burn", out_path.stem, burn_id, out_path.parent)
        try:
            ffmpeg_tool.burn_subtitles(str(media), sub, out_path, _scaled(cb, 0.08, 0.98, "[压制] "),
                                       export_router.fonts_dir_for(req))
        finally:
            sub.unlink(missing_ok=True)
    cb(0.99, "完成")
    return {"out_path": str(out_path), "mode": mode,
            "size_mb": round(out_path.stat().st_size / 1048576, 2)}


def _video_out_path(args: argparse.Namespace, media: Path, out_dir: Path, base: str,
                    mode: str) -> Path:
    if getattr(args, "video_out", None):
        return Path(args.video_out).expanduser().resolve()
    return out_dir / f"{base}.{'hard.mp4' if mode == 'hard' else 'soft.mkv'}"


def _tracks_from_subs(args: argparse.Namespace, media: Path | None,
                      duration: float) -> tuple[list[SubtitleTrack], SubtitleTrack]:
    """-s 字幕文件列表 → 轨道集合；首条为主轨（--primary 可改），其余套副语言样式。"""
    tracks: list[SubtitleTrack] = []
    langs = args.lang or []
    for i, s in enumerate(args.sub):
        p = _existing(s, "字幕文件")
        tracks.append(_load_track(p, langs[i] if i < len(langs) else None,
                                  "source" if i == 0 else "translation",
                                  str(media) if media else None, duration))
    primary_index = args.primary if args.primary is not None else 0
    if not 0 <= primary_index < len(tracks):
        _fail(f"--primary 序号越界（0-{len(tracks) - 1}）: {primary_index}")
    primary = tracks[primary_index]
    _apply_sub_styles(tracks, primary)
    return tracks, primary


# ---------------------------------------------------------------- 子命令

def cmd_status(args: argparse.Namespace) -> Result:
    from app.routers.config import _masked

    cfg = _masked(store.all())
    found = ffmpeg_tool.find_ffmpeg()
    result = {
        "app": "SubCraft CLI",
        "ffmpeg": found[0] if found else None,
        "ffmpeg_ready": found is not None,
        "cuda_available": asr.is_cuda_available(),
        "whisper": {"model": cfg.get("whisper_model"), "device": cfg.get("whisper_device"),
                    "models": list(asr.WHISPER_MODELS)},
        "ai_providers": [
            {"id": p.get("id"), "name": p.get("name"), "model": p.get("model"),
             "api_key_set": p.get("api_key_set")}
            for p in cfg.get("ai_providers", []) or []
        ],
        "deepl_configured": bool(cfg.get("deepl_api_key_set")),
        "languages": LANGUAGES,
        "supported_subtitle_files": list(subtitle_parser.SUPPORTED_SUFFIXES),
    }
    lines = [
        f"ffmpeg: {result['ffmpeg'] or '未就绪（首次运行会自动下载）'}",
        f"CUDA:   {'可用' if result['cuda_available'] else '不可用（回退 CPU）'}",
        f"Whisper 默认模型: {result['whisper']['model']} / 设备 {result['whisper']['device']}",
        f"翻译厂商: {len(result['ai_providers'])} 个"
        + (f"（{', '.join(p['name'] or '' for p in result['ai_providers'])}）" if result["ai_providers"] else ""),
        f"DeepL:  {'已配置' if result['deepl_configured'] else '未配置'}",
    ]
    return result, lines


def cmd_probe(args: argparse.Namespace) -> Result:
    info = ffmpeg_tool.probe(str(_existing(args.media, "媒体文件")))
    data = info.model_dump()
    return data, [f"{info.width}x{info.height}  {info.duration:.2f}s  "
                  f"视频 {info.video_codec or '-'} / 音频 {info.audio_codec or '-'}  "
                  f"{info.size / 1048576:.1f}MB"]


def cmd_fonts(args: argparse.Namespace) -> Result:
    names = sorted(fonts.list_fonts())
    if args.keyword:
        kw = args.keyword.lower()
        names = [n for n in names if kw in n.lower()]
    shown = names[: args.limit]
    return {"total": len(names), "returned": len(shown), "fonts": shown}, \
        [f"共 {len(names)} 个匹配字体:"] + [f"  - {n}" for n in shown]


def _transcribe(args: argparse.Namespace, media: Path, cb: ProgressCb,
                lo: float, hi: float) -> tuple[SubtitleTrack, dict[str, Any]]:
    info = ffmpeg_tool.probe(str(media))
    segments, detected = asr.transcribe(
        str(media), info.duration, args.engine, args.model, _norm_lang(args.lang),
        None, None, _scaled(cb, lo, hi, "[识别] "),
    )
    if not segments:
        _fail("未识别到语音内容（可换更大的 Whisper 模型，或用 --lang 显式指定语言）")
    track = SubtitleTrack(
        id=_next_id(), language=detected or "und",
        label=LANGUAGES.get(detected or "", "") or (detected or "und"),
        role="source", segments=segments,
    )
    meta = {"language": track.language, "segment_count": len(segments),
            "duration": round(info.duration, 2), "info": info,
            "preview": [_seg_view(s) for s in segments[:5]]}
    return track, meta


def _read_glossary(args: argparse.Namespace) -> str | None:
    path = getattr(args, "glossary", None)
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        _fail(f"术语表文件不存在: {path}")
    return p.read_text(encoding="utf-8-sig")


def _translate(args: argparse.Namespace, src: SubtitleTrack, cb: ProgressCb,
               lo: float, hi: float) -> SubtitleTrack:
    from app.mcp.state import translation_style

    target = _check_lang(args.target, "--target")
    translated = translator.translate_segments(
        src.segments, src.language if src.language not in ("", "und") else "auto", target,
        "deepl" if str(args.provider).lower() == "deepl" else "openai", args.provider_id,
        None, None, args.model,
        batch_size=int(store.get("translate_batch_size", 25) or 25),
        concurrency=int(store.get("translate_concurrency", 4) or 4),
        progress_cb=_scaled(cb, lo, hi, "[翻译] "),
        glossary=_read_glossary(args),
    )
    if len(translated) != len(src.segments):
        _fail(f"翻译段数不对齐: 源 {len(src.segments)} / 译文 {len(translated)}")
    return SubtitleTrack(
        id=_next_id(), language=target, label=LANGUAGES.get(target, target),
        role="translation", segments=translated, style=translation_style(src.style),
    )


def _finish_export(args: argparse.Namespace, tracks: list[SubtitleTrack], primary_id: str,
                   bilingual: bool, media: Path | None, base: str, cb: ProgressCb,
                   extra: dict[str, Any]) -> Result:
    out_dir = Path(args.out).expanduser().resolve() if args.out else \
        (media.parent if media else Path.cwd())
    w, h = _play_size(media, args.width, args.height)
    cb(0.82, "[导出] 写字幕文件...")
    files = _export_files(tracks, primary_id, bilingual, out_dir, base, args.formats, w, h)
    video_out = None
    if args.video:
        if media is None:
            _fail("封装/压制视频需要 --media 指定源视频")
        video_out = _export_video(
            tracks, primary_id, bilingual, media,
            _video_out_path(args, media, out_dir, base, args.video),
            args.video, args.burn, w, h, _scaled(cb, 0.85, 0.99),
        )
        files.append(video_out["out_path"])
    cb.done()
    result = {**extra, "resolution": [w, h], "files": files, "out_dir": str(out_dir),
              "tracks": [{"id": t.id, "language": t.language, "role": t.role,
                          "segments": len(t.segments)} for t in tracks],
              "primary_id": primary_id, "video": video_out}
    lines = [f"输出 {len(files)} 个文件:"] + [f"  - {f}" for f in files]
    return result, lines


def cmd_transcribe(args: argparse.Namespace) -> Result:
    cb = Progress(args.quiet)
    media = _existing(args.media, "媒体文件")
    _ensure_ffmpeg(_scaled(cb, 0.0, 0.02, "[准备] "))
    src, meta = _transcribe(args, media, cb, 0.02, 0.8)
    info = meta.pop("info")
    extra = {**meta, "video_path": str(media)}
    result, lines = _finish_export(args, [src], src.id, False, media,
                                   args.base or media.stem, cb, extra)
    lines.insert(0, f"识别完成: 语言 {meta['language']} / {meta['segment_count']} 段 / "
                    f"{meta['duration']}s / {info.width}x{info.height}")
    return result, lines


def cmd_translate(args: argparse.Namespace) -> Result:
    cb = Progress(args.quiet)
    src_path = _existing(args.input, "字幕文件")
    media = _existing(args.media, "媒体文件") if args.media else None
    src = _load_track(src_path, _norm_lang(args.source_lang), "source",
                      str(media) if media else None, 0.0)
    trn = _translate(args, src, cb, 0.0, 0.8)
    tracks = [src, trn]
    primary = trn if args.primary_target else src
    _apply_sub_styles(tracks, primary)
    extra = {"source_track": {"language": src.language, "segments": len(src.segments)},
             "target": trn.language, "input": str(src_path)}
    result, lines = _finish_export(args, tracks, primary.id, not args.no_bilingual,
                                   media, args.base or src_path.stem, cb, extra)
    lines.insert(0, f"翻译完成: {src.language} → {trn.language} / {len(trn.segments)} 段"
                    f"（双语主行: {primary.language}）")
    return result, lines


def cmd_gen(args: argparse.Namespace) -> Result:
    cb = Progress(args.quiet)
    media = _existing(args.media, "媒体文件")
    _ensure_ffmpeg(_scaled(cb, 0.0, 0.03, "[准备] "))
    src, meta = _transcribe(args, media, cb, 0.03, 0.45)
    info = meta.pop("info")
    tracks = [src]
    primary = src
    extra = {**meta, "video_path": str(media)}
    if args.target:
        trn = _translate(args, src, cb, 0.45, 0.8)
        tracks.append(trn)
        primary = trn if args.primary_target else src
        extra["target"] = trn.language
    _apply_sub_styles(tracks, primary)
    result, lines = _finish_export(args, tracks, primary.id,
                                   not args.no_bilingual and len(tracks) >= 2,
                                   media, args.base or media.stem, cb, extra)
    lines.insert(0, f"识别完成: 语言 {meta['language']} / {meta['segment_count']} 段 / "
                    f"{meta['duration']}s / {info.width}x{info.height}")
    return result, lines


def cmd_export(args: argparse.Namespace) -> Result:
    cb = Progress(args.quiet)
    media = _existing(args.media, "媒体文件") if args.media else None
    duration = 0.0
    if media is not None:
        _ensure_ffmpeg(_scaled(cb, 0.0, 0.05, "[准备] "))
        duration = ffmpeg_tool.probe(str(media)).duration
    tracks, primary = _tracks_from_subs(args, media, duration)
    extra = {"media": str(media) if media else None}
    result, lines = _finish_export(args, tracks, primary.id, not args.no_bilingual,
                                   media, args.base or (media.stem if media else "subtitle"),
                                   cb, extra)
    lines.insert(0, f"轨道: {' + '.join(t.language for t in tracks)}（主行: {primary.language}）")
    return result, lines


def cmd_preview(args: argparse.Namespace) -> Result:
    cb = Progress(args.quiet)
    media = _existing(args.media, "媒体文件")
    _ensure_ffmpeg(_scaled(cb, 0.0, 0.2, "[准备] "))
    duration = ffmpeg_tool.probe(str(media)).duration
    tracks, primary = _tracks_from_subs(args, media, duration)
    burn_id = None
    if args.burn is not None:
        if not 0 <= args.burn < len(tracks):
            _fail(f"--burn 序号越界（0-{len(tracks) - 1}）: {args.burn}")
        burn_id = tracks[args.burn].id
    w, h = _play_size(media, args.width, args.height)
    req = export_router.PreviewFrameRequest(
        tracks=tracks, bilingual=not args.no_bilingual and len(tracks) >= 2,
        primary_id=primary.id, width=w, height=h, video_path=str(media),
        burn_track_id=burn_id, time=max(0.0, float(args.time)),
    )
    cb(0.5, "渲染预览帧...")
    try:
        data_url = export_router.preview_frame(req)["image"]
    except Exception as e:
        _fail(f"预览帧渲染失败: {e}")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    out = Path(args.out).expanduser().resolve() if args.out else \
        media.parent / f"{media.stem}.preview_{args.time:.1f}s.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    cb.done()
    return ({"image": str(out), "time": args.time, "resolution": [w, h],
             "size_kb": round(len(raw) / 1024, 1)},
            [f"预览帧已保存: {out}（{len(raw) / 1024:.0f}KB, t={args.time}s）"])


# ---------------------------------------------------------------- 参数解析

def _common_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--json", action="store_true", help="结果以 JSON 输出（进度仍走 stderr）")
    p.add_argument("-q", "--quiet", action="store_true", help="不打印进度")
    p.add_argument("-v", "--verbose", action="store_true", help="出错时打印完整堆栈")
    return p


def _export_options(p: argparse.ArgumentParser, with_video: bool = True) -> None:
    p.add_argument("-o", "--out", help="输出目录（默认与源媒体同目录）")
    p.add_argument("--base", help="输出文件名前缀（默认取源文件名）")
    p.add_argument("--formats", default="srt,ass", help="字幕格式逗号组合: srt,ass（默认两者）")
    p.add_argument("--width", type=int, default=0, help="ASS 画布宽（0=自动探测视频）")
    p.add_argument("--height", type=int, default=0, help="ASS 画布高（0=自动探测视频）")
    p.add_argument("--no-bilingual", action="store_true", help="不导出双语合并字幕")
    if with_video:
        p.add_argument("--video", choices=["soft", "hard"],
                       help="soft=无损封装 MKV / hard=烧录硬字幕 MP4")
        p.add_argument("--video-out", help="视频输出路径（默认 <out>/<base>.soft.mkv 或 .hard.mp4）")
        p.add_argument("--burn", type=int, help="hard 模式只烧第 N 条轨（0 基，默认双语/主轨）")


def _sub_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("-s", "--sub", action="append", required=True,
                   help="字幕文件（srt/vtt/ass），可重复；首条为主轨")
    p.add_argument("--lang", action="append", help="按 --sub 顺序显式指定语言码，可重复")
    p.add_argument("--primary", type=int, help="主行轨道序号（0 基，默认 0）")


def build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    parser = argparse.ArgumentParser(
        prog="subcraft", description="SubCraft 字幕生成器命令行：识别 / 翻译 / 导出 / 烧录预览。",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<命令>")

    p = sub.add_parser("status", help="环境自检（ffmpeg / CUDA / 翻译厂商 / 模型）", parents=[common])
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("probe", help="探测音视频文件（时长 / 分辨率 / 编码）", parents=[common])
    p.add_argument("media", help="媒体文件路径")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("fonts", help="列出系统字体（供样式参考）", parents=[common])
    p.add_argument("-k", "--keyword", default="", help="过滤关键字，如 YaHei")
    p.add_argument("--limit", type=int, default=60, help="最多显示条数")
    p.set_defaults(func=cmd_fonts)

    p = sub.add_parser("transcribe", help="语音识别并导出字幕文件", parents=[common])
    p.add_argument("media", help="媒体文件路径")
    p.add_argument("--engine", default="local", choices=["local", "openai"],
                   help="local=本地 faster-whisper / openai=云端 Whisper API")
    p.add_argument("--model", help="Whisper 模型: tiny/base/small/medium/large-v3-turbo/large-v3")
    p.add_argument("--lang", help="源语言码（留空自动检测）")
    _export_options(p)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("translate", help="翻译字幕文件并导出（含双语）", parents=[common])
    p.add_argument("input", help="源字幕文件路径")
    p.add_argument("-t", "--target", required=True, help="目标语言码，如 zh/en/ja")
    p.add_argument("--source-lang", help="源语言码（留空按文件名/内容推断）")
    p.add_argument("--provider", default="ai", choices=["ai", "deepl"], help="翻译厂商类型")
    p.add_argument("--provider-id", help="指定已配置厂商 id（留空用第一个）")
    p.add_argument("--model", help="覆盖厂商默认模型名")
    p.add_argument("--media", help="关联视频（用于 ASS 画布尺寸与封装）")
    p.add_argument("--primary-target", action="store_true", help="双语以译文为主行（默认源语言为主行）")
    p.add_argument("--glossary", help="术语表文件（每行「原文=译文」，留空用设置里的术语表）")
    _export_options(p)
    p.set_defaults(func=cmd_translate)

    p = sub.add_parser("gen", help="一条龙：识别 → 可选翻译 → 导出字幕 / 封装视频", parents=[common])
    p.add_argument("media", help="媒体文件路径")
    p.add_argument("-t", "--target", help="目标语言码（留空则只识别不翻译）")
    p.add_argument("--engine", default="local", choices=["local", "openai"])
    p.add_argument("--model", help="Whisper 模型名")
    p.add_argument("--lang", help="源语言码（留空自动检测）")
    p.add_argument("--provider", default="ai", choices=["ai", "deepl"])
    p.add_argument("--provider-id", help="指定已配置厂商 id")
    p.add_argument("--primary-target", action="store_true", help="双语以译文为主行（默认源语言为主行）")
    p.add_argument("--glossary", help="术语表文件（每行「原文=译文」，留空用设置里的术语表）")
    _export_options(p)
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser("export", help="用已有字幕文件导出字幕 / 封装 / 烧录视频", parents=[common])
    _sub_options(p)
    p.add_argument("--media", help="源视频（用于画布尺寸与封装/烧录）")
    _export_options(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("preview", help="渲染指定时间点的真实烧录预览图", parents=[common])
    _sub_options(p)
    p.add_argument("--media", required=True, help="源视频路径")
    p.add_argument("--time", type=float, default=0.0, help="预览时间点（秒）")
    p.add_argument("-o", "--out", help="预览图输出路径（.jpg，默认与视频同目录）")
    p.add_argument("--width", type=int, default=0)
    p.add_argument("--height", type=int, default=0)
    p.add_argument("--burn", type=int, help="只烧第 N 条轨（0 基，默认双语/主轨）")
    p.add_argument("--no-bilingual", action="store_true", help="只烧主轨")
    p.set_defaults(func=cmd_preview)

    return parser


def _fix_stdio() -> None:
    """Windows 中文控制台兜底：统一 UTF-8 输出，避免编码异常。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _fix_stdio()
    args = build_parser().parse_args(argv)
    try:
        args.formats = _check_formats(getattr(args, "formats", "srt,ass"))
        result, human = args.func(args)
    except CliError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except Exception as e:                                  # noqa: BLE001 - 兜底回传细节
        if getattr(args, "verbose", False):
            traceback.print_exc()
        print(f"内部错误: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n".join(human))
    return 0


if __name__ == "__main__":
    sys.exit(main())
