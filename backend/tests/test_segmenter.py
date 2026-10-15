"""识别断句：长段切分、时间连续、标点优先。"""
from backend.app.models import Segment
from backend.app.services.segmenter import (
    Word, resegment, split_segment_by_text, split_words, text_units,
)


def _check_continuous(parts, start, end):
    assert parts[0].start == start and parts[-1].end == end
    for a, b in zip(parts, parts[1:]):
        assert abs(a.end - b.start) < 1e-6
        assert a.start < a.end


def test_short_segment_untouched():
    seg = Segment(start=1.0, end=2.0, text="你好。")
    assert split_segment_by_text(seg) == [seg]


def test_cjk_split_prefers_punctuation():
    text = "今天我们来聊一聊字幕断句这个问题，因为Whisper识别出来的句子经常很长。尤其是在讲座视频里面，一段可能有十几秒。"
    parts = split_segment_by_text(Segment(start=0.0, end=12.0, text=text))
    assert len(parts) >= 2
    assert "".join(p.text for p in parts) == text
    assert all(text_units(p.text) <= 21 for p in parts)
    assert parts[0].text.endswith("，") or parts[0].text.endswith("。")
    _check_continuous(parts, 0.0, 12.0)


def test_english_split_keeps_words_whole():
    text = ("So today we are going to talk about subtitle segmentation, because the lines "
            "that Whisper produces are often far too long to read comfortably.")
    parts = split_segment_by_text(Segment(start=0.0, end=9.0, text=text))
    assert " ".join(p.text for p in parts) == text
    assert all(text_units(p.text) <= 21 for p in parts)
    _check_continuous(parts, 0.0, 9.0)


def test_word_timestamps_split_at_pause():
    words = [Word(i * 0.4, i * 0.4 + 0.3, f" w{i}") for i in range(10)]
    # 第 5 个词后有 1.5 秒停顿
    words += [Word(5.5 + i * 0.4, 5.5 + i * 0.4 + 0.3, f" v{i}") for i in range(10)]
    parts = split_words(words, max_units=16, max_duration=7)
    assert parts[0].text.endswith("w9") and parts[1].text.startswith("v0")
    assert parts[0].end == round(words[9].end, 3)


def test_duration_limit():
    words = [Word(i * 1.0, i * 1.0 + 0.9, f"字{i}") for i in range(12)]
    parts = split_words(words, max_units=100, max_duration=7)
    assert all(p.end - p.start <= 7 for p in parts)


def test_disabled_when_zero():
    segs = [Segment(start=0, end=20, text="很长" * 40)]
    assert resegment(segs, max_units=0) == segs


def test_english_prefers_break_before_conjunction():
    ws = "Hello everyone and welcome back to the channel today".split()
    words = [Word(i * 0.3, i * 0.3 + 0.25, " " + w) for i, w in enumerate(ws)]
    parts = split_words(words, max_units=14, max_duration=7)
    assert parts[0].text == "Hello everyone"
    assert not any(p.text.split()[-1].lower() in {"the", "to", "a"} for p in parts)


def test_fontconfig_listing(monkeypatch):
    from backend.app.services import fonts

    class R:
        stdout = "Noto Sans SC,思源黑体\t/f/NotoSansSC.otf\nDejaVu Sans\t/f/DejaVuSans.ttf\nBad\t/f/x.pcf\n"

    monkeypatch.setattr(fonts.shutil, "which", lambda n: "/usr/bin/fc-list")
    monkeypatch.setattr(fonts.subprocess, "run", lambda *a, **k: R())
    got = fonts._list_fonts_fontconfig()
    assert got == {"Noto Sans SC": "/f/NotoSansSC.otf", "思源黑体": "/f/NotoSansSC.otf", "DejaVu Sans": "/f/DejaVuSans.ttf"}
