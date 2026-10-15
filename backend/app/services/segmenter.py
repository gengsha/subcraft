"""字幕断句：把 Whisper 过长的识别段切成适合上屏的短句。

Whisper 的一个 segment 经常长达十几秒、两三行，直接上屏阅读压力大。
这里按「字幕可读性」二次切分：

- 长度上限按字符计，CJK（中日韩）字符记 1，其余字符记 0.5，
  默认上限 21（约等于一行 21 个汉字或 42 个英文字符）；
- 时长上限默认 7 秒；
- 切分点优先选句末标点，其次逗号类标点，再次词间停顿最长处；
- 有词级时间戳（faster-whisper word_timestamps）时按词切，时间精确；
  没有时（OpenAI API segment 粒度）按标点切，时间按字数比例插值。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..models import Segment

DEFAULT_MAX_UNITS = 21.0
DEFAULT_MAX_DURATION = 7.0
MIN_PIECE_UNITS = 4.0  # 切出来的碎片不能太短

_STRONG = set("。！？!?…；;")
_WEAK = set("，、,：:—")


@dataclass
class Word:
    start: float
    end: float
    text: str  # 保留原始前导空格（faster-whisper 的英文词带前导空格）


def char_units(ch: str) -> float:
    if ch.isspace():
        return 0.5
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    return 0.5


def text_units(text: str) -> float:
    return sum(char_units(c) for c in text.strip())


def _join(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


def _break_score(prev: Word, nxt: Word) -> float:
    """在 prev 与 nxt 之间断开的「好坏」分数，越大越适合断开。"""
    tail = prev.text.strip()[-1:] if prev.text.strip() else ""
    score = 0.0
    if tail in _STRONG:
        score += 3.0
    elif tail in _WEAK:
        score += 2.0
    score += min(max(nxt.start - prev.end, 0.0), 1.0) * 2.0  # 停顿越长越适合断
    return score


def split_words(
    words: list[Word],
    max_units: float = DEFAULT_MAX_UNITS,
    max_duration: float = DEFAULT_MAX_DURATION,
) -> list[Segment]:
    """按词级时间戳递归二分，直到每段都满足长度与时长上限。"""
    words = [w for w in words if w.text.strip()]
    if not words:
        return []
    text = _join(words)
    dur = words[-1].end - words[0].start
    if len(words) == 1 or (text_units(text) <= max_units and dur <= max_duration):
        return [Segment(start=round(words[0].start, 3), end=round(words[-1].end, 3), text=text)]

    total = text_units(text)
    best_i, best_score = None, float("-inf")
    acc = 0.0
    for i in range(1, len(words)):
        acc += text_units(words[i - 1].text)
        left, right = acc, total - acc
        if left < MIN_PIECE_UNITS or right < MIN_PIECE_UNITS:
            continue
        # 标点/停顿得分 - 偏离中点的惩罚（保持两段长度均衡）
        balance = abs(left - right) / total
        score = _break_score(words[i - 1], words[i]) - balance * 2.5
        if score > best_score:
            best_i, best_score = i, score
    if best_i is None:  # 太短无法再分（如单个超长词），原样保留
        best_i = len(words) // 2
    return split_words(words[:best_i], max_units, max_duration) + split_words(
        words[best_i:], max_units, max_duration
    )


_TOKEN_RE = re.compile(r"[A-Za-z0-9\u00C0-\u024F'’\-]+[^\sA-Za-z0-9\u00C0-\u024F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]*\s*|\S[。！？!?…；;，、,：:」』”）)]*\s*")


def split_segment_by_text(
    seg: Segment,
    max_units: float = DEFAULT_MAX_UNITS,
    max_duration: float = DEFAULT_MAX_DURATION,
) -> list[Segment]:
    """无词级时间戳时：按标点拆分子句，时间按字数比例分配。"""
    if text_units(seg.text) <= max_units and seg.end - seg.start <= max_duration:
        return [seg]
    # 拉丁文按词（连同其后的标点与空格）、CJK 按字切成伪词，再交给 split_words 挑断点
    clauses = [c for c in _TOKEN_RE.findall(seg.text) if c.strip()]
    total = sum(text_units(c) for c in clauses) or 1.0
    span = seg.end - seg.start
    t = seg.start
    pseudo: list[Word] = []
    for c in clauses:
        d = span * text_units(c) / total
        pseudo.append(Word(start=t, end=t + d, text=c))
        t += d
    out = split_words(pseudo, max_units, max_duration)
    if out:
        out[-1] = Segment(start=out[-1].start, end=round(seg.end, 3), text=out[-1].text)
    return out


def resegment(
    segments: list[Segment],
    words_per_segment: list[list[Word]] | None = None,
    max_units: float = DEFAULT_MAX_UNITS,
    max_duration: float = DEFAULT_MAX_DURATION,
) -> list[Segment]:
    """统一入口：有词级时间戳用词，否则用文本比例。max_units<=0 时不切分。"""
    if max_units <= 0:
        return list(segments)
    out: list[Segment] = []
    for i, seg in enumerate(segments):
        words = words_per_segment[i] if words_per_segment and i < len(words_per_segment) else None
        if words:
            out.extend(split_words(words, max_units, max_duration))
        else:
            out.extend(split_segment_by_text(seg, max_units, max_duration))
    return out
