"""枚举 Windows 系统字体（注册表），并提供字体文件供前端预览。"""
from __future__ import annotations

import sys
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
    _cache = dict(sorted(fonts.items()))
    return _cache


def font_file(family: str) -> Path | None:
    fonts = list_fonts()
    if family in fonts:
        return Path(fonts[family])
    # 前缀匹配兜底（如 "Microsoft YaHei" vs "Microsoft YaHei UI"）
    for name, path in fonts.items():
        if name.lower().startswith(family.lower()) or family.lower().startswith(name.lower()):
            return Path(path)
    return None
