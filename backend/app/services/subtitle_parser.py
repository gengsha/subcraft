"""字幕文件解析：SRT / WebVTT / ASS(SSA) → 字幕段列表。

供 MCP 工具与「导入已有字幕」场景复用。解析结果统一为 `Segment(start, end, text)`，
时间单位为秒；文本已去除 ASS 覆盖标签与 HTML 标签，多行以 `\n` 连接。
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import Segment

SUPPORTED_SUFFIXES = (".srt", ".vtt", ".ass", ".ssa")

# 时:分:秒.毫秒；小时位可省略（WebVTT 允许 mm:ss.mmm），分隔符兼容 , 与 .
_TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")
_ASS_TAG_RE = re.compile(r"\{[^{}]*\}")
_ASS_DRAWING_RE = re.compile(r"\\p[1-9].*?(?:\\p0|$)", re.S)
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
# ASS 默认 Dialogue 字段顺序（文件缺少 Format 行时兜底）
_ASS_DEFAULT_FORMAT = ["layer", "start", "end", "style", "name",
                       "marginl", "marginr", "marginv", "effect", "text"]


def parse_timestamp(text: str) -> float | None:
    """把 `00:01:02,500` / `0:01:02.50` / `01:02.500` 解析为秒；无法识别返回 None。"""
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int((frac + "000")[:3]) / 1000


def clean_ass_text(text: str) -> str:
    """去掉 ASS 覆盖标签/绘图指令，换行标签转为真实换行。"""
    t = _ASS_TAG_RE.sub("", text or "")
    t = _ASS_DRAWING_RE.sub("", t)
    t = t.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    t = t.replace("\\:", ":").replace("\\{", "{").replace("\\}", "}")
    return t.strip()


def _normalize(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _split_blocks(text: str) -> list[list[str]]:
    """按空行切块（SRT / VTT 通用）。"""
    return [b.split("\n") for b in re.split(r"\n\s*\n", _normalize(text).strip()) if b.strip()]


def _make_segment(start: float, end: float, text: str) -> Segment | None:
    text = _HTML_TAG_RE.sub("", text).strip()
    if not text:
        return None
    if end <= start:            # 容错：结束不晚于开始时给一个最小时长，避免下游生成非法时间码
        end = start + 0.1
    return Segment(start=round(start, 3), end=round(end, 3), text=text)


def parse_srt(text: str) -> list[Segment]:
    """解析 SRT（也兼容缺少序号的松散写法）。"""
    out: list[Segment] = []
    for lines in _split_blocks(text):
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        left, _, right = lines[idx].partition("-->")
        start, end = parse_timestamp(left), parse_timestamp(right)
        if start is None or end is None:
            continue
        seg = _make_segment(start, end, "\n".join(lines[idx + 1:]))
        if seg:
            out.append(seg)
    return out


def parse_vtt(text: str) -> list[Segment]:
    """解析 WebVTT（跳过 WEBVTT 头、NOTE 块与 cue setting）。"""
    body = _normalize(text)
    body = re.sub(r"NOTE\n.*?(?:\n\n|\Z)", "\n", body, flags=re.S)
    return parse_srt(body)


def parse_ass(text: str) -> list[Segment]:
    """解析 ASS/SSA 的 [Events] 段（忽略 Comment 行与样式定义）。"""
    fmt = list(_ASS_DEFAULT_FORMAT)
    out: list[Segment] = []
    in_events = False
    for raw in _normalize(text).split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("["):
            in_events = line.lower().startswith("[events]")
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fmt = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        parts = line.split(":", 1)[1].split(",", max(len(fmt) - 1, 1))
        if len(parts) < len(fmt):
            continue
        row = dict(zip(fmt, parts))
        start, end = parse_timestamp(row.get("start", "")), parse_timestamp(row.get("end", ""))
        if start is None or end is None:
            continue
        seg = _make_segment(start, end, clean_ass_text(row.get("text", "")))
        if seg:
            out.append(seg)
    return out


def parse_file(path: str | Path) -> list[Segment]:
    """按扩展名解析字幕文件，返回按开始时间排序的字幕段。

    扩展名与内容不符时自动兜底重试；解析不出任何段落时抛出 ValueError。
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"字幕文件不存在: {p}")
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    suffix = p.suffix.lower()
    if suffix in (".ass", ".ssa"):
        segments = parse_ass(text)
    elif suffix == ".vtt":
        segments = parse_vtt(text)
    else:
        segments = parse_srt(text)
        if not segments:                 # 扩展名是 .srt/.txt 但内容其实是 ASS
            segments = parse_ass(text)
    if not segments:
        raise ValueError(f"未能从 {p.name} 解析出字幕段（支持 {', '.join(SUPPORTED_SUFFIXES)}）")
    return sorted(segments, key=lambda s: (s.start, s.end))
