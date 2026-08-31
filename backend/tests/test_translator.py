"""翻译对齐解析单元测试（不调用真实 API）。"""
from backend.app.models import Segment
from backend.app.services import translator


def test_parse_numbered_lines():
    text = "1. 你好\n2. 世界\n3. 字幕"
    assert translator.parse_numbered_lines(text) == ["你好", "世界", "字幕"]


def test_parse_numbered_lines_variants():
    assert translator.parse_numbered_lines("[1] a\n(2) b\n3、 c") == ["a", "b", "c"]
    assert translator.parse_numbered_lines("仅一行") == ["仅一行"]


def test_translate_segments_alignment(monkeypatch):
    """模拟批量翻译返回数量不齐时，结果仍与时间轴一一对应。"""
    class FakeTranslator:
        def translate_batch(self, texts, source_lang, target_lang):
            if len(texts) > 1:
                return texts[::-1]  # 批量：整批反转（数量一致）
            return [t + "!" for t in texts]

    monkeypatch.setattr(translator, "_get_translator", lambda *a, **k: FakeTranslator())
    segs = [Segment(start=i, end=i + 1, text=f"s{i}") for i in range(5)]
    out = translator.translate_segments(segs, "en", "zh", batch_size=3, concurrency=1)
    assert len(out) == 5
    assert out[0].text == "s2" and out[2].text == "s0"   # 第一批反转
    assert out[3].text == "s4" and out[4].text == "s3"   # 第二批反转
    assert [ (s.start, s.end) for s in out ] == [ (i, i + 1) for i in range(5) ]


def test_deepl_host_selection():
    free = translator.DeepLTranslator("abc:fx")
    pro = translator.DeepLTranslator("abc")
    assert "api-free" in free.url and "api.deepl.com" in pro.url
