"""本地后端访问控制：令牌校验、CORS 来源限制、Host 校验。"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.security import TOKEN_ENV

TOKEN = "t0ken-for-test"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_health_is_public(client):
    assert client.get("/api/health").status_code == 200


def test_rejects_request_without_token(client):
    assert client.get("/api/config").status_code == 401
    assert client.post("/api/config", json={"deepl_api_key": "x"}).status_code == 401


def test_accepts_header_or_query_token(client):
    assert client.get("/api/config", headers={"X-SubCraft-Token": TOKEN}).status_code == 200
    assert client.get(f"/api/config?token={TOKEN}").status_code == 200
    assert client.get("/api/config", headers={"X-SubCraft-Token": "wrong"}).status_code == 401


def test_cors_blocks_foreign_origin(client):
    r = client.options("/api/config", headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-subcraft-token",
    })
    assert r.headers.get("access-control-allow-origin") is None


@pytest.mark.parametrize("origin", ["null", "http://localhost:5173", "http://127.0.0.1:5173"])
def test_cors_allows_app_origins(client, origin):
    r = client.options("/api/config", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-subcraft-token",
    })
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_rejects_foreign_host_header(client):
    """DNS 重绑定：用别的域名解析到 127.0.0.1 访问时拒绝。"""
    r = client.get("/api/health", headers={"Host": "attacker.example.com"})
    assert r.status_code == 403


def test_websocket_requires_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1/ws") as ws:
            ws.receive_text()
    with client.websocket_connect(f"ws://127.0.0.1/ws?token={TOKEN}") as ws:
        ws.send_text("ping")


def test_no_token_configured_allows_local_debug(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    c = TestClient(create_app(), base_url="http://127.0.0.1")
    assert c.get("/api/config").status_code == 200
