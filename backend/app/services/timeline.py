"""时间轴操作：拆分 / 合并 / 平移缩放 / 镜头切点吸附 / 合理性检查。

纯函数，MCP 工具与 CLI `retime` 共用；所有函数返回新列表，不修改入参。
"""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

from ..models import Segment, SubtitleTrack
from .segmenter import char_units, text_units

MIN_DURATION = 0.3       # 短于此时长基本看不清
DEFAULT_MAX_DURATION = 7.0
CJK_MAX_CPS = 9.0        # 中日韩：每秒 9 字（Netflix 中文规范）
LATIN_MAX_CPS = 10.0     # 拉丁文字按 0.5 单位计，即每秒 20 个字母（Netflix 英文规范）
DEFAULT_MAX_CPS = 0.0    # 0 = 按文字自动选上面两档
GAP = 0.04               # 吸附切点时留出的最小间隔（约 1 帧）

_CJK_RE = re.compile(r"[\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]")


def _r(t: float) -> float:
    return round(max(t, 0.0), 3)


def _copy(segs: list[Segment]) -> list[Segment]:
    return [Segment(start=s.start, end=s.end, text=s.text) for s in segs]


# ------------------------------------------------------------------ 检查

def check(segs: list[Segment], max_cps: float = DEFAULT_MAX_CPS,
          max_duration: float = DEFAULT_MAX_DURATION, indexes: set[int] | None = None) -> list[dict]:
    """返回问题列表：overlap 重叠 / too_short 过短 / too_long 过长 / too_fast 阅读速度过快。

    indexes 给定时只检查这些段（及其与相邻段的重叠），用于编辑后的局部校验。
    """
    issues: list[dict] = []
    for i, s in enumerate(segs):
        if indexes is not None and i not in indexes and (i + 1) not in indexes:
            continue
        dur = s.end - s.start
        if indexes is None or i in indexes:
            if dur < MIN_DURATION:
                issues.append({"index": i, "type": "too_short", "detail": f"仅 {dur:.2f}s"})
            if max_duration and dur > max_duration:
                issues.append({"index": i, "type": "too_long", "detail": f"{dur:.2f}s > {max_duration}s"})
            text = s.text.replace("\n", "")
            units = text_units(text)
            limit = max_cps or (CJK_MAX_CPS if len(_CJK_RE.findall(text)) * 2 >= len(text.replace(" ", ""))
                                else LATIN_MAX_CPS)
            if dur > 0 and units / dur > limit:
                issues.append({"index": i, "type": "too_fast",
                               "detail": f"{units / dur:.1f} 单位/秒 > {limit}（汉字计 1，字母计 0.5）"})
        if i + 1 < len(segs) and segs[i + 1].start < s.end - 1e-3:
            issues.append({"index": i, "type": "overlap",
                           "detail": f"与下一段重叠 {s.end - segs[i + 1].start:.2f}s"})
    return issues


def fix_overlaps(segs: list[Segment]) -> tuple[list[Segment], int]:
    """把每段结束时间截到下一段开始前（不动开始时间）；返回 (新列表, 修复数)。"""
    out = _copy(segs)
    fixed = 0
    for i in range(len(out) - 1):
        nxt = out[i + 1].start
        if out[i].end > nxt and nxt - out[i].start >= MIN_DURATION / 2:
            out[i].end = _r(nxt)
            fixed += 1
    return out, fixed


# ------------------------------------------------------------------ 拆分 / 合并

def _proportional_text_split(text: str, ratio: float) -> tuple[str, str]:
    """按比例找最接近的断点，优先标点与空格，避免把英文单词切开。"""
    text = text.strip()
    total = text_units(text)
    if total <= 0 or len(text) < 2:
        return text, ""
    target = total * min(max(ratio, 0.05), 0.95)
    acc, best, best_score = 0.0, 1, float("inf")
    for i, ch in enumerate(text[:-1]):
        acc += char_units(ch)
        nxt = text[i + 1]
        if ch.isalnum() and nxt.isalnum() and not (_CJK_RE.match(ch) or _CJK_RE.match(nxt)):
            continue  # 单词中间不切
        score = abs(acc - target)
        if ch in "。！？!?…；;，、,：:" or ch.isspace():
            score -= total * 0.08  # 标点/空格处优先
        if score < best_score:
            best, best_score = i + 1, score
    return text[:best].strip(), text[best:].strip()


def split(segs: list[Segment], index: int, at_time: float | None = None,
          text: str | None = None) -> list[Segment]:
    """把第 index 段拆成两段。

    text: 用 "|" 标出断点，如 "前半句|后半句"（推荐，最精确）；也可只给第一段的文字前缀。
    at_time: 拆分时间点（绝对秒）；省略时按文字长度比例推算。
    两者都省略时，在文字中点附近的标点/空格处、按比例时间拆开。
    """
    if not 0 <= index < len(segs):
        raise ValueError(f"index 越界（0-{len(segs) - 1}）")
    seg = segs[index]
    full = seg.text.strip()
    dur = seg.end - seg.start
    if at_time is not None and not (seg.start < at_time < seg.end):
        raise ValueError(f"at_time {at_time} 不在该段时间范围 ({seg.start}, {seg.end}) 内")

    if text is not None and "|" in text:
        first, second = (p.strip() for p in text.split("|", 1))
    elif text:
        if not full.startswith(text.strip()):
            raise ValueError("text 不是该段文字的前缀；如需同时改字，请用 '前半|后半' 写法")
        first, second = text.strip(), full[len(text.strip()):].strip()
    elif at_time is not None:
        first, second = _proportional_text_split(full, (at_time - seg.start) / dur if dur else 0.5)
    else:
        first, second = _proportional_text_split(full, 0.5)
    if not first or not second:
        raise ValueError("拆分后有一段为空，请调整断点")

    if at_time is None:
        u1, u2 = text_units(first), text_units(second)
        at_time = seg.start + dur * (u1 / (u1 + u2) if u1 + u2 else 0.5)
    out = _copy(segs)
    out[index:index + 1] = [Segment(start=_r(seg.start), end=_r(at_time), text=first),
                            Segment(start=_r(at_time), end=_r(seg.end), text=second)]
    return out


