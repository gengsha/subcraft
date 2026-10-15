import pytest

from backend.app.models import Segment
from backend.app.services import timeline


def segs(*items):
    return [Segment(start=a, end=b, text=t) for a, b, t in items]


def test_split_with_marker_and_time():
    s = segs((0, 4, "Hello world, this is a test"))
    out = timeline.split(s, 0, 2.5, "Hello world,|this is a test")
    assert [(x.start, x.end, x.text) for x in out] == [(0, 2.5, "Hello world,"), (2.5, 4, "this is a test")]
    assert s[0].text == "Hello world, this is a test"           # 入参不被修改


def test_split_auto_prefers_punctuation_and_keeps_words():
    out = timeline.split(segs((0, 4, "今天天气很好，我们出去走走吧")), 0)
    assert out[0].text == "今天天气很好，" and out[1].text == "我们出去走走吧"
    out = timeline.split(segs((0, 4, "automatic speech recognition")), 0, at_time=1.0)
    assert out[0].text + " " + out[1].text == "automatic speech recognition"


def test_split_errors():
    s = segs((0, 2, "abc def"))
    with pytest.raises(ValueError):
        timeline.split(s, 0, at_time=3)
    with pytest.raises(ValueError):
        timeline.split(s, 0, text="xyz")
    with pytest.raises(ValueError):
        timeline.split(s, 5)


def test_merge_spacing():
    out = timeline.merge(segs((0, 1, "Hello"), (1, 2, "world"), (2, 3, "你好"), (3, 4, "世界")), 0, 3)
    assert out[0].text == "Hello world你好世界" and (out[0].start, out[0].end) == (0, 4)


def test_shift_scale_from_time_and_clamp():
    s = segs((0.1, 1, "a"), (5, 6, "b"))
    out, n = timeline.shift(s, offset=-0.5)
    assert n == 2 and out[0].start == 0 and out[1].start == 4.5
    out, n = timeline.shift(s, offset=1, from_time=2)
    assert n == 1 and out[0].start == 0.1 and out[1].start == 6
    out, _ = timeline.shift(s, scale=2)
    assert (out[1].start, out[1].end) == (10, 12)


def test_snap_to_cuts():
    s = segs((0, 3.1, "a"), (3.5, 5.9, "b"), (6.2, 8, "c"), (9, 14, "long"))
    out, changes = timeline.snap_to_cuts(s, [3.0, 6.0, 11.5], tolerance=0.5)
    assert out[0].end == pytest.approx(3.0 - timeline.GAP)     # 越过切点 0.1s → 收回
    assert out[1].end == pytest.approx(6.0 - timeline.GAP)     # 离切点 0.1s → 延到切点
    assert out[2].start == 6.2                                  # 在切点后，不动
    assert timeline.crossing_cuts(out, [3.0, 6.0, 11.5])[0]["index"] == 3
    again, ch2 = timeline.snap_to_cuts(out, [3.0, 6.0, 11.5], tolerance=0.5)
    assert ch2 == []                                            # 幂等


def test_check_and_fix_overlaps():
    s = segs((0, 2, "你好"), (1.5, 1.6, "短"), (2, 3, "这是一句非常非常非常非常长的中文字幕"), (3, 12, "ok"))
    kinds = {(i["index"], i["type"]) for i in timeline.check(s)}
    assert {(0, "overlap"), (1, "too_short"), (2, "too_fast"), (3, "too_long")} <= kinds
    fixed, n = timeline.fix_overlaps(s)
    assert n >= 1 and fixed[0].end == 1.5
    assert not timeline.check(segs((0, 2, "Hello there, friend")))   # 英文按 20 字母/秒，不误报
