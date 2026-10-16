"""批量处理：对整个文件夹依次「识别 → 可选贴齐镜头切点 → 可选翻译 → 导出字幕 / 成片」。

CLI（`subcraft batch`）与 MCP（`subcraft_batch_process`）共用这里的实现，保证两边行为一致。
典型场景是课程、剧集：一个目录几十集，按集号自然排序逐个处理，单集失败不影响其余，
重跑时跳过已完成的文件（断点续跑），最后在输出目录写一份 JSON 报告。

两种输入模式：
- media：扫描音视频文件，走完整流水线（识别模型只加载一次，后续各集复用）。
- subs：扫描已有字幕文件（如课程自带的英文 srt），只做翻译 + 导出；同目录同名视频
  会被自动关联，用于 ASS 画布尺寸、贴齐切点与封装 / 烧录。
"""
from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import store
from ..models import LANGUAGES, Segment, SubtitleTrack

ProgressCb = Callable[[float, str], None]

MEDIA_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mts",
              ".mpg", ".mpeg", ".3gp", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
SUB_EXTS = (".srt", ".vtt", ".ass", ".ssa")       # 同一集有多种格式时按此顺序取第一个
REPORT_NAME = "subcraft_batch_report.json"
# 本工具自己产出的成片，重跑时不能再被当成输入
_OUTPUT_VIDEO_RE = re.compile(r"(\.hard\.mp4|\.soft\.mkv|_内嵌\.\w+|_sub\.\w+)$", re.I)


@dataclass
class BatchOptions:
    mode: str = "media"                     # media / subs
    target: str | None = None               # 目标语言；None=只识别（subs 模式必填）
    out_dir: str | None = None              # 输出根目录；None=各文件原目录。子目录结构会保留
    recursive: bool = False
    pattern: str | None = None              # 文件名通配，如 "*.mp4" / "EP*"
    engine: str = "local"
    whisper_model: str | None = None
    source_lang: str | None = None
    provider: str = "ai"
    provider_id: str | None = None
    translate_model: str | None = None
    glossary: str | None = None             # 术语表文本（每行「原文=译文」）；None=用设置里的
    primary_target: bool = False            # 双语以译文为主行
    bilingual: bool = True
    formats: list[str] = field(default_factory=lambda: ["srt", "ass"])
    video: str | None = None                # soft / hard / None
    snap_cuts: bool = False
    split_cuts: bool = False                # 贴齐后仍跨镜头的段按切点自动拆开（隐含 snap_cuts）
    cut_threshold: float = 0.3
    tolerance: float = 0.5
    skip_existing: bool = True
    stop_on_error: bool = False
    limit: int = 0                          # 只处理前 N 个（0=全部），便于先试跑一两集


class BatchError(ValueError):
    """参数 / 目录层面的错误（单个文件的失败不会抛出，而是记进报告）。"""


# ---------------------------------------------------------------- 扫描与命名

