"""ASS (Advanced SubStation Alpha) 字幕生成：每种语言独立样式，支持双语单文件。"""
from __future__ import annotations

from ..models import SubtitleStyle, SubtitleTrack
from .srt_builder import _best_overlap


def fmt_time(seconds: float) -> str:
    cs = round(seconds * 100)
    h, cs = divmod(cs, 3600_00)
    m, cs = divmod(cs, 60_00)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def ass_color(rgb_hex: str) -> str:
    """#RRGGBB -> ASS &HBBGGRR"""
    h = rgb_hex.lstrip("#")
    if len(h) != 6:
        return "&H00FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b.upper()}{g.upper()}{r.upper()}"


def style_line(name: str, st: SubtitleStyle) -> str:
    bold = -1 if st.bold else 0
    italic = -1 if st.italic else 0
    return (
        f"Style: {name},{st.font_name},{st.font_size},"
        f"{ass_color(st.primary_color)},{ass_color(st.primary_color)},"
        f"{ass_color(st.outline_color)},{ass_color(st.back_color)},"
        f"{bold},{italic},0,0,100,100,0,0,1,{st.outline},{st.shadow},"
        f"{st.alignment},{st.margin_l},{st.margin_r},{st.margin_v},1"
    )


def _escape(text: str) -> str:
    return text.replace("\n", "\\N").replace("{", "(").replace("}", ")")


def _pos_prefix(st: SubtitleStyle) -> str:
    r"""中心点定位前缀：pos_x/pos_y 设置时用 \an5\pos 让锚点为字幕块中心。"""
    if st.pos_x is None or st.pos_y is None:
        return ""
    return f"{{\\an5\\pos({st.pos_x:.0f},{st.pos_y:.0f})}}"


def _inline_override(st: SubtitleStyle) -> str:
    """行内样式覆盖标签：让双语第二行拥有独立字体。"""
    bold = 1 if st.bold else 0
    italic = 1 if st.italic else 0
    return (
        f"{{\\fn{st.font_name}\\fs{st.font_size}\\b{bold}\\i{italic}"
        f"\\c{ass_color(st.primary_color)}\\3c{ass_color(st.outline_color)}"
        f"\\bord{st.outline}\\shd{st.shadow}}}"
    )


HEADER_TMPL = """[Script Info]
Title: SubCraft
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_w}
PlayResY: {play_h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(
    tracks: list[SubtitleTrack],
    play_w: int = 1920,
    play_h: int = 1080,
    bilingual: bool = False,
    primary_id: str | None = None,
) -> str:
    """生成 ASS 文本。bilingual=True 时把主/副语言合并到同一行（副语言用行内覆盖标签）。"""
    if not tracks:
        raise ValueError("至少需要一个字幕轨")

    if bilingual and len(tracks) >= 2:
        primary = next((t for t in tracks if t.id == primary_id), tracks[0])
        secondary = next(t for t in tracks if t.id != primary.id)
        styles = "\n".join([
            style_line("Main", primary.style),
            style_line("Sub", secondary.style),
        ])
        pos_main = _pos_prefix(primary.style)
        pos_sub = _pos_prefix(secondary.style)
        # 任一轨设置了中心点 → 拆成两条独立 Dialogue，各语言可单独定位拖动；
        # 都没设置时保持单 Dialogue 叠放（副语言行内覆盖，紧跟主语言换行）
        split = bool(pos_main or pos_sub)
        lines = []
        for seg in primary.segments:
            other = _best_overlap(seg.start, seg.end, secondary)
            timing = f"{fmt_time(seg.start)},{fmt_time(seg.end)}"
            if not split:
                text = _escape(seg.text)
                if other:
                    text += "\\N" + _inline_override(secondary.style) + _escape(other)
                lines.append(f"Dialogue: 0,{timing},Main,,0,0,0,,{text}")
            else:
                lines.append(f"Dialogue: 0,{timing},Main,,0,0,0,,{pos_main}{_escape(seg.text)}")
                if other:
                    lines.append(f"Dialogue: 0,{timing},Sub,,0,0,0,,{pos_sub}{_escape(other)}")
        return HEADER_TMPL.format(play_w=play_w, play_h=play_h, styles=styles) + "\n".join(lines) + "\n"

    # 单语：每轨一个样式，事件按时间排序
    styles = "\n".join(style_line(_style_name(t), t.style) for t in tracks)
    events = []
    for t in tracks:
        for seg in t.segments:
            events.append((
                seg.start,
                f"Dialogue: 0,{fmt_time(seg.start)},{fmt_time(seg.end)},{_style_name(t)},,0,0,0,,{_pos_prefix(t.style)}{_escape(seg.text)}",
            ))
    events.sort(key=lambda e: e[0])
    return HEADER_TMPL.format(play_w=play_w, play_h=play_h, styles=styles) + "\n".join(e[1] for e in events) + "\n"


def _style_name(track: SubtitleTrack) -> str:
    return f"SubCraft_{track.language}_{track.role}"
