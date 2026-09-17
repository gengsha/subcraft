"""CLI 入口测试：参数解析、字幕导出链路、错误退出码（不触发识别/翻译/ffmpeg 压制）。"""
import json

import pytest

from backend import cli

EN_SRT = (
    "1\n00:00:00,500 --> 00:00:02,000\nHello world\n\n"
    "2\n00:00:02,500 --> 00:00:04,000\nSecond line\n"
)
ZH_SRT = (
    "1\n00:00:00,500 --> 00:00:02,000\n你好世界\n\n"
    "2\n00:00:02,500 --> 00:00:04,000\n第二行\n"
)


def write_subs(tmp_path):
    zh = tmp_path / "demo.zh.srt"
    en = tmp_path / "demo.en.srt"
    zh.write_text(ZH_SRT, encoding="utf-8")
    en.write_text(EN_SRT, encoding="utf-8")
    return zh, en


def test_help_exits_zero():
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0


def test_status_json(capsys):
    assert cli.main(["status", "--json", "-q"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "ffmpeg_ready" in data and "languages" in data


def test_export_bilingual_from_files(tmp_path, capsys):
    zh, en = write_subs(tmp_path)
    out = tmp_path / "out"
    rc = cli.main(["export", "-s", str(zh), "-s", str(en), "-o", str(out),
                   "--base", "demo", "--formats", "srt,ass", "-q"])
    assert rc == 0
    names = {p.name for p in out.iterdir()}
    assert names == {"demo.zh.srt", "demo.en.srt", "demo.bilingual.srt",
                     "demo.zh.ass", "demo.en.ass", "demo.bilingual.ass"}
    bi = (out / "demo.bilingual.srt").read_text(encoding="utf-8-sig")
    assert "你好世界\nHello world" in bi          # 主行（zh）在上
    ass = (out / "demo.bilingual.ass").read_text(encoding="utf-8-sig")
    assert "\\N{\\" in ass and "Style: Main," in ass


def test_export_primary_switch(tmp_path, capsys):
    zh, en = write_subs(tmp_path)
    out = tmp_path / "out2"
    rc = cli.main(["export", "-s", str(zh), "-s", str(en), "--primary", "1",
                   "-o", str(out), "--base", "demo", "--formats", "srt", "-q"])
    assert rc == 0
    body = (out / "demo.bilingual.srt").read_text(encoding="utf-8-sig").splitlines()
    assert body[2] == "Hello world"               # --primary 1 → 英文为主行
    assert body[3] == "你好世界"


def test_export_sub_style_follows_primary(tmp_path):
    zh, en = write_subs(tmp_path)
    out = tmp_path / "out3"
    assert cli.main(["export", "-s", str(zh), "-s", str(en), "-o", str(out),
                     "--base", "demo", "--formats", "ass", "-q"]) == 0
    ass = (out / "demo.bilingual.ass").read_text(encoding="utf-8-sig")
    main_line = next(l for l in ass.splitlines() if l.startswith("Style: Main,"))
    sub_line = next(l for l in ass.splitlines() if l.startswith("Style: Sub,"))
    assert ",48," in main_line                    # 主轨默认字号
    assert ",34," in sub_line                     # 副轨 0.7 倍字号
    assert "&H0099FFFF" in sub_line               # 副轨淡黄


def test_missing_file_exit_code_2(tmp_path, capsys):
    rc = cli.main(["export", "-s", str(tmp_path / "nope.srt"), "-q"])
    assert rc == 2
    assert "错误" in capsys.readouterr().err


def test_bad_formats_exit_code_2(tmp_path, capsys):
    zh, en = write_subs(tmp_path)
    rc = cli.main(["export", "-s", str(zh), "-s", str(en), "--formats", "txt", "-q"])
    assert rc == 2
    assert "--formats" in capsys.readouterr().err


def test_unknown_language_exit_code_2(tmp_path, capsys):
    zh, _ = write_subs(tmp_path)
    rc = cli.main(["translate", str(zh), "-t", "xx", "-q"])
    assert rc == 2
    assert "语言码无效" in capsys.readouterr().err
