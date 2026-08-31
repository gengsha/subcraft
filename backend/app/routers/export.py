"""导出：SRT/ASS 字幕文件 + MKV 软字幕封装（无损）+ 硬字幕烧录（重编码）。"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import work_dir
from ..models import SubtitleTrack
from ..services import ass_builder, ffmpeg_tool, fonts, srt_builder
from ..tasks import manager

router = APIRouter(prefix="/api/export", tags=["export"])


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


class PreviewRequest(BaseModel):
    tracks: list[SubtitleTrack]
    bilingual: bool = True
    primary_id: str | None = None
    width: int = 1920
    height: int = 1080


class SubtitleExportRequest(PreviewRequest):
    out_dir: str
    base_name: str = "subtitle"
    formats: list[str] = ["ass", "srt"]   # ass / srt


class VideoExportRequest(PreviewRequest):
    video_path: str
    out_path: str
    mode: Literal["soft", "hard"] = "soft"   # soft=软字幕封装 / hard=内嵌烧录进画面
    burn_track_id: str | None = None          # hard 模式烧录哪条轨；None=双语(若有)否则主轨


class PreviewFrameRequest(PreviewRequest):
    video_path: str
    burn_track_id: str | None = None
    time: float = 0.0                          # 预览时间点(秒)


@router.post("/preview_ass")
def preview_ass(req: PreviewRequest) -> dict:
    """生成当前项目 ASS 文本供前端 libass 实时预览。"""
    return {"ass": ass_builder.build_ass(req.tracks, req.width, req.height, req.bilingual, req.primary_id)}


@router.post("/subtitles")
def export_subtitles(req: SubtitleExportRequest) -> dict:
    out_dir = Path(req.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _safe_name(req.base_name)
    files: list[str] = []

    for fmt in req.formats:
        if fmt == "ass":
            # 每语言一个单语 ASS + 双语合并 ASS
            for t in req.tracks:
                p = out_dir / f"{base}.{t.language}.ass"
                p.write_text(ass_builder.build_ass([t], req.width, req.height), encoding="utf-8-sig")
                files.append(str(p))
            if req.bilingual and len(req.tracks) >= 2:
                p = out_dir / f"{base}.bilingual.ass"
                p.write_text(
                    ass_builder.build_ass(req.tracks, req.width, req.height, True, req.primary_id),
                    encoding="utf-8-sig",
                )
                files.append(str(p))
        elif fmt == "srt":
            for t in req.tracks:
                p = out_dir / f"{base}.{t.language}.srt"
                p.write_text(srt_builder.build_srt(t), encoding="utf-8-sig")
                files.append(str(p))
            if req.bilingual and len(req.tracks) >= 2:
                primary = next((t for t in req.tracks if t.id == req.primary_id), req.tracks[0])
                secondary = next(t for t in req.tracks if t.id != primary.id)
                p = out_dir / f"{base}.bilingual.srt"
                p.write_text(srt_builder.build_bilingual_srt(primary, secondary), encoding="utf-8-sig")
                files.append(str(p))
    return {"files": files}


@router.post("/video")
def export_video(req: VideoExportRequest) -> dict:
    if not Path(req.video_path).exists():
        raise HTTPException(404, "源视频不存在")
    if not req.tracks:
        raise HTTPException(400, "没有可导出的字幕轨")

    if req.mode == "hard":
        return _export_video_hard(req)
    return _export_video_soft(req)


def _burn_ass_text(req: PreviewRequest, burn_track_id: str | None) -> str:
    """烧录用 ASS 文本：优先双语，其次指定/主轨道。"""
    if burn_track_id is None and req.bilingual and len(req.tracks) >= 2:
        return ass_builder.build_ass(req.tracks, req.width, req.height, True, req.primary_id)
    track = next((t for t in req.tracks if t.id == burn_track_id), None)
    if track is None:
        track = next((t for t in req.tracks if t.id == req.primary_id), req.tracks[0])
    return ass_builder.build_ass([track], req.width, req.height)


def _write_temp_ass(req: PreviewRequest, name: str, stem: str, burn_track_id: str | None, directory: Path) -> Path:
    """把烧录用 ASS 写到临时文件。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f".{_safe_name(stem)}.{name}.ass"
    path.write_text(_burn_ass_text(req, burn_track_id), encoding="utf-8-sig")
    return path


