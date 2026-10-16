"""批量处理测试：文件扫描 / 自然排序 / 断点续跑 / 单集失败不中断，CLI 与 MCP 两个入口。

识别、翻译、ffprobe 全部打桩，不需要模型、网络与真实视频。
"""
import asyncio
import json
from pathlib import Path

import pytest

from backend import cli
from backend.app.mcp import tools

EN_SRT = (
    "1\n00:00:00,500 --> 00:00:02,000\nHello world\n\n"
    "2\n00:00:02,500 --> 00:00:04,000\nSecond line\n"
)


def _batch_mod(cli_side: bool):
    """CLI 以 `app.*` 导入、测试与 MCP 以 `backend.app.*` 导入，是两份模块，打桩要打对。"""
    if cli_side:
        from app.services import batch  # type: ignore[import-not-found]
    else:
        from backend.app.services import batch
    return batch


def _fakes(models):
    """按被测一侧的 models 模块造对象（pydantic 不接受另一份模块里的同名类实例）。"""
    seg, info = models.Segment, models.MediaInfo

    def translate(segments, source_lang, target_lang, *a, **kw):
        if any("BOOM" in s.text for s in segments):
            raise RuntimeError("厂商返回 500")
        return [seg(start=s.start, end=s.end, text=f"[{target_lang}]{s.text}") for s in segments]

    def probe(path):
        return info(path=str(path), name=Path(path).name, duration=4.0, width=1280, height=720)

    def transcribe(path, duration, engine, model, lang, *a, **kw):
        if "silent" in Path(path).name:
            return [], "en"
        return [seg(start=0.5, end=2.0, text="Hello"), seg(start=2.5, end=4.0, text="World")], "en"
    return translate, probe, transcribe


def _patch(monkeypatch, cli_side: bool):
    batch = _batch_mod(cli_side)
    import importlib
    pkg = "app.services" if cli_side else "backend.app.services"
    _fake_translate, _fake_probe, _fake_transcribe = _fakes(
        importlib.import_module(pkg.replace(".services", ".models")))
    translator = importlib.import_module(f"{pkg}.translator")
    asr = importlib.import_module(f"{pkg}.asr")
    ffmpeg_tool = importlib.import_module(f"{pkg}.ffmpeg_tool")
    monkeypatch.setattr(translator, "translate_segments", _fake_translate)
    monkeypatch.setattr(asr, "transcribe", _fake_transcribe)
    monkeypatch.setattr(ffmpeg_tool, "probe", _fake_probe)
    monkeypatch.setattr(ffmpeg_tool, "find_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    return batch


# ---------------------------------------------------------------- 扫描与命名

def test_natural_sort_and_output_exclusion(tmp_path):
    from backend.app.services import batch

    for n in ["EP10.mp4", "EP2.mp4", "EP1.mkv", "EP1.hard.mp4", "EP2.soft.mkv", "notes.txt", ".hidden.mp4"]:
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "S2").mkdir()
    (tmp_path / "S2" / "EP3.mp4").write_bytes(b"x")
    opts = batch.validate(batch.BatchOptions())
    assert [p.name for p in batch.find_inputs(tmp_path, opts)] == ["EP1.mkv", "EP2.mp4", "EP10.mp4"]
    opts.recursive = True
    assert [p.name for p in batch.find_inputs(tmp_path, opts)][-1] == "EP3.mp4"
    opts.pattern = "EP1*"
    assert [p.name for p in batch.find_inputs(tmp_path, opts)] == ["EP1.mkv", "EP10.mp4"]
    opts.pattern, opts.limit = None, 2
    assert len(batch.find_inputs(tmp_path, opts)) == 2


def test_out_dir_inside_folder_is_not_rescanned(tmp_path):
    from backend.app.services import batch

    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.hard.mp4").write_bytes(b"x")
    (tmp_path / "out" / "copy.mp4").write_bytes(b"x")
    opts = batch.validate(batch.BatchOptions(recursive=True, out_dir=str(tmp_path / "out")))
    assert [p.name for p in batch.find_inputs(tmp_path, opts)] == ["a.mp4"]


