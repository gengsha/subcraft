"""PyInstaller 运行时钩子（仅纯命令行版）：不打包 PyAV，给 faster-whisper 一个占位 av 模块。

faster-whisper 在模块顶层 `import av`，但 SubCraft 总是先用 ffmpeg 抽出 16kHz 单声道 PCM，
再以 numpy 数组喂给模型（见 services/asr._load_wav），从不调用 PyAV 解码。
去掉 PyAV 能省下约 90 MB；真被调用时给出明确错误而不是静默失败。
"""
import sys
import types


class _NoAV(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError("纯命令行版未包含 PyAV：音频应先由 ffmpeg 转成 16kHz 单声道 WAV")


sys.modules.setdefault("av", _NoAV("av"))
