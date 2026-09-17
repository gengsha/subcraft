"""字幕文件解析测试：SRT / WebVTT / ASS 与构建器的往返一致性。"""
from backend.app.models import Segment, SubtitleTrack
from backend.app.services import ass_builder, srt_builder, subtitle_parser


def test_parse_timestamp_variants():
    assert subtitle_parser.parse_timestamp("00:01:02,500") == 62.5
    assert subtitle_parser.parse_timestamp("0:01:02.50") == 62.5      # ASS 百分秒
    assert subtitle_parser.parse_timestamp("01:02.500") == 62.5       # VTT 省略小时
    assert subtitle_parser.parse_timestamp("10:02:03,999") == 36123.999
    assert subtitle_parser.parse_timestamp("无时间") is None


def test_parse_srt():
    text = (
        "1\n00:00:01,000 --> 00:00:03,000\n你好，世界\n\n"
        "2\n00:00:03,500 --> 00:00:05,000\n<i>第二行</i>\n带换行\n\n"
        "3\n00:00:06,000 --> 00:00:07,000\n   \n"      # 空文本段应被丢弃
    )
    segs = subtitle_parser.parse_srt(text)
    assert len(segs) == 2
    assert segs[0] == Segment(start=1.0, end=3.0, text="你好，世界")
    assert segs[1].text == "第二行\n带换行"            # HTML 标签被清掉，换行保留


def test_parse_vtt_skips_header_and_note():
    text = (
        "WEBVTT\n\nNOTE\n这是一段注释\n\n"
        "00:00:01.000 --> 00:00:02.000 position:50%\n第一句\n\n"
        "00:02.000 --> 00:03.000\n第二句\n"
    )
    segs = subtitle_parser.parse_vtt(text)
    assert [s.text for s in segs] == ["第一句", "第二句"]
    assert segs[0].start == 1.0


def test_parse_ass_strips_override_tags():
    text = (
        "[Script Info]\nScriptType: v4.00+\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Main,Microsoft YaHei,48\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Comment: 0,0:00:00.00,0:00:01.00,Main,,0,0,0,,注释行应被忽略\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Main,,0,0,0,,{\\fnArial\\fs40}主文本\\N{\\fs28}副文本\n"
        "Dialogue: 0,0:00:04.00,0:00:05.00,Main,,0,0,0,,含逗号, 的句子\n"
    )
    segs = subtitle_parser.parse_ass(text)
    assert len(segs) == 2
    assert segs[0].text == "主文本\n副文本"
    assert segs[1].text == "含逗号, 的句子"            # Text 列含逗号不能被截断
    assert segs[0].start == 1.0 and segs[0].end == 3.0


def test_parse_ass_custom_format_order():
    """Format 列顺序不同也要按名取列。"""
    text = (
        "[Events]\nFormat: Start, End, Text, Style\n"
        "Dialogue: 0:00:02.00,0:00:03.00,自定义顺序,Main\n"
    )
    segs = subtitle_parser.parse_ass(text)
    assert segs[0].text == "自定义顺序" and segs[0].start == 2.0


def test_parse_file_dispatch_and_sort(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:05,000 --> 00:00:06,000\n后\n\n2\n00:00:01,000 --> 00:00:02,000\n先\n",
                   encoding="utf-8-sig")
    segs = subtitle_parser.parse_file(srt)
    assert [s.text for s in segs] == ["先", "后"]       # 按开始时间排序

    # 扩展名是 .srt 但内容其实是 ASS → 兜底解析
    weird = tmp_path / "b.srt"
    weird.write_text("[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Main,,0,0,0,,其实是ASS\n",
                     encoding="utf-8")
    assert subtitle_parser.parse_file(weird)[0].text == "其实是ASS"


def test_parse_file_errors(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        subtitle_parser.parse_file(tmp_path / "不存在.srt")
    empty = tmp_path / "empty.srt"
    empty.write_text("随便写点没有时间轴的东西", encoding="utf-8")
    with pytest.raises(ValueError):
        subtitle_parser.parse_file(empty)


def test_srt_roundtrip():
    """build_srt 写出的内容再解析回来，段数/时间/文本一致。"""
    track = SubtitleTrack(id="t", language="zh", segments=[
        Segment(start=0.0, end=1.234, text="第一句"),
        Segment(start=2.0, end=3.5, text="第二句\n带换行"),
    ])
    segs = subtitle_parser.parse_srt(srt_builder.build_srt(track))
    assert [(s.start, s.end, s.text) for s in segs] == [
        (0.0, 1.234, "第一句"), (2.0, 3.5, "第二句\n带换行"),
    ]


def test_ass_roundtrip():
    """build_ass（含双语行内覆盖）写出的内容再解析回来文本一致。"""
    tracks = [
        SubtitleTrack(id="a", language="zh", segments=[Segment(start=0.0, end=2.0, text="你好")]),
        SubtitleTrack(id="b", language="en", role="translation",
                      segments=[Segment(start=0.0, end=2.0, text="Hello")]),
    ]
    mono = subtitle_parser.parse_ass(ass_builder.build_ass([tracks[0]]))
    assert mono[0].text == "你好"

    bi = subtitle_parser.parse_ass(ass_builder.build_ass(tracks, bilingual=True, primary_id="a"))
    assert bi[0].text == "你好\nHello"                 # 双语合并为一段两行
