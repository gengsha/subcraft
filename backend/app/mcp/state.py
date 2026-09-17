"""MCP 会话状态：内存中的字幕轨道存储 + 长任务后台执行。

MCP 工具调用是「请求-响应」式的，而识别/翻译/压制可能耗时数分钟，因此这里提供一个
轻量任务池：工具可以立刻返回 `job_id`（`wait=False`），也可以阻塞等待并通过
`ctx.report_progress` 上报进度（`wait=True`）。
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from ..models import LANGUAGES, Segment, SubtitleStyle, SubtitleTrack

ProgressCb = Callable[[float, str], None]

# 单次工具调用返回的段数上限，避免把上千条字幕一次性灌进模型上下文
MAX_SEGMENTS_PER_CALL = 200
DEFAULT_PAGE_SIZE = 50
# 文本类结果（如 ASS 源码）的最大返回长度
MAX_TEXT_CHARS = 8000
# 任务记录保留条数
MAX_JOBS_KEPT = 50


@dataclass
class SessionTrack:
    """会话内的一条字幕轨（附带来源视频信息，便于导出时自动推导参数）。"""

    track: SubtitleTrack
    video_path: str | None = None
    duration: float = 0.0
    origin: str = ""            # transcribe / translate / file / manual

    @property
    def id(self) -> str:
        return self.track.id

    def summary(self) -> dict[str, Any]:
        t, s = self.track, self.track.style
        segs = t.segments
        return {
            "track_id": t.id,
            "language": t.language,
            "language_name": LANGUAGES.get(t.language, t.language),
            "label": t.label,
            "role": t.role,
            "origin": self.origin,
            "segment_count": len(segs),
            "span": [round(segs[0].start, 2), round(segs[-1].end, 2)] if segs else None,
            "video_path": self.video_path,
            "duration": round(self.duration, 2),
            "style": {
                "font_name": s.font_name,
                "font_size": s.font_size,
                "primary_color": s.primary_color,
                "outline_color": s.outline_color,
                "outline": s.outline,
                "shadow": s.shadow,
                "alignment": s.alignment,
                "margin_v": s.margin_v,
                "pos": [s.pos_x, s.pos_y] if s.pos_x is not None else None,
            },
        }


def translation_style(base: SubtitleStyle | None = None) -> SubtitleStyle:
    """翻译轨默认样式：与前端一致（副语言字号缩小 30%，淡黄色区分）。"""
    src = base or SubtitleStyle()
    return SubtitleStyle(
        **{
            **src.model_dump(),
            "font_size": max(12, round(src.font_size * 0.7)),
            "primary_color": "#FFFF99",
        }
    )


class Session:
    """MCP 进程内的字幕轨道集合（不持久化，可用 subcraft_save_project 落盘）。"""

    def __init__(self) -> None:
        self._items: dict[str, SessionTrack] = {}
        self._seq = 0
        self._lock = threading.RLock()

    # ---- 增删查 ----
    def next_id(self) -> str:
        with self._lock:
            self._seq += 1
            while f"t{self._seq}" in self._items:
                self._seq += 1
            return f"t{self._seq}"

    def insert(self, st: SessionTrack) -> str:
        with self._lock:
            self._items[st.track.id] = st
            return st.track.id

    def create(
        self,
        segments: list[Segment],
        *,
        language: str = "und",
        role: str = "source",
        label: str = "",
        style: SubtitleStyle | None = None,
        video_path: str | None = None,
        duration: float = 0.0,
        origin: str = "manual",
    ) -> SessionTrack:
        label = label or LANGUAGES.get(language or "", "") or ("" if language in (None, "", "und") else language)
        track = SubtitleTrack(
            id=self.next_id(),
            language=language or "und",
            label=label,
            role="translation" if role == "translation" else "source",
            segments=segments,
            style=style or SubtitleStyle(),
        )
        st = SessionTrack(track=track, video_path=video_path, duration=duration, origin=origin)
        self.insert(st)
        return st

    def get(self, track_id: str) -> SessionTrack | None:
        return self._items.get(track_id)

    def ids(self) -> list[str]:
        return list(self._items)

    def all(self) -> list[SessionTrack]:
        return list(self._items.values())

    def resolve(self, track_ids: list[str] | None) -> list[SessionTrack]:
        """None/空 → 全部轨道（保持插入顺序）；否则按给定顺序取。"""
        if not track_ids:
            return self.all()
        return [self._items[i] for i in track_ids if i in self._items]

    def clear(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            self._seq = 0
            return n

    # ---- 项目文件 ----
    def dump(self) -> dict[str, Any]:
        return {
            "app": "SubCraft",
            "version": 1,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tracks": [
                {
                    "track": st.track.model_dump(),
                    "video_path": st.video_path,
                    "duration": st.duration,
                    "origin": st.origin,
                }
                for st in self.all()
            ],
        }

    def load(self, data: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for item in data.get("tracks", []) or []:
            track = SubtitleTrack.model_validate(item.get("track") or item)
            if track.id in self._items:                 # 重名时换一个新 id
                track.id = self.next_id()
            ids.append(self.insert(SessionTrack(
                track=track,
                video_path=item.get("video_path"),
                duration=float(item.get("duration") or 0.0),
                origin=item.get("origin") or "project",
            )))
        return ids


class JobRunner:
    """线程池执行长任务，进度写入任务表供工具轮询。"""

    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="subcraft-mcp-job")
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def submit(self, fn: Callable[[ProgressCb], Any], label: str = "") -> str:
        job_id = uuid.uuid4().hex[:12]
        t0 = time.time()
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id, "label": label, "status": "running",
                "progress": 0.0, "message": "排队中", "result": None, "error": None,
                "elapsed_sec": 0.0,
            }
            self._gc()

        def progress_cb(p: float, msg: str) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["progress"] = round(min(max(float(p), 0.0), 1.0), 3)
                    job["message"] = msg
                    job["elapsed_sec"] = round(time.time() - t0, 1)

        def runner() -> None:
            try:
                result = fn(progress_cb)
                with self._lock:
                    self._jobs[job_id].update(
                        status="done", progress=1.0, message="完成",
                        result=result, elapsed_sec=round(time.time() - t0, 1),
                    )
            except Exception as e:                       # noqa: BLE001 - 任务失败要回传给调用方
                traceback.print_exc()                    # 走 stderr，不污染 stdio 协议通道
                with self._lock:
                    self._jobs[job_id].update(
                        status="error", message="失败", error=f"{type(e).__name__}: {e}",
                        elapsed_sec=round(time.time() - t0, 1),
                    )

        self._pool.submit(runner)
        return job_id

    def _gc(self) -> None:
        if len(self._jobs) > MAX_JOBS_KEPT:
            for k in list(self._jobs)[: len(self._jobs) - MAX_JOBS_KEPT]:
                self._jobs.pop(k, None)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def view(self, job_id: str, with_result: bool = False) -> dict[str, Any] | None:
        """任务快照；默认剔除 result（体积可能很大）。"""
        job = self.get(job_id)
        if job is None or with_result:
            return job
        job.pop("result", None)
        return job

    def recent(self, limit: int = 10, with_result: bool = False) -> list[dict[str, Any]]:
        """最近若干条任务快照（按提交顺序）。"""
        with self._lock:
            ids = list(self._jobs)[-max(1, int(limit)):]
        return [v for v in (self.view(i, with_result) for i in ids) if v]


SESSION = Session()
JOBS = JobRunner()