def _fonts_dir_for(req: VideoExportRequest) -> str | None:
    """取字幕样式的字体所在目录，供 libass 在字体选择失败时兜底。"""
    for t in req.tracks:
        f = fonts.font_file(t.style.font_name)
        if f and f.parent.exists():
            return str(f.parent)
    return None


def _export_video_soft(req: VideoExportRequest) -> dict:
    def job(progress_cb):
        progress_cb(0.05, "生成字幕轨...")
        tmp = Path(req.out_path).parent
        stem = _safe_name(Path(req.out_path).stem)
        tmp.mkdir(parents=True, exist_ok=True)
        subs: list[tuple[Path, str, str]] = []
        # 双语轨（默认显示）+ 各单语轨；每条 ASS 轨附一条 SRT 兼容轨
        # （部分播放器不支持 ASS 软字幕样式，SRT 保证至少能看到纯文本）
        if req.bilingual and len(req.tracks) >= 2:
            bi = tmp / f".{stem}.bilingual.ass"
            bi.write_text(
                ass_builder.build_ass(req.tracks, req.width, req.height, True, req.primary_id),
                encoding="utf-8-sig",
            )
            subs.append((bi, "zho", "双语 / Bilingual"))
            primary = next((t for t in req.tracks if t.id == req.primary_id), req.tracks[0])
            secondary = next(t for t in req.tracks if t.id != primary.id)
            srt = tmp / f".{stem}.bilingual.srt"
            srt.write_text(srt_builder.build_bilingual_srt(primary, secondary), encoding="utf-8-sig")
            subs.append((srt, "zho", "双语 SRT (兼容)"))
        for t in req.tracks:
            f = tmp / f".{stem}.{t.language}.ass"
            f.write_text(ass_builder.build_ass([t], req.width, req.height), encoding="utf-8-sig")
            subs.append((f, t.language, t.label or t.language))
            srt = tmp / f".{stem}.{t.language}.srt"
            srt.write_text(srt_builder.build_srt(t), encoding="utf-8-sig")
            subs.append((srt, t.language, f"{t.label or t.language} SRT"))
        progress_cb(0.3, "封装中（视频流直接复制，不重编码）...")
        ffmpeg_tool.mux_subtitles(req.video_path, subs, Path(req.out_path), default_index=0)
        for f, _, _ in subs:
            f.unlink(missing_ok=True)
        progress_cb(0.99, "完成")
        return {"out_path": req.out_path}

    return {"task_id": manager.submit(job)}


def _export_video_hard(req: VideoExportRequest) -> dict:
    def job(progress_cb):
        progress_cb(0.05, "生成字幕轨...")
        sub = _write_temp_ass(req, "burn", Path(req.out_path).stem, req.burn_track_id,
                              Path(req.out_path).parent)
        fonts_dir = _fonts_dir_for(req)

        def on_encode(p: float, msg: str) -> None:
            progress_cb(0.08 + p * 0.87, msg)

        ffmpeg_tool.burn_subtitles(req.video_path, sub, Path(req.out_path), on_encode, fonts_dir)
        sub.unlink(missing_ok=True)
        progress_cb(0.99, "完成")
        return {"out_path": req.out_path}

    return {"task_id": manager.submit(job)}


@router.post("/preview_frame")
def preview_frame(req: PreviewFrameRequest) -> dict:
    """按最终烧录管线渲染单帧预览图，返回 data URL，供导出前所见即所得确认。"""
    if not Path(req.video_path).exists():
        raise HTTPException(404, "源视频不存在")
    if not req.tracks:
        raise HTTPException(400, "没有可预览的字幕轨")
    d = work_dir()
    sub = _write_temp_ass(req, "preview", "burn_preview", req.burn_track_id, d)
    jpg = d / "burn_preview.jpg"
    try:
        ffmpeg_tool.burn_frame(req.video_path, sub, req.time, jpg, _fonts_dir_for(req))
        b64 = base64.b64encode(jpg.read_bytes()).decode()
        return {"image": f"data:image/jpeg;base64,{b64}"}
    finally:
        sub.unlink(missing_ok=True)
        jpg.unlink(missing_ok=True)
