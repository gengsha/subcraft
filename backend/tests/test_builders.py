"""SRT/ASS 生成器单元测试。"""
from backend.app.models import Segment, SubtitleStyle, SubtitleTrack
from backend.app.services import ass_builder, srt_builder


def make_track(lang: str, role: str = "source") -> SubtitleTrack:
    return SubtitleTrack(
        id=f"t-{lang}", language=lang, role=role,
        segments=[
            Segment(start=0.5, end=2.0, text="你好世界"),
            Segment(start=2.5, end=4.25, text="第二行\n换行"),
        ],
        style=SubtitleStyle(font_name="Microsoft YaHei", font_size=40, primary_color="#FF0000", bold=True),
    )


def test_srt_format():
    srt = srt_builder.build_srt(make_track("zh"))
    assert "1\n00:00:00,500 --> 00:00:02,000\n你好世界" in srt
    assert "00:00:02,500 --> 00:00:04,250" in srt


def test_bilingual_srt():
    main = make_track("zh")
    sub = make_track("en", "translation")
    sub.segments[0].text = "Hello world"
    sub.segments[1].text = "Second line"
    srt = srt_builder.build_bilingual_srt(main, sub)
    assert "你好世界\nHello world" in srt


def test_ass_color():
    assert ass_builder.ass_color("#FF0000") == "&H000000FF"
    assert ass_builder.ass_color("#00FF00") == "&H0000FF00"


def test_ass_structure():
    ass = ass_builder.build_ass([make_track("zh")], 1920, 1080)
    assert "[V4+ Styles]" in ass
    assert "Style: SubCraft_zh_source,Microsoft YaHei,40,&H000000FF" in ass
    assert ",-1,0,0,0,100,100,0,0,1,2.0,0.0,2,20,20,30,1" in ass  # bold=-1 及边距等
    assert "Dialogue: 0,0:00:00.50,0:00:02.00" in ass
    assert "第二行\\N换行" in ass  # 换行转义


def test_ass_bilingual_inline_override():
    main = make_track("zh")
    sub = make_track("en", "translation")
    sub.style = SubtitleStyle(font_name="Arial", font_size=24)
    ass = ass_builder.build_ass([main, sub], bilingual=True, primary_id="t-zh")
    assert "Style: Main," in ass and "Style: Sub," in ass
    assert "\\N{\\fnArial\\fs24" in ass  # 副语言行内覆盖标签
    assert "Hello world" not in ass  # 副轨道文本未被替换过（默认文本）
    assert "Dialogue:" in ass


def test_ass_pos_center_mode():
    # 中心点坐标模式：Dialogue 行首插入 \an5\pos；双语时主轨生效
    track = make_track("zh")
    track.style.pos_x, track.style.pos_y = 640, 300
    ass = ass_builder.build_ass([track], 1280, 720)
    assert "{\\an5\\pos(640,300)}你好世界" in ass

    main = make_track("zh")
    main.style.pos_x, main.style.pos_y = 100, 200
    sub = make_track("en", "translation")
    bi = ass_builder.build_ass([main, sub], bilingual=True, primary_id="t-zh")
    assert "{\\an5\\pos(100,200)}你好世界" in bi

    # 未设置 pos 时不应出现覆盖标签
    assert "\\pos(" not in ass_builder.build_ass([make_track("zh")], 1280, 720)


def test_ass_bilingual_split_independent_pos():
    # 双语时任一轨设置中心点 → 拆成独立 Main/Sub Dialogue，各自定位
    def track(lang: str, role: str, text: str, px: int | None, py: int | None) -> SubtitleTrack:
        return SubtitleTrack(
            id=f"t-{lang}", language=lang, role=role,
            segments=[Segment(start=0.5, end=2.0, text=text)],
            style=SubtitleStyle(font_name="Microsoft YaHei", pos_x=px, pos_y=py),
        )

    main = track("zh", "source", "中文行", 640, 300)
    sub = track("en", "translation", "english line", 500, 420)
    ass = ass_builder.build_ass([main, sub], bilingual=True, primary_id="t-zh")
    assert "Dialogue: 0,0:00:00.50,0:00:02.00,Main,,0,0,0,,{\\an5\\pos(640,300)}中文行" in ass
    assert "Dialogue: 0,0:00:00.50,0:00:02.00,Sub,,0,0,0,,{\\an5\\pos(500,420)}english line" in ass
    assert "\\N" not in ass  # 拆分模式下不再行内拼接

    # 只有主轨有 pos：主轨独立定位，副轨保持默认边距位置
    main2 = track("zh", "source", "中文行", 640, 300)
    sub2 = track("en", "translation", "english line", None, None)
    ass2 = ass_builder.build_ass([main2, sub2], bilingual=True, primary_id="t-zh")
    assert "{\\an5\\pos(640,300)}中文行" in ass2
    assert "Dialogue: 0,0:00:00.50,0:00:02.00,Sub,,0,0,0,,english line" in ass2

    # 都没有 pos：保持单 Dialogue 叠放
    ass3 = ass_builder.build_ass(
        [track("zh", "source", "中文行", None, None), track("en", "translation", "english line", None, None)],
        bilingual=True, primary_id="t-zh",
    )
    assert "中文行\\N" in ass3


def test_ass_time_format():
    assert ass_builder.fmt_time(3661.25) == "1:01:01.25"
