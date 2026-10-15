"""枚举系统字体（Windows 注册表 / Linux·macOS fontconfig），并提供字体文件供前端预览。"""
from __future__ import annotations

import sys
import shutil
import subprocess
from pathlib import Path

_cache: dict[str, str] | None = None


def list_fonts() -> dict[str, str]:
    """返回 {字体显示名: 字体文件路径}。"""
    global _cache
    if _cache is not None:
        return _cache
    fonts: dict[str, str] = {}
    if sys.platform == "win32":
        import winreg

        system_fonts = Path(__import__("os").environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
                )
            except OSError:
                continue
            fonts_dir = (
                system_fonts
                if root == winreg.HKEY_LOCAL_MACHINE
                else Path.home() / "AppData/Local/Microsoft/Windows/Fonts"
            )
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    i += 1
                except OSError:
                    break
                # 部分注册表项的值不是字体路径（如 REG_DWORD 标记位），会导致 Path() 抛错，跳过
                if not isinstance(value, str):
                    continue
                family = name.split(" (")[0].strip()
                path = Path(value) if Path(value).is_absolute() else fonts_dir / value
                if family and path.exists() and family not in fonts:
                    fonts[family] = str(path)
            winreg.CloseKey(key)
    else:
        fonts = _list_fonts_fontconfig() or _scan_font_dirs()
    _cache = dict(sorted(fonts.items()))
    return _cache


_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}


def _list_fonts_fontconfig() -> dict[str, str]:
    """Linux / macOS：用 fc-list 枚举（与 libass/ffmpeg 实际使用的字体来源一致）。"""
    fc = shutil.which("fc-list")
    if not fc:
        return {}
    try:
        out = subprocess.run(
            [fc, "--format", "%{family}\t%{file}\n"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    fonts: dict[str, str] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        families, file = line.rsplit("\t", 1)
        if Path(file).suffix.lower() not in _FONT_EXTS:
            continue
        # 一个字体可能有多个本地化族名（如 "Noto Sans SC,思源黑体"），全部登记
        for family in families.split(","):
            family = family.strip()
            if family and family not in fonts:
                fonts[family] = file
    return fonts


def _scan_font_dirs() -> dict[str, str]:
    """无 fontconfig 时的兜底：扫描常见字体目录，以文件名作显示名。"""
    dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
            Path.home() / ".local/share/fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts"),
            Path.home() / "Library/Fonts"]
    fonts: dict[str, str] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.suffix.lower() in _FONT_EXTS and f.stem not in fonts:
                fonts[f.stem] = str(f)
    return fonts


def font_file(family: str) -> Path | None:
    fonts = list_fonts()
    if family in fonts:
        return Path(fonts[family])
    # 前缀匹配兜底（如 "Microsoft YaHei" vs "Microsoft YaHei UI"）
    for name, path in fonts.items():
        if name.lower().startswith(family.lower()) or family.lower().startswith(name.lower()):
            return Path(path)
    return None
