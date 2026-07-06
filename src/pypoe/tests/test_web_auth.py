"""Web cookie-verify / header auth middleware (CLAUDE.local.md §4.8).

Drives the real ``_OwnerScopeMiddleware`` over ASGI with a mocked sidecar
(``_verify_session`` monkeypatched), covering the valid / invalid / sidecar-
unreachable / public-path / header-mode paths.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

import httpx
from fastapi import FastAPI

import pypoe.interfaces.web.app as appmod
from pypoe.core.history import owner_ctx, _UNSCOPED


def _build(**kw):
    app = FastAPI()
    app.add_middleware(appmod._OwnerScopeMiddleware, **kw)

    @app.get("/who")
    async def who():
        v = owner_ctx.get()
        return {"owner": None if v is _UNSCOPED else v}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


async def _get(app, path, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                 follow_redirects=False) as c:
        return await c.get(path, headers=headers or {})


def test_auth_off_is_open_and_unscoped():
    async def go():
        app = _build(verify_cookie=False, trust_header=False)
        r = await _get(app, "/who")
        assert r.status_code == 200 and r.json()["owner"] is None
    asyncio.run(go())


def test_cookie_verify_paths(monkeypatch):
    async def go():
        state = {"r": None}

        async def fake_verify(base, cookie):
            return state["r"]

        monkeypatch.setattr(appmod, "_verify_session", fake_verify)
        app = _build(verify_cookie=True, auth_service_base="http://x",
                     login_url="http://dash/login")

        state["r"] = "alice@lab"
        r = await _get(app, "/who", {"cookie": "ac_auth_session=abc"})
        assert r.status_code == 200 and r.json()["owner"] == "alice@lab"

        state["r"] = None  # unauthenticated
        r = await _get(app, "/who", {"accept": "text/html"})
        assert r.status_code == 302 and r.headers["location"] == "http://dash/login"
        r = await _get(app, "/who", {"accept": "application/json"})
        assert r.status_code == 401

        state["r"] = "unreachable"  # sidecar down -> fail open
        r = await _get(app, "/who")
        assert r.status_code == 200 and r.json()["owner"] is None

        state["r"] = None  # public path bypasses auth
        r = await _get(app, "/health")
        assert r.status_code == 200

    asyncio.run(go())


def test_cookie_verify_401_page_without_login_url(monkeypatch):
    async def go():
        async def fake_verify(base, cookie):
            return None

        monkeypatch.setattr(appmod, "_verify_session", fake_verify)
        app = _build(verify_cookie=True, auth_service_base="http://x", login_url="")
        r = await _get(app, "/who", {"accept": "text/html"})
        assert r.status_code == 401 and "Sign in" in r.text

    asyncio.run(go())


def test_header_edge_mode_trusts_x_auth_user():
    async def go():
        app = _build(trust_header=True)
        r = await _get(app, "/who", {"x-auth-user": "bob@lab"})
        assert r.json()["owner"] == "bob@lab"
    asyncio.run(go())
