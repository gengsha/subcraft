"""配置迁移、AI 厂商解析与 key 掩码回写测试。"""
import json

from backend.app.config import ConfigStore
from backend.app.services import translator


def test_old_config_migrates_to_ai_providers(tmp_path, monkeypatch):
    """旧版 openai_* 配置应迁移为 ai_providers 列表项。"""
    monkeypatch.setenv("SUBCRAFT_DATA_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({
        "openai_base_url": "https://api.deepseek.com/v1",
        "openai_api_key": "sk-oldkey1234",
        "openai_model": "deepseek-chat",
        "whisper_model": "tiny",
    }), encoding="utf-8")
    store = ConfigStore()
    providers = store.get("ai_providers")
    assert len(providers) == 1
    p = providers[0]
    assert p["api_key"] == "sk-oldkey1234"
    assert p["base_url"] == "https://api.deepseek.com/v1"
    assert p["model"] == "deepseek-chat"
    # 旧键不再回写
    assert "openai_api_key" not in store.all()
    assert store.get("whisper_model") == "tiny"


def test_get_ai_provider_by_id(monkeypatch):
    monkeypatch.setattr(translator, "__store_providers", None, raising=False)  # no-op 防呆
    from backend.app.config import store
    monkeypatch.setattr(store, "_cfg", {
        **store._cfg,
        "ai_providers": [
            {"id": "a", "name": "甲", "base_url": "https://a.com/v1", "api_key": "ka", "model": "m1"},
            {"id": "b", "name": "乙", "base_url": "https://b.com/v1", "api_key": "kb", "model": "m2"},
        ],
    })
    assert translator.get_ai_provider("b")["api_key"] == "kb"
    assert translator.get_ai_provider()["id"] == "a"          # 默认取第一个
    assert translator.get_ai_provider("不存在")["id"] == "a"   # 找不到回退第一个


def test_get_translator_uses_provider_credentials(monkeypatch):
    from backend.app.config import store
    monkeypatch.setattr(store, "_cfg", {
        **store._cfg,
        "ai_providers": [{"id": "x", "name": "测试商", "base_url": "https://x.com/v1", "api_key": "kx", "model": "mx"}],
        "deepl_api_key": "dk:fx",
    })
    t = translator._get_translator("openai", "x")
    assert t.model == "mx"
    d = translator._get_translator("deepl")
    assert "api-free" in d.url


def test_masked_roundtrip_preserves_keys(tmp_path, monkeypatch):
    """掩码后的配置回写不应覆盖已保存的 key。"""
    import copy

    from backend.app.config import store
    from backend.app.routers.config import _masked, update_config

    monkeypatch.setattr(store, "_path", tmp_path / "config.json")  # 隔离真实配置文件
    original = copy.deepcopy(store._cfg.get("ai_providers", []))
    try:
        update_config({"ai_providers": [{"id": "p1", "name": "A", "base_url": "https://a.com", "api_key": "real-key-123", "model": "m"}]})
        masked = _masked(store.all())
        assert masked["ai_providers"][0]["api_key"] == "****-123"
        assert masked["ai_providers"][0]["api_key_set"] is True
        # 掩码回写
        update_config({"ai_providers": masked["ai_providers"]})
        assert store.get("ai_providers")[0]["api_key"] == "real-key-123"
    finally:
        store._cfg["ai_providers"] = original


def test_system_status_and_cuda_check():
    from backend.app.routers.config import system_status
    from backend.app.services import asr

    res = system_status()
    assert "ffmpeg_ready" in res
    assert "cuda_available" in res
    assert isinstance(res["cuda_available"], bool)
    assert res["cuda_available"] == asr.is_cuda_available()



def _fake_frozen(monkeypatch, exe_dir):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "subcraft"))


def test_frozen_cli_uses_portable_data_dir(tmp_path, monkeypatch):
    """打包版可执行文件旁有 data 目录时进入便携模式；SUBCRAFT_DATA_DIR 仍优先。"""
    from backend.app import config
    monkeypatch.delenv("SUBCRAFT_DATA_DIR", raising=False)
    _fake_frozen(monkeypatch, tmp_path)
    assert config.portable_data_dir() is None
    (tmp_path / "data").mkdir()
    assert config.data_dir() == tmp_path / "data"
    monkeypatch.setenv("SUBCRAFT_DATA_DIR", str(tmp_path / "other"))
    assert config.data_dir() == tmp_path / "other"


def test_frozen_tools_dir_next_to_executable(tmp_path, monkeypatch):
    """打包版 ffmpeg 等工具放在可执行文件旁，而不是 onefile 的临时解压目录。"""
    from backend.app import config
    monkeypatch.delenv("SUBCRAFT_TOOLS_DIR", raising=False)
    _fake_frozen(monkeypatch, tmp_path)
    assert config.tools_dir() == tmp_path / "tools"
