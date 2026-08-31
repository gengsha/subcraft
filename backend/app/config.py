"""应用配置：数据目录、API Key 等持久化设置。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "SubCraft"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def data_dir() -> Path:
    override = os.environ.get("SubCraft_DATA_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".config"
    return base / APP_NAME


def tools_dir() -> Path:
    override = os.environ.get("SubCraft_TOOLS_DIR")
    if override:
        return Path(override)
    # 开发模式：项目根目录/tools；打包后由 Electron 设置 SubCraft_TOOLS_DIR
    return project_root() / "tools"


def work_dir() -> Path:
    d = data_dir() / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_CONFIG: dict[str, Any] = {
    # AI 翻译接口（OpenAI 兼容）厂商列表:
    # [{"id": "xxx", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "api_key": "sk-...", "model": "deepseek-chat"}]
    "ai_providers": [],
    # DeepL
    "deepl_api_key": "",
    # ASR
    "whisper_model": "large-v3-turbo",
    "whisper_device": "auto",        # auto / cuda / cpu
    # 翻译批处理
    "translate_batch_size": 25,
    "translate_concurrency": 4,
}


class ConfigStore:
    def __init__(self) -> None:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        self._path = d / "config.json"
        self._cfg: dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    # 旧版单 OpenAI 配置 → 迁移为 AI 厂商列表中的一项
                    if any(k in saved for k in ("openai_base_url", "openai_api_key", "openai_model")):
                        old_key = saved.pop("openai_api_key", "")
                        old_base = saved.pop("openai_base_url", "https://api.openai.com/v1")
                        old_model = saved.pop("openai_model", "gpt-4o-mini")
                        if not saved.get("ai_providers"):
                            saved["ai_providers"] = [{
                                "id": "openai", "name": "OpenAI",
                                "base_url": old_base, "api_key": old_key, "model": old_model,
                            }]
                    self._cfg.update(saved)
            except Exception:
                pass

    def save(self) -> None:
        self._path.write_text(
            json.dumps(self._cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._cfg.get(key, default)

    def all(self) -> dict[str, Any]:
        # 不向前端暴露完整 key，仅返回掩码后的副本由路由层处理
        return dict(self._cfg)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        for k, v in values.items():
            if k in DEFAULT_CONFIG:
                self._cfg[k] = v
        self.save()
        return dict(self._cfg)


store = ConfigStore()
