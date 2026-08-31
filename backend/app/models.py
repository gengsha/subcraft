"""共享数据模型：字幕段、字幕轨、样式。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Segment(BaseModel):
    start: float  # 秒
    end: float
    text: str


class SubtitleStyle(BaseModel):
    font_name: str = "Microsoft YaHei"
    font_size: int = 48
    primary_color: str = "#FFFFFF"   # #RRGGBB
    outline_color: str = "#000000"
    back_color: str = "#000000"      # 阴影/底色
    bold: bool = False
    italic: bool = False
    outline: float = 2.0
    shadow: float = 0.0
    alignment: int = 2               # ASS 对齐 1-9 (2=底部居中)
    margin_v: int = 30               # 垂直边距(像素)
    margin_l: int = 20               # 左边距(左对齐时为水平位置)
    margin_r: int = 20               # 右边距(右对齐时为水平位置)
    pos_x: float | None = None       # 中心点坐标模式：设置后用 \pos 定位，忽略对齐/边距
    pos_y: float | None = None


class SubtitleTrack(BaseModel):
    id: str
    language: str = "und"            # ISO 码: zh/en/ja/ko/...
    label: str = ""
    role: Literal["source", "translation"] = "source"
    segments: list[Segment] = Field(default_factory=list)
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class MediaInfo(BaseModel):
    path: str
    name: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    size: int = 0


# 常见语言(代码 -> 显示名)，前后端共用
LANGUAGES: dict[str, str] = {
    "auto": "自动检测",
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "ru": "Русский",
    "it": "Italiano",
    "pt": "Português",
    "ar": "العربية",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "hi": "हिन्दी",
    "yue": "粤语",
}