def merge(segs: list[Segment], first: int, last: int) -> list[Segment]:
    """把 first..last（含）合并为一段；中英文自动决定是否加空格。"""
    if not (0 <= first < last < len(segs)):
        raise ValueError(f"合并范围无效：{first}-{last}（共 {len(segs)} 段，需 first < last）")
    parts = [s.text.strip() for s in segs[first:last + 1] if s.text.strip()]
    text = ""
    for p in parts:
        if text and not (_CJK_RE.match(text[-1]) or _CJK_RE.match(p[0])):
            text += " "
        text += p
    out = _copy(segs)
    out[first:last + 1] = [Segment(start=segs[first].start,
                                   end=max(s.end for s in segs[first:last + 1]), text=text)]
    return out


# ------------------------------------------------------------------ 平移 / 缩放

def shift(segs: list[Segment], offset: float = 0.0, scale: float = 1.0,
          first: int = 0, last: int | None = None, from_time: float | None = None) -> tuple[list[Segment], int]:
    """整轨或区间平移/缩放：t' = t * scale + offset。

    first/last 指定段序号区间（含）；from_time 给定时只影响开始时间 >= from_time 的段（如中间插了片头）。
    结果小于 0 的时间截到 0。返回 (新列表, 受影响段数)。
    """
    if scale <= 0:
        raise ValueError("scale 必须大于 0")
    last = len(segs) - 1 if last is None else last
    out = _copy(segs)
    n = 0
    for i, s in enumerate(out):
        if not first <= i <= last or (from_time is not None and s.start < from_time):
            continue
        s.start, s.end = _r(s.start * scale + offset), _r(s.end * scale + offset)
        n += 1
    out = [s for s in out if s.end > s.start]
    out.sort(key=lambda s: (s.start, s.end))
    return out, n


# ------------------------------------------------------------------ 镜头切点

_cuts_cache: dict[tuple, list[float]] = {}
_cuts_lock = threading.Lock()


def detect_cuts(ffmpeg: str, video: str, threshold: float = 0.3) -> list[float]:
    """用 ffmpeg 场景检测找出镜头切换时间点（秒）。threshold 越小越敏感（0.2~0.5）。

    先缩到 320 宽再检测（长视频快很多，结果基本不变）；按 路径+修改时间+阈值 缓存。
    """
    p = Path(video)
    key = (str(p.resolve()), p.stat().st_mtime if p.exists() else 0, round(float(threshold), 3))
    with _cuts_lock:
        if key in _cuts_cache:
            return list(_cuts_cache[key])
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", video, "-an", "-sn", "-dn",
         "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"场景检测失败: {proc.stderr[-800:]}")
    cuts = sorted({round(float(m), 3) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr)})
    with _cuts_lock:
        if len(_cuts_cache) > 32:
            _cuts_cache.clear()
        _cuts_cache[key] = cuts
    return list(cuts)


def snap_to_cuts(segs: list[Segment], cuts: list[float], tolerance: float = 0.5) -> tuple[list[Segment], list[dict]]:
    """让字幕不跨镜头：结束时间刚越过切点（tolerance 内）就收回到切点前；
    开始时间略早于切点（tolerance 内）就推到切点上。拆不开的长跨越不处理（交给 split）。
    """
    out = _copy(segs)
    before = [(s.start, s.end) for s in out]
    # 第一遍：处理刚好越过切点的起止
    for s in out:
        for c in cuts:
            if s.start < c < s.end:
                if s.end - c <= tolerance and c - s.start >= MIN_DURATION:
                    s.end = _r(c - GAP)
                elif c - s.start <= tolerance and s.end - c >= MIN_DURATION:
                    s.start = _r(c)
    # 第二遍：结束点离后面的切点很近且下一段在切点之后才开始 → 延到切点前，字幕随镜头一起消失更自然
    for i, s in enumerate(out):
        for c in cuts:
            if 0 < c - s.end <= tolerance and (i + 1 >= len(out) or out[i + 1].start >= c - 1e-3):
                s.end = _r(c - GAP)
                break
    changes = [{"index": i, "before": list(b), "after": [s.start, s.end]}
               for i, (s, b) in enumerate(zip(out, before)) if (s.start, s.end) != b]
    return out, changes


def crossing_cuts(segs: list[Segment], cuts: list[float], margin: float = 0.3) -> list[dict]:
    """列出跨越切点、且切点两侧都超过 margin 的段：这些需要 split 才能不跨镜头。"""
    found = []
    for i, s in enumerate(segs):
        inner = [c for c in cuts if s.start + margin < c < s.end - margin]
        if inner:
            found.append({"index": i, "cuts": inner, "text": s.text})
    return found


# ------------------------------------------------------------------ 多轨对齐

def aligned_with(tracks: list[SubtitleTrack], target: SubtitleTrack) -> list[SubtitleTrack]:
    """找出与 target 逐段时间完全一致的其他轨（如 AI/接口翻译出的译文轨），结构操作要同步到它们。"""
    segs = target.segments
    out = []
    for t in tracks:
        if t.id == target.id or len(t.segments) != len(segs):
            continue
        if all(abs(a.start - b.start) < 1e-3 and abs(a.end - b.end) < 1e-3 for a, b in zip(t.segments, segs)):
            out.append(t)
    return out
