"""本地后端访问控制。

后端只监听 127.0.0.1，但浏览器里的任意网页同样能访问 127.0.0.1。
为防止恶意网页读取本地文件、改写翻译厂商 base_url 窃取 API Key、或借导出接口写任意路径，
这里做两层防护：

1. CORS 只放行 Electron 渲染进程（file:// → Origin "null"）与本地 Vite 开发服务器；
2. 共享令牌：Electron 启动时生成随机令牌，经环境变量 SUBCRAFT_TOKEN 传给后端、
   经启动参数传给渲染进程。请求需带 `X-SubCraft-Token` 头，
   无法自定义请求头的场景（<video src>、WebSocket）改用 `?token=` 查询参数。

未设置 SUBCRAFT_TOKEN（手动 `python run.py` 调试）时不校验令牌，但 CORS 限制仍然生效。
"""
from __future__ import annotations

import hmac
import os

from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "x-subcraft-token"
TOKEN_ENV = "SUBCRAFT_TOKEN"

# Electron loadFile 的 Origin 为 "null"；开发模式为 Vite 本地地址
ALLOWED_ORIGIN_REGEX = r"^(null|https?://(localhost|127\.0\.0\.1)(:\d+)?)$"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

# 无需令牌的路径（Electron 主进程启动时的健康检查）
PUBLIC_PATHS = {"/api/health"}


def expected_token() -> str:
    return os.environ.get(TOKEN_ENV, "")


def _query_token(scope: Scope) -> str:
    from urllib.parse import parse_qs

    qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
    vals = qs.get("token") or []
    return vals[0] if vals else ""


def _header(scope: Scope, name: str) -> str:
    raw = name.encode("latin-1")
    for k, v in scope.get("headers") or []:
        if k.lower() == raw:
            return v.decode("latin-1")
    return ""


def check_request(scope: Scope, token: str | None = None) -> tuple[bool, int, str]:
    """返回 (是否放行, 状态码, 原因)。"""
    host = _header(scope, "host").rsplit(":", 1)[0].strip("[]")
    if host and host not in ALLOWED_HOSTS:
        # 防 DNS 重绑定：只接受以 127.0.0.1 / localhost 访问
        return False, 403, "invalid host"
    if scope.get("type") == "http" and scope.get("method") == "OPTIONS":
        return True, 200, ""
    if scope.get("path") in PUBLIC_PATHS:
        return True, 200, ""
    token = expected_token() if token is None else token
    if not token:
        return True, 200, ""
    given = _header(scope, TOKEN_HEADER) or _query_token(scope)
    if given and hmac.compare_digest(given, token):
        return True, 200, ""
    return False, 401, "missing or invalid token"


class TokenAuthMiddleware:
    """纯 ASGI 中间件，同时覆盖 HTTP 与 WebSocket。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        ok, status, reason = check_request(scope)
        if ok:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        body = ('{"detail":"%s"}' % reason).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