def test_subs_mode_groups_formats_and_skips_outputs(tmp_path):
    from backend.app.services import batch

    for n in ["L01.en.srt", "L01.en.ass", "L02.en.vtt", "L01.zh.srt", "L01.bilingual.srt", "L03.srt"]:
        (tmp_path / n).write_text(EN_SRT, encoding="utf-8")
    opts = batch.validate(batch.BatchOptions(mode="subs", target="zh"))
    assert [p.name for p in batch.find_inputs(tmp_path, opts)] == ["L01.en.srt", "L02.en.vtt", "L03.srt"]
    assert batch.strip_lang_suffix("L01.en") == "L01"
    assert batch.strip_lang_suffix("L01.bilingual") == "L01"
    assert batch.strip_lang_suffix("v1.2") == "v1.2"


def test_validate_rejects_bad_options():
    from backend.app.services import batch

    with pytest.raises(batch.BatchError):
        batch.validate(batch.BatchOptions(mode="subs"))           # subs 需要目标语言
    with pytest.raises(batch.BatchError):
        batch.validate(batch.BatchOptions(target="xx"))
    with pytest.raises(batch.BatchError):
        batch.validate(batch.BatchOptions(formats=["vtt"]))
    with pytest.raises(batch.BatchError):
        batch.validate(batch.BatchOptions(video="gif"))


# ---------------------------------------------------------------- CLI

def test_cli_batch_subs_resume_and_failure(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch, cli_side=True)
    src = tmp_path / "course"
    (src / "week1").mkdir(parents=True)
    (src / "week1" / "L01.en.srt").write_text(EN_SRT, encoding="utf-8")
    (src / "week1" / "L02.en.srt").write_text(EN_SRT.replace("Second", "BOOM"), encoding="utf-8")
    (src / "L10.en.srt").write_text(EN_SRT, encoding="utf-8")
    out = tmp_path / "out"

    args = ["batch", str(src), "--subs", "-t", "zh", "-r", "-o", str(out), "--json", "-q"]
    assert cli.main(args) == 0
    rep = json.loads(capsys.readouterr().out)
    assert (rep["total"], rep["done"], rep["failed"]) == (3, 2, 1)
    assert [Path(r["relative"]).name for r in rep["items"]] == ["L10.en.srt", "L01.en.srt", "L02.en.srt"]
    zh = out / "week1" / "L01.zh.srt"
    assert zh.exists() and "[zh]Hello world" in zh.read_text(encoding="utf-8-sig")
    assert (out / "week1" / "L01.bilingual.ass").exists()
    assert "厂商返回 500" in rep["items"][2]["error"]
    saved = json.loads((out / "subcraft_batch_report.json").read_text(encoding="utf-8"))
    assert saved["failed"] == 1 and "trace" not in saved["items"][2]

    # 修好失败的那集后重跑：已完成的跳过，只补做失败的
    (src / "week1" / "L02.en.srt").write_text(EN_SRT, encoding="utf-8")
    assert cli.main(args) == 0
    rep = json.loads(capsys.readouterr().out)
    assert (rep["done"], rep["skipped"], rep["failed"]) == (1, 2, 0)
    # --force 全部重做
    assert cli.main(args + ["--force"]) == 0
    assert json.loads(capsys.readouterr().out)["done"] == 3