def natural_key(p: Path) -> list[Any]:
    """自然排序：EP2 排在 EP10 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(p))]


def _lang_tokens(stem: str) -> list[str]:
    return [t for t in re.split(r"[._\-\s()+]+", stem.lower()) if t]


def strip_lang_suffix(stem: str) -> str:
    """`lesson01.en` → `lesson01`；`EP01.bilingual` → `EP01`。"""
    m = re.match(r"^(.*?)[._]([A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?|bilingual|retimed)$", stem)
    if m and (m.group(2).lower() in LANGUAGES or m.group(2).lower() in ("bilingual", "retimed")):
        return strip_lang_suffix(m.group(1))
    return stem


def guess_language(path: Path) -> str | None:
    for tok in reversed(_lang_tokens(path.stem)):
        if tok in LANGUAGES and tok != "auto":
            return tok
    return None


def validate(opts: BatchOptions) -> BatchOptions:
    opts.mode = (opts.mode or "media").lower()
    if opts.mode not in ("media", "subs"):
        raise BatchError(f"mode 只能是 media / subs，收到: {opts.mode}")
    if opts.target is not None and (opts.target not in LANGUAGES or opts.target == "auto"):
        raise BatchError(f"无效的目标语言码: {opts.target}")
    if opts.mode == "subs" and not opts.target:
        raise BatchError("subs 模式（翻译已有字幕）必须指定目标语言")
    opts.formats = [f.lower() for f in (opts.formats or ["srt", "ass"])]
    bad = [f for f in opts.formats if f not in ("srt", "ass")]
    if bad or not opts.formats:
        raise BatchError(f"不支持的字幕格式: {'、'.join(bad) or '空'}（仅 srt / ass）")
    if opts.split_cuts:
        opts.snap_cuts = True
    if opts.video is not None:
        opts.video = opts.video.lower() or None
        if opts.video not in (None, "soft", "hard"):
            raise BatchError(f"video 只能是 soft / hard / 留空，收到: {opts.video}")
    return opts


def _inside(p: Path, d: Path) -> bool:
    try:
        p.resolve().relative_to(d.resolve())
        return True
    except ValueError:
        return False


def find_inputs(root: Path, opts: BatchOptions) -> list[Path]:
    """按模式列出要处理的文件（自然排序）。会排除输出目录与本工具产出的文件。"""
    if not root.is_dir():
        raise BatchError(f"不是文件夹: {root}")
    out_root = Path(opts.out_dir).expanduser().resolve() if opts.out_dir else None
    it = root.rglob("*") if opts.recursive else root.glob("*")
    files = []
    for p in it:
        if not p.is_file() or p.name.startswith("."):
            continue
        if out_root and out_root != root.resolve() and _inside(p, out_root):
            continue
        if opts.pattern and not p.match(opts.pattern):
            continue
        files.append(p)

    if opts.mode == "media":
        picked = [p for p in files if p.suffix.lower() in MEDIA_EXTS and not _OUTPUT_VIDEO_RE.search(p.name)]
    else:
        groups: dict[tuple[Path, str], list[Path]] = {}
        for p in files:
            if p.suffix.lower() not in SUB_EXTS:
                continue
            toks = _lang_tokens(p.stem)
            if "bilingual" in toks or "retimed" in toks:
                continue                      # 双语合并 / retime 产物
            if opts.target and guess_language(p) == opts.target:
                continue                      # 已是目标语言（多半是上次的译文）
            groups.setdefault((p.parent, strip_lang_suffix(p.stem)), []).append(p)
        picked = [sorted(g, key=lambda x: SUB_EXTS.index(x.suffix.lower()))[0] for g in groups.values()]
    picked.sort(key=natural_key)
    return picked[: opts.limit] if opts.limit and opts.limit > 0 else picked


def output_dir_for(item: Path, root: Path, opts: BatchOptions) -> Path:
    if not opts.out_dir:
        return item.parent
    rel = item.parent.resolve().relative_to(root.resolve())
    return Path(opts.out_dir).expanduser().resolve() / rel


def base_name_for(item: Path, opts: BatchOptions) -> str:
    stem = strip_lang_suffix(item.stem) if opts.mode == "subs" else item.stem
    return re.sub(r'[\\/:*?"<>|]', "_", stem)


def video_out_path(out_dir: Path, base: str, mode: str) -> Path:
    return out_dir / f"{base}.{'hard.mp4' if mode == 'hard' else 'soft.mkv'}"


def is_done(item: Path, out_dir: Path, opts: BatchOptions) -> bool:
    """断点续跑判断：该集要求的产物都已存在就跳过。"""
    base = base_name_for(item, opts)
    fmt = opts.formats[0]
    if opts.target:
        subs_ok = (out_dir / f"{base}.{opts.target}.{fmt}").exists()
    else:
        subs_ok = any(p for p in out_dir.glob(f"{glob_escape(base)}.*.{fmt}")
                      if p.stem.rsplit(".", 1)[-1] in LANGUAGES)
    video_ok = video_out_path(out_dir, base, opts.video).exists() if opts.video else True
    return subs_ok and video_ok


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def find_media_for(sub: Path) -> Path | None:
    """subs 模式：找同目录同名视频（lesson01.en.srt → lesson01.mp4）。"""
    base = strip_lang_suffix(sub.stem)
    for p in sorted(sub.parent.iterdir(), key=natural_key):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS and p.stem == base \
                and not _OUTPUT_VIDEO_RE.search(p.name):
            return p
    return None


# ---------------------------------------------------------------- 单集处理

_seq = 0


def _tid(prefix: str) -> str:
    global _seq
    _seq += 1
    return f"{prefix}{_seq}"


def _scaled(cb: ProgressCb, lo: float, hi: float, prefix: str = "") -> ProgressCb:
    return lambda p, m: cb(lo + (hi - lo) * max(0.0, min(1.0, p)), prefix + m)


def _translate(src: SubtitleTrack, opts: BatchOptions, cb: ProgressCb) -> SubtitleTrack:
    from ..mcp.state import translation_style
    from . import translator

    translated = translator.translate_segments(
        src.segments, src.language if src.language not in ("", "und") else "auto", opts.target,
        "deepl" if str(opts.provider or "ai").lower() == "deepl" else "openai", opts.provider_id,
        None, None, opts.translate_model,
        batch_size=int(store.get("translate_batch_size", 25) or 25),
        concurrency=int(store.get("translate_concurrency", 4) or 4),
        progress_cb=cb, glossary=opts.glossary,
    )
    if len(translated) != len(src.segments):
        raise RuntimeError(f"翻译段数不对齐: 源 {len(src.segments)} / 译文 {len(translated)}")
    return SubtitleTrack(id=_tid("bt"), language=opts.target, label=LANGUAGES.get(opts.target, opts.target),
                         role="translation", segments=translated, style=translation_style(src.style))


def _snap(segments: list[Segment], media: Path, opts: BatchOptions) -> tuple[list[Segment], dict]:
    from . import ffmpeg_tool, timeline

    ffmpeg, _ = ffmpeg_tool.ensure_ffmpeg()
    cuts = timeline.detect_cuts(ffmpeg, str(media), opts.cut_threshold)
    new, changes = timeline.snap_to_cuts(segments, cuts, opts.tolerance)
    split = 0
    if opts.split_cuts:
        # 从后往前拆，前面的序号不受影响；拆不开（文字太短等）的保留并报告
        for x in reversed(timeline.crossing_cuts(new, cuts)):
            for c in reversed(x["cuts"]):
                try:
                    new = timeline.split(new, x["index"], c)
                    split += 1
                except ValueError:
                    pass
    crossing = timeline.crossing_cuts(new, cuts)
    return new, {"cuts": len(cuts), "snapped": len(changes), "split": split,
                 "need_split": [{"index": x["index"] + 1, "cuts": x["cuts"]} for x in crossing[:20]]}


def _export(tracks: list[SubtitleTrack], primary: SubtitleTrack, media: Path | None,
            out_dir: Path, base: str, opts: BatchOptions, w: int, h: int, cb: ProgressCb) -> tuple[list[str], str | None]:
    from ..mcp.state import translation_style
    from ..routers import export as export_router
    from . import ffmpeg_tool

    for t in tracks:                       # 非主轨套副语言样式，与桌面端 / CLI / MCP 一致
        if t.id != primary.id:
            t.style = translation_style(primary.style)
    bilingual = opts.bilingual and len(tracks) >= 2
    out_dir.mkdir(parents=True, exist_ok=True)
    res = export_router.export_subtitles(export_router.SubtitleExportRequest(
        tracks=tracks, bilingual=bilingual, primary_id=primary.id, width=w, height=h,
        out_dir=str(out_dir), base_name=base, formats=opts.formats,
    ))
    files = list(res.get("files", []))
    video_out = None
    if opts.video:
        if media is None:
            raise RuntimeError("找不到同名视频，无法封装 / 烧录")
        out_path = video_out_path(out_dir, base, opts.video)
        if out_path.resolve() == media.resolve():
            raise RuntimeError("视频输出路径与源视频相同")
        req = export_router.VideoExportRequest(
            tracks=tracks, bilingual=bilingual, primary_id=primary.id, width=w, height=h,
            video_path=str(media), out_path=str(out_path), mode=opts.video,
        )
        if opts.video == "soft":
            cb(0.1, "封装软字幕...")
            subs = export_router.build_soft_sub_files(req, out_path.parent, out_path.stem)
            try:
                ffmpeg_tool.mux_subtitles(str(media), subs, out_path, default_index=0)
            finally:
                for f, _, _ in subs:
                    f.unlink(missing_ok=True)
        else:
            sub = export_router.write_burn_ass(req, "burn", out_path.stem, None, out_path.parent)
            try:
                ffmpeg_tool.burn_subtitles(str(media), sub, out_path, _scaled(cb, 0.05, 1.0, "压制 "),
                                           export_router.fonts_dir_for(req))
            finally:
                sub.unlink(missing_ok=True)
        video_out = str(out_path)
        files.append(video_out)
    return files, video_out


def _canvas(media: Path | None) -> tuple[int, int, float]:
    from . import ffmpeg_tool

    if media is None:
        return 1920, 1080, 0.0
    info = ffmpeg_tool.probe(str(media))
    return (info.width or 1920), (info.height or 1080), info.duration


def process_media(item: Path, out_dir: Path, opts: BatchOptions, cb: ProgressCb) -> dict[str, Any]:
    from . import asr

    w, h, duration = _canvas(item)
    lang = None if opts.source_lang in (None, "", "auto") else opts.source_lang
    segments, detected = asr.transcribe(
        str(item), duration, "openai" if str(opts.engine).lower() in ("openai", "cloud") else "local",
        opts.whisper_model, lang, None, None, _scaled(cb, 0.0, 0.5, "识别 "),
    )
    if not segments:
        raise RuntimeError("未识别到语音内容")
    extra: dict[str, Any] = {}
    if opts.snap_cuts:
        cb(0.5, "检测镜头切点...")
        segments, extra["snap"] = _snap(segments, item, opts)
    language = detected or "und"
    src = SubtitleTrack(id=_tid("bs"), language=language, label=LANGUAGES.get(language, language) or language,
                        role="source", segments=segments)
    tracks, primary = [src], src
    if opts.target:
        trn = _translate(src, opts, _scaled(cb, 0.55, 0.8, "翻译 "))
        tracks.append(trn)
        primary = trn if opts.primary_target else src
    files, video_out = _export(tracks, primary, item, out_dir, base_name_for(item, opts), opts, w, h,
                               _scaled(cb, 0.82, 1.0, "导出 "))
    return {"language": language, "segments": len(segments), "duration": round(duration, 2),
            "files": files, "video": video_out, **extra}


def process_subtitle(item: Path, out_dir: Path, opts: BatchOptions, cb: ProgressCb) -> dict[str, Any]:
    from . import subtitle_parser

    segments = subtitle_parser.parse_file(item)
    if not segments:
        raise RuntimeError("字幕文件没有可用段落")
    media = find_media_for(item)
    w, h, _ = _canvas(media)
    extra: dict[str, Any] = {"media": str(media) if media else None}
    if opts.snap_cuts and media is not None:
        cb(0.05, "检测镜头切点...")
        segments, extra["snap"] = _snap(segments, media, opts)
    language = (None if opts.source_lang in (None, "", "auto") else opts.source_lang) \
        or guess_language(item) or "und"
    src = SubtitleTrack(id=_tid("bs"), language=language, label=LANGUAGES.get(language, language) or language,
                        role="source", segments=segments)
    trn = _translate(src, opts, _scaled(cb, 0.1, 0.8, "翻译 "))
    primary = trn if opts.primary_target else src
    files, video_out = _export([src, trn], primary, media, out_dir, base_name_for(item, opts), opts, w, h,
                               _scaled(cb, 0.82, 1.0, "导出 "))
    return {"language": language, "segments": len(segments), "files": files, "video": video_out, **extra}


# ---------------------------------------------------------------- 批量主循环

def run_batch(folder: str | Path, opts: BatchOptions, cb: ProgressCb | None = None,
              on_item: Callable[[dict[str, Any]], None] | None = None,
              dry_run: bool = False) -> dict[str, Any]:
    """逐个处理文件夹中的文件，返回（并写出）批量报告。

    cb(p, msg) 是整批进度（0~1）；on_item(record) 在每个文件结束时回调，便于实时打印。
    单个文件失败只记进报告，除非 stop_on_error=True。
    """
    cb = cb or (lambda p, m: None)
    root = Path(str(folder).strip().strip('"')).expanduser().resolve()
    opts = validate(opts)
    items = find_inputs(root, opts)
    started = time.time()
    report: dict[str, Any] = {
        "folder": str(root), "mode": opts.mode, "options": asdict(opts),
        "total": len(items), "done": 0, "skipped": 0, "failed": 0, "items": [],
    }
    report["options"].pop("glossary", None)
    if not items:
        report["message"] = "没有找到可处理的文件" + ("（可加 --recursive 扫描子目录）" if not opts.recursive else "")
        return report
    if not dry_run and (opts.mode == "media" or opts.video):
        from . import ffmpeg_tool
        if not ffmpeg_tool.find_ffmpeg():
            ffmpeg_tool.ensure_ffmpeg(_scaled(cb, 0.0, 0.01, "[准备] "))

    n = len(items)
    for i, item in enumerate(items):
        out_dir = output_dir_for(item, root, opts)
        rec: dict[str, Any] = {"index": i + 1, "input": str(item),
                               "relative": str(item.relative_to(root)), "out_dir": str(out_dir)}
        label = f"[{i + 1}/{n}] {item.name}"
        if opts.skip_existing and is_done(item, out_dir, opts):
            rec["status"] = "skipped"
            report["skipped"] += 1
        elif dry_run:
            rec["status"] = "pending"
        else:
            t0 = time.time()
            item_cb = _scaled(cb, i / n, (i + 1) / n, label + " ")
            try:
                fn = process_media if opts.mode == "media" else process_subtitle
                rec.update(fn(item, out_dir, opts, item_cb))
                rec["status"] = "done"
                report["done"] += 1
            except Exception as e:                      # noqa: BLE001 - 单集失败不中断整批
                rec["status"] = "failed"
                rec["error"] = f"{type(e).__name__}: {e}"
                rec["trace"] = traceback.format_exc(limit=3)[-800:]
                report["failed"] += 1
            rec["elapsed_sec"] = round(time.time() - t0, 1)
        report["items"].append(rec)
        cb((i + 1) / n, f"{label} {rec['status']}")
        if on_item:
            on_item(rec)
        if rec["status"] == "failed" and opts.stop_on_error:
            report["stopped_early"] = True
            break

    report["elapsed_sec"] = round(time.time() - started, 1)
    if not dry_run:
        report_dir = Path(opts.out_dir).expanduser().resolve() if opts.out_dir else root
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / REPORT_NAME
        slim = {**report, "items": [{k: v for k, v in r.items() if k != "trace"} for r in report["items"]]}
        path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(path)
    return report
