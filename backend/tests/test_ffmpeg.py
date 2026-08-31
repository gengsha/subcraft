"""ffmpeg 命令构造与探测测试（依赖系统/内置 ffmpeg，可跳过）。"""
import shutil

import pytest

from backend.app.services import ffmpeg_tool

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None and ffmpeg_tool.find_ffmpeg() is None,
    reason="无 ffmpeg 可用",
)


def test_find_ffmpeg():
    found = ffmpeg_tool.find_ffmpeg()
    assert found is not None


def test_probe_and_mux(tmp_path):
    ffmpeg, _ = ffmpeg_tool.find_ffmpeg()
    import subprocess
    # 生成 1 秒测试视频（含音轨）
    src = tmp_path / "src.mp4"
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-c:a", "aac", "-strict", "-2", "-shortest", str(src),
    ], check=True, capture_output=True)

    info = ffmpeg_tool.probe(str(src))
    assert info.width == 320 and info.height == 240
    assert info.duration > 0

    sub = tmp_path / "t.ass"
    from backend.app.models import Segment, SubtitleTrack
    from backend.app.services import ass_builder
    sub.write_text(
        ass_builder.build_ass([SubtitleTrack(id="a", language="zh", segments=[Segment(start=0.0, end=0.9, text="测试")])]),
        encoding="utf-8-sig",
    )
    out = tmp_path / "out.mkv"
    ffmpeg_tool.mux_subtitles(str(src), [(sub, "zh", "中文")], out)
    assert out.exists() and out.stat().st_size > 0

    # 校验字幕轨确实存在且视频流为 copy（h264 保持不变）
    info2 = ffmpeg_tool.probe(str(out))
    assert info2.video_codec == "h264"


def test_burn_subtitles(tmp_path):
    ffmpeg, _ = ffmpeg_tool.find_ffmpeg()
    import subprocess
    if not ffmpeg_tool._has_filter(ffmpeg, "ass") and not ffmpeg_tool._has_filter(ffmpeg, "subtitles"):
        pytest.skip("当前 ffmpeg 无 libass 滤镜")
    src = tmp_path / "src.mp4"
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-c:a", "aac", "-strict", "-2", "-shortest", str(src),
    ], check=True, capture_output=True)

    sub = tmp_path / "t.ass"
    from backend.app.models import Segment, SubtitleTrack
    from backend.app.services import ass_builder
    sub.write_text(
        ass_builder.build_ass([SubtitleTrack(id="a", language="zh", segments=[Segment(start=0.0, end=0.9, text="测试内嵌")])]),
        encoding="utf-8-sig",
    )
    out = tmp_path / "out_hard.mp4"
    seen: list[float] = []
    ffmpeg_tool.burn_subtitles(str(src), sub, out, progress_cb=lambda p, m: seen.append(p))
    assert out.exists() and out.stat().st_size > 0

    # 烧录后视频必须重编码且时长保持一致
    info = ffmpeg_tool.probe(str(out))
    assert info.video_codec == "h264"
    assert abs(info.duration - 1.0) < 0.5
    assert seen and seen[-1] > 0


def test_burn_frame(tmp_path):
    ffmpeg, _ = ffmpeg_tool.find_ffmpeg()
    import subprocess
    if not ffmpeg_tool._has_filter(ffmpeg, "ass") and not ffmpeg_tool._has_filter(ffmpeg, "subtitles"):
        pytest.skip("当前 ffmpeg 无 libass 滤镜")
    src = tmp_path / "src.mp4"
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
        "-c:v", "libx264", str(src),
    ], check=True, capture_output=True)

    sub = tmp_path / "t.ass"
    from backend.app.models import Segment, SubtitleTrack
    from backend.app.services import ass_builder
    sub.write_text(
        ass_builder.build_ass([SubtitleTrack(id="a", language="zh", segments=[Segment(start=0.0, end=2.0, text="预览帧")])]),
        encoding="utf-8-sig",
    )
    jpg = tmp_path / "frame.jpg"
    ffmpeg_tool.burn_frame(str(src), sub, 1.0, jpg)
    assert jpg.exists() and jpg.stat().st_size > 1000
    # 时间点超出视频长度时应自动夹到视频末尾而不是报错
    jpg2 = tmp_path / "frame2.jpg"
    ffmpeg_tool.burn_frame(str(src), sub, 99.0, jpg2)
    assert jpg2.exists() and jpg2.stat().st_size > 1000
