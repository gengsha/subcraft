"""SRT 字幕生成。"""
from __future__ import annotations

from ..models import SubtitleTrack


def fmt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(track: SubtitleTrack) -> str:
    blocks = []
    for i, seg in enumerate(track.segments, 1):
        blocks.append(
            f"{i}\n{fmt_timestamp(seg.start)} --> {fmt_timestamp(seg.end)}\n{seg.text}\n"
        )
    return "\n".join(blocks)


def build_bilingual_srt(primary: SubtitleTrack, secondary: SubtitleTrack) -> str:
    """双语 SRT：主语言在上，副语言在下（纯文本，无样式）。"""
    sec_by_time = { (s.start, s.end): s.text for s in secondary.segments }
    blocks = []
    for i, seg in enumerate(primary.segments, 1):
        other = sec_by_time.get((seg.start, seg.end))
        # 时间不完全一致时找重叠最大的
        if other is None:
            other = _best_overlap(seg.start, seg.end, secondary)
        text = f"{seg.text}\n{other}" if other else seg.text
        blocks.append(
            f"{i}\n{fmt_timestamp(seg.start)} --> {fmt_timestamp(seg.end)}\n{text}\n"
        )
    return "\n".join(blocks)


def _best_overlap(start: float, end: float, track: SubtitleTrack) -> str | None:
    best, best_ov = None, 0.0
    for s in track.segments:
        ov = min(end, s.end) - max(start, s.start)
        if ov > best_ov:
            best, best_ov = s.text, ov
    return best if best_ov > 0 else None
