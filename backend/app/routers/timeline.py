"""时间轴编辑：拆分 / 合并 / 平移 / 贴齐镜头切点 / 修重叠 / 检查。

前端把当前全部轨道发来，后端用 services.timeline 计算后返回新的轨道列表；
结构操作会同步到与目标轨逐段对齐的其他轨（双语不会错位）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..models import Segment, SubtitleTrack
from ..services import ffmpeg_tool, timeline
from ..tasks import manager

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


class CheckRequest(BaseModel):
    segments: list[Segment]
    max_cps: float = 0.0
    max_duration: float = timeline.DEFAULT_MAX_DURATION


class ApplyRequest(BaseModel):
    tracks: list[SubtitleTrack]
    track_id: str
    op: Literal["split", "merge", "shift", "snap", "fix_overlaps"]
    sync: bool = True
    # split
    index: int | None = None
    at_time: float | None = None
    text: str | None = None
    # merge
    first: int | None = None
    last: int | None = None
    # shift
    offset: float = 0.0
    scale: float = 1.0
    from_time: float | None = None
    # snap
    cuts: list[float] = Field(default_factory=list)
    tolerance: float = 0.5


class CutsRequest(BaseModel):
    video_path: str
    threshold: float = 0.3


@router.post("/check")
def check(req: CheckRequest) -> dict:
    return {"issues": timeline.check(req.segments, req.max_cps, req.max_duration)}


@router.post("/cuts")
def cuts(req: CutsRequest) -> dict:
    """后台检测镜头切点（长视频需要一会儿）；结果 {cuts: [...]}，同一视频再次调用走缓存。"""
    if not Path(req.video_path).exists():
        raise HTTPException(404, f"视频不存在: {req.video_path}")

    def job(progress_cb):
        ffmpeg, _ = ffmpeg_tool.ensure_ffmpeg(progress_cb)
        progress_cb(0.1, "正在检测镜头切点…")
        found = timeline.detect_cuts(ffmpeg, req.video_path, req.threshold)
        progress_cb(1.0, f"检测到 {len(found)} 个切点")
        return {"cuts": found}

    return {"task_id": manager.submit(job)}


@router.post("/apply")
def apply(req: ApplyRequest) -> dict:
    tracks = [t.model_copy(deep=True) for t in req.tracks]
    target = next((t for t in tracks if t.id == req.track_id), None)
    if target is None:
        raise HTTPException(404, f"轨道不存在: {req.track_id}")
    others = timeline.aligned_with(tracks, target) if req.sync else []
    info: dict = {}
    try:
        if req.op == "split":
            if req.index is None:
                raise ValueError("缺少 index")
            target.segments = timeline.split(target.segments, req.index, req.at_time, req.text)
            cut = target.segments[req.index].end
            for o in others:
                o.segments = timeline.split(o.segments, req.index, cut)
            info["split_at"] = cut
        elif req.op == "merge":
            if req.first is None or req.last is None:
                raise ValueError("缺少 first/last")
            for t in [target, *others]:
                t.segments = timeline.merge(t.segments, req.first, req.last)
        elif req.op == "shift":
            for t in [target, *others]:
                t.segments, n = timeline.shift(t.segments, req.offset, req.scale, from_time=req.from_time)
                if t is target:
                    info["shifted"] = n
        elif req.op == "snap":
            if not req.cuts:
                raise ValueError("缺少 cuts：请先调用 /api/timeline/cuts 检测切点")
            for t in [target, *others]:
                t.segments, changes = timeline.snap_to_cuts(t.segments, req.cuts, req.tolerance)
                if t is target:
                    info["changes"] = changes
            info["need_split"] = timeline.crossing_cuts(target.segments, req.cuts)
        elif req.op == "fix_overlaps":
            target.segments, info["fixed"] = timeline.fix_overlaps(target.segments)
            others = []
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    info["synced"] = [o.id for o in others]
    return {"tracks": tracks, "info": info, "issues": timeline.check(target.segments)}