def test_cli_batch_media_dry_run_and_run(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch, cli_side=True)
    for n in ["EP2.mp4", "EP10.mp4", "silent.mp4"]:
        (tmp_path / n).write_bytes(b"x")

    assert cli.main(["batch", str(tmp_path), "-t", "zh", "--dry-run", "--json", "-q"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert [r["status"] for r in rep["items"]] == ["pending"] * 3
    assert not list(tmp_path.glob("*.srt"))

    assert cli.main(["batch", str(tmp_path), "-t", "zh", "--formats", "srt", "--primary-target"]) == 0
    captured = capsys.readouterr()
    assert "成功 2" in captured.out and "失败 1" in captured.out and "未识别到语音内容" in captured.out
    assert (tmp_path / "EP2.en.srt").exists() and (tmp_path / "EP10.zh.srt").exists()
    assert (tmp_path / "EP10.bilingual.srt").read_text(encoding="utf-8-sig").index("[zh]Hello") < \
        (tmp_path / "EP10.bilingual.srt").read_text(encoding="utf-8-sig").index("\nHello")
    assert "✓ [1/3] EP2.mp4" in captured.err


def test_cli_batch_stop_on_error_and_empty_folder(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch, cli_side=True)
    assert cli.main(["batch", str(tmp_path), "-q"]) == 2            # 空文件夹
    assert "没有找到" in capsys.readouterr().err
    for n in ["a_silent.mp4", "b.mp4"]:
        (tmp_path / n).write_bytes(b"x")
    assert cli.main(["batch", str(tmp_path), "--stop-on-error", "--json", "-q"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["stopped_early"] and len(rep["items"]) == 1
    assert cli.main(["batch", str(tmp_path), "--subs", "-q"]) == 2   # subs 缺 -t


# ---------------------------------------------------------------- MCP

def test_mcp_batch_tool(tmp_path, monkeypatch):
    _patch(monkeypatch, cli_side=False)
    for n in ["L1.en.srt", "L2.en.srt"]:
        (tmp_path / n).write_text(EN_SRT, encoding="utf-8")

    dry = asyncio.run(tools.subcraft_batch_process(None, str(tmp_path), "zh", mode="subs", dry_run=True))
    assert dry["total"] == 2 and {r["status"] for r in dry["items"]} == {"pending"}

    res = asyncio.run(tools.subcraft_batch_process(None, str(tmp_path), "ja", mode="subs", formats=["srt"]))
    assert res["status"] == "done" and res["done"] == 2
    assert (tmp_path / "L2.ja.srt").exists() and Path(res["report_path"]).exists()
    assert "trace" not in json.dumps(res) and "options" not in res

    again = asyncio.run(tools.subcraft_batch_process(None, str(tmp_path), "ja", mode="subs", formats=["srt"]))
    assert again["skipped"] == 2

    with pytest.raises(Exception, match="必须指定目标语言"):
        asyncio.run(tools.subcraft_batch_process(None, str(tmp_path), mode="subs"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(Exception, match="没有可处理"):
        asyncio.run(tools.subcraft_batch_process(None, str(empty), "zh"))


def test_batch_tool_registered():
    from backend.app.mcp.server import server

    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "subcraft_batch_process" in names


def test_mcp_batch_media_split_cuts(tmp_path, monkeypatch):
    _patch(monkeypatch, cli_side=False)
    from backend.app.services import ffmpeg_tool, timeline

    monkeypatch.setattr(ffmpeg_tool, "ensure_ffmpeg", lambda *a, **k: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(timeline, "detect_cuts", lambda *a, **k: [1.9, 3.2])
    (tmp_path / "EP1.mp4").write_bytes(b"x")
    res = asyncio.run(tools.subcraft_batch_process(None, str(tmp_path), "zh", split_cuts=True, formats=["srt"]))
    item = res["items"][0]
    # 1.9 离第 1 段结尾 2.0 很近 → 收回到切点前；3.2 落在第 2 段中间 → 拆开，译文跟着拆后的源轨逐段翻译
    assert item["snap"]["snapped"] >= 1 and item["snap"]["split"] == 1 and item["snap"]["need_split"] == []
    assert item["segments"] == 3
    zh = (tmp_path / "EP1.zh.srt").read_text(encoding="utf-8-sig")
    assert "--> 00:00:01," in zh and "00:00:03,200 --> 00:00:04,000" in zh
