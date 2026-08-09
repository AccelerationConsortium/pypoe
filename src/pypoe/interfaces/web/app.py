import asyncio
import json
import os
import secrets
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from fastapi import FastAPI, Request, Form, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from ...core.config import get_config, Config
from ...core.client import PoeChatClient
from ...core.history import owner_ctx, _UNSCOPED
from ...core.logging_db import logger
from ...core.models import (
    CHAT_MODELS,
    DEFAULT_CHAT_MODEL,
    models_by_provider,
    provider_for,
)
from ...core.provider_health import (
    ACCOUNT_BLOCKING_REASONS,
    component_for,
    probe_provider,
    registry as health,
)
from ...core.providers import (
    POE,
    PROVIDERS,
    api_key_for,
    configured_providers,
    fetch_credits,
    get_provider,
)

# Standard-library logger for diagnostics that don't fit the structured
# PyPoeLogger above (e.g. optional lab-integration wiring).
import logging
_stdlib_logger = logging.getLogger(__name__)


# Edge path-prefix (single-edge SSO). When PyPoe's UI is served behind the shared
# auth edge at ``/pypoe/`` (Caddy ``handle_path /pypoe/* { header_up
# X-Forwarded-Prefix /pypoe }``), Caddy strips the prefix off the path but tells
# us via ``X-Forwarded-Prefix`` so we can put it back on the URLs the browser
# sees (PyPoe's own assets / links / API / WS). Absent header (direct :8006
# access) => empty prefix => URLs are unprefixed exactly as before. The shared
# ``/auth/*`` surface is NOT prefixed — it lives at the edge root. Exposed to
# templates as the Jinja global ``base_path()`` and to browser JS as
# ``window.PYPOE_BASE``.
import contextvars

_edge_prefix_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pypoe_edge_prefix", default=""
)


class _ForwardedPrefixMiddleware:
    """Bind ``X-Forwarded-Prefix`` into ``_edge_prefix_var`` for the request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            prefix = ""
            for key, value in scope.get("headers", []):
                if key == b"x-forwarded-prefix":
                    prefix = "/" + value.decode("latin1").strip().strip("/")
                    prefix = "" if prefix == "/" else prefix
                    break
            token = _edge_prefix_var.set(prefix)
            try:
                await self.app(scope, receive, send)
            finally:
                _edge_prefix_var.reset(token)
        else:
            await self.app(scope, receive, send)


# Paths that stay reachable even when cookie-verify gating is on: the
# STATUS_SPEC probes the aggregator polls, static assets, and the Kuma
# webhook. Everything else (the UI + /api/*) is gated in cookie-verify mode.
_PUBLIC_EXACT = {"/health", "/status", "/", "/favicon.ico", "/kuma/status"}
_PUBLIC_PREFIXES = ("/static/", "/alerts/", "/control/")


async def _verify_session(auth_service_base: str, cookie_header: str):
    """Validate a session cookie against the ac_auth sidecar's /auth/verify.

    Mirrors the dashboard's Next.js middleware. Returns the resolved user
    (str), ``None`` when the sidecar says unauthenticated (401/403), or the
    string ``"unreachable"`` when we could not reach/parse the sidecar (so the
    caller can fail *open* rather than lock everyone out during an outage).
    Broken out as a module function so tests can monkeypatch it.
    """
    try:
        import httpx
    except Exception:
        return "unreachable"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{auth_service_base}/auth/verify",
                headers={"cookie": cookie_header},
            )
    except Exception:
        return "unreachable"
    if resp.status_code == 200:
        return resp.headers.get("x-auth-user") or None
    if resp.status_code in (401, 403):
        return None
    return "unreachable"


class _OwnerScopeMiddleware:
    """Pure-ASGI middleware that binds the per-request signed-in user (§4.8).

    Two opt-in modes (default: neither set => open/unscoped, unchanged):

    * **header/edge** (``trust_header``, ``PYPOE_TRUST_FORWARD_AUTH``): trust
      the ``X-Auth-User`` header injected by a Caddy ``forward_auth`` edge —
      for the eventual off-Tailnet public deploy.
    * **cookie-verify** (``verify_cookie``, ``PYPOE_AUTH_VERIFY_COOKIE``): no
      edge — validate the request's ``ac_auth_session`` cookie against the
      ac_auth sidecar's ``GET /auth/verify`` (exactly like the dashboard's
      Next.js middleware) and read the resolved ``X-Auth-User``. Fits the
      current Tailnet reality (no Caddy).

    Whichever resolves an identity, it is bound to ``owner_ctx`` so the shared
    ``HistoryManager`` scopes conversations to that user with no per-route
    changes (websockets included). Pure ASGI (not BaseHTTPMiddleware) so the
    contextvar reliably propagates into the endpoint's context.

    In cookie-verify mode PyPoe's reads are *private per-user chat*, so reads
    are gated too: an unauthenticated HTML ``GET`` is redirected to
    ``login_url`` (else 401), XHR gets 401, and websockets are closed. Fails
    **closed** on a missing/invalid cookie, but **open** if the sidecar is
    unreachable (an outage must not lock everyone out).
    """

    def __init__(self, app, *, trust_header: bool = False,
                 verify_cookie: bool = False,
                 auth_service_base: str = "", login_url: str = ""):
        self.app = app
        self.trust_header = trust_header
        self.verify_cookie = verify_cookie
        self.auth_service_base = (auth_service_base or "").rstrip("/")
        self.login_url = login_url

    def _is_public(self, path: str) -> bool:
        return path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES)

    async def __call__(self, scope, receive, send):
        stype = scope.get("type")
        if stype not in ("http", "websocket") or not (
            self.trust_header or self.verify_cookie
        ):
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers") or ()
        user = None

        # Header/edge mode first (cheap, no I/O).
        if self.trust_header:
            for key, value in headers:
                if key == b"x-auth-user" and value:
                    user = value.decode("latin1")
                    break

        # Cookie-verify mode: hit the sidecar unless this path is public.
        if user is None and self.verify_cookie and not self._is_public(
            scope.get("path", "")
        ):
            cookie = ""
            for key, value in headers:
                if key == b"cookie":
                    cookie = value.decode("latin1")
                    break
            verdict = await _verify_session(self.auth_service_base, cookie)
            if verdict == "unreachable":
                # Fail open: proceed unscoped rather than lock everyone out.
                _stdlib_logger.warning(
                    "ac_auth sidecar unreachable at %s; failing open (unscoped)",
                    self.auth_service_base,
                )
                await self.app(scope, receive, send)
                return
            if verdict is None:
                # Fail closed: not authenticated.
                await self._reject(scope, receive, send)
                return
            user = verdict

        token = owner_ctx.set(user) if user else None
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                owner_ctx.reset(token)

    async def _reject(self, scope, receive, send):
        if scope.get("type") == "websocket":
            # Consume the connect event, then refuse the handshake.
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        accept = ""
        for key, value in scope.get("headers") or ():
            if key == b"accept":
                accept = value.decode("latin1")
                break
        wants_html = scope.get("method") == "GET" and "text/html" in accept
        if wants_html and self.login_url:
            await send({
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", self.login_url.encode("latin1"))],
            })
            await send({"type": "http.response.body", "body": b""})
            return
        if wants_html:
            body = (
                b"<!doctype html><meta charset=utf-8><title>Sign in required</title>"
                b"<body style='font-family:sans-serif;padding:2rem'>"
                b"<h3>Sign in required</h3><p>Sign in on the lab dashboard, "
                b"then reload PyPoe.</p></body>"
            )
            ctype = b"text/html; charset=utf-8"
        else:
            body = b'{"detail":"authentication required"}'
            ctype = b"application/json"
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", ctype),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


class _CanonicalHostMiddleware:
    """Redirect browser navigations to the canonical MagicDNS host (§4.8).

    The ac_auth_session cookie is ``Domain``-scoped (e.g. ``tail6a1dd7.ts.net``)
    and is therefore **never sent to a raw IP**. If a user reaches PyPoe by IP,
    a 302 to the same path on ``canonical_host`` bounces them to the hostname,
    where the browser attaches the cookie on the follow-up request. Only HTML
    ``GET`` navigations are redirected — API/health/status/websocket and every
    non-GET pass untouched, so IP-based automation/polling still works. No-op
    when ``canonical_host`` is unset. Registered OUTERMOST so it runs before
    the auth middleware.
    """

    def __init__(self, app, canonical_host: str = ""):
        self.app = app
        self.canonical_host = (canonical_host or "").strip()

    async def __call__(self, scope, receive, send):
        if (not self.canonical_host or scope.get("type") != "http"
                or scope.get("method") != "GET"):
            await self.app(scope, receive, send)
            return
        host = ""
        accept = ""
        for key, value in scope.get("headers") or ():
            if key == b"host":
                host = value.decode("latin1")
            elif key == b"accept":
                accept = value.decode("latin1")
        if "text/html" in accept and host and host != self.canonical_host:
            scheme = scope.get("scheme", "http")
            target = f"{scheme}://{self.canonical_host}{scope.get('path', '')}"
            qs = scope.get("query_string", b"")
            if qs:
                target += "?" + qs.decode("latin1")
            await send({
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", target.encode("latin1"))],
            })
            await send({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send)

# TODO: Add support for remote access of the webpage with username and password protection
# This would involve:
# - Adding authentication middleware (e.g., HTTP Basic Auth, session-based auth, or JWT)
# - User management system with secure password storage
# - Login/logout endpoints and templates
# - Session management and CSRF protection
# - Rate limiting and security headers
# - Optional: Multi-user support with user-specific conversation isolation

# Check if web dependencies are available
try:
    import fastapi
    import jinja2
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

if not WEB_AVAILABLE:
    raise ImportError(
        "Web UI dependencies not installed. Please install with: pip install -e '.[web-ui]'"
    )

# --- Debate role presets ---
#
# These map each preset key to a system-prompt blurb that's interpolated
# into every model's debate prompt. Keep blurbs imperative, second-person,
# and brief — long descriptions push the actual topic out of attention.
DEBATE_ROLE_PRESETS: Dict[str, str] = {
    "defend": "Argue in favor of the topic. Steelman the strongest version "
              "of the affirmative case.",
    "critique": "Find flaws, edge cases, and missed risks. Be specific.",
    "steelman_opposite": "Argue the strongest version of the opposing view, "
                          "even if you personally disagree.",
    "devils_advocate": "Pick the position the user is least likely to be "
                        "considering and defend it.",
    "synthesizer": "Find common ground between the other participants and "
                    "produce a merged recommendation.",
    "custom": None,  # uses custom_label
}


# Pydantic models for request bodies
class BotAssignment(BaseModel):
    role: str
    custom_label: Optional[str] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = None  # Optional title, will generate timestamp if empty
    bot_name: str
    chat_mode: Optional[str] = "chatbot"  # chatbot, group, debate
    # Required for chat_mode in ('group','debate'); exactly 2 participants
    # drawn from CHAT_MODELS. Ignored for 'chatbot'.
    bot_names: Optional[List[str]] = None
    # Required for chat_mode='debate'. Keys must equal bot_names exactly.
    bot_assignments: Optional[Dict[str, BotAssignment]] = None
    # Required for chat_mode='debate'. The pinned shared context.
    debate_topic: Optional[str] = None


class ConversationPatch(BaseModel):
    """Partial update payload for PATCH /api/conversation/{id}.

    Currently scoped to debate-only fields — the topic and per-bot role
    assignments can be edited at any time and take effect on the next turn.
    """
    debate_topic: Optional[str] = None
    bot_assignments: Optional[Dict[str, BotAssignment]] = None


class MessageSend(BaseModel):
    message: str
    bot_name: Optional[str] = None
    chat_mode: Optional[str] = None


def _validate_bot_assignments(
    assignments: Dict[str, BotAssignment],
    bot_names: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Validate debate role assignments and return a JSON-serialisable dict.

    Raises HTTPException on the first failure so the caller doesn't have to
    repeat error wrapping. The returned dict is the on-disk shape:
    ``{bot_name: {role, custom_label}}``.
    """
    if set(assignments.keys()) != set(bot_names):
        raise HTTPException(
            status_code=400,
            detail=(
                f"bot_assignments keys ({sorted(assignments.keys())}) "
                f"must exactly match bot_names ({sorted(bot_names)})."
            ),
        )
    result: Dict[str, Dict[str, Any]] = {}
    for bot, assignment in assignments.items():
        if assignment.role not in DEBATE_ROLE_PRESETS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown role '{assignment.role}' for bot '{bot}'. "
                    f"Pick one of: {sorted(DEBATE_ROLE_PRESETS.keys())}."
                ),
            )
        if assignment.role == "custom":
            label = (assignment.custom_label or "").strip()
            if not label:
                raise HTTPException(
                    status_code=400,
                    detail=f"role='custom' requires a non-empty custom_label (bot '{bot}').",
                )
        result[bot] = {
            "role": assignment.role,
            "custom_label": (assignment.custom_label or "").strip() or None,
        }
    return result

class ClaimRequest(BaseModel):
    owner: str
    session_id: str
    ttl_s: float = 30.0

class WebApp:
    """FastAPI web application for PyPoe chat interface."""
    
    def __init__(self, config: Config = None):
        if config is None:
            config = get_config()
        
        self.config = config
        self.app = FastAPI(title="PyPoe Web Interface", version="2.0.0")
        
        # Add CORS middleware for React frontend
        self.app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|100\.64\.\d{1,3}\.\d{1,3}):(3000|5173|8000)",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Owner-scoping (§4.8): bind the per-request signed-in user (from the
        # ac_auth edge's X-Auth-User header) so the shared client's history is
        # scoped per user. Gated by PYPOE_TRUST_FORWARD_AUTH.
        self.app.add_middleware(
            _OwnerScopeMiddleware,
            trust_header=config.web_trust_forward_auth,
            verify_cookie=config.web_auth_verify_cookie,
            auth_service_base=config.web_auth_service_base,
            login_url=config.web_login_url,
        )

        # Added AFTER the auth middleware so it is OUTERMOST and runs first: a
        # browser hitting the raw IP is bounced to the MagicDNS host (where the
        # ac_auth_session domain cookie attaches) before the auth check runs.
        self.app.add_middleware(
            _CanonicalHostMiddleware,
            canonical_host=config.web_canonical_host,
        )

        # Added last => OUTERMOST: capture the edge path-prefix before any
        # template renders, so {{ base_path() }} / window.PYPOE_BASE are correct.
        self.app.add_middleware(_ForwardedPrefixMiddleware)

        self.client = PoeChatClient(config=config)
        
        # Setup templates and static files
        self.templates_dir = Path(__file__).parent / "templates"
        self.static_dir = Path(__file__).parent / "static"
        
        # Create directories if they don't exist
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.static_dir.mkdir(parents=True, exist_ok=True)
        
        self.templates = Jinja2Templates(directory=str(self.templates_dir))
        # Single-edge SSO: templates prefix PyPoe's own URLs with {{ base_path() }}
        # so they resolve under /pypoe/ when served behind the edge (empty when
        # hit directly on :8006). See _ForwardedPrefixMiddleware.
        self.templates.env.globals["base_path"] = lambda: _edge_prefix_var.get("")
        # Cache-busting: a token from the static files' mtimes, computed once at
        # startup and appended as ?v=<token> to /static/* URLs in the templates.
        # A deploy changes the mtimes -> new token -> browsers fetch fresh
        # JS/CSS instead of serving a stale cached copy; unchanged files keep
        # the same token so normal caching still applies. (StaticFiles sends no
        # Cache-Control, so without this a browser can cling to an old asset.)
        try:
            _mtimes = [p.stat().st_mtime for p in self.static_dir.glob("*") if p.is_file()]
            _asset_v = str(int(max(_mtimes))) if _mtimes else "0"
        except OSError:
            _asset_v = "0"
        self.templates.env.globals["asset_v"] = _asset_v

        # Mount static files
        self.app.mount("/static", StaticFiles(directory=str(self.static_dir)), name="static")
        
        # Auth is enforced at the ac_auth Caddy edge (§4.8), not here; the old
        # shared Basic-auth gate is retired. Per-user scoping is applied by
        # _OwnerScopeMiddleware from the X-Auth-User header.
        self.security = None
        
        # Active WebSocket connections for real-time chat
        self.active_connections: List[WebSocket] = []
        self._status_cache: Optional[Dict[str, Any]] = None
        self._status_cache_expires_at = 0.0
        self._kuma_status_cache: Optional[Dict[str, Any]] = None
        self._kuma_status_cache_expires_at = 0.0
        self._claim: Optional[Dict[str, Any]] = None
        
        self._setup_routes()

        # Optional: POST /alerts/kuma webhook for the AC Organic Self-driving
        # Lab. Activated by LAB_API_URL or PYPOE_ENABLE_LAB. Imports are local
        # so the web app still starts if the lab extra isn't installed.
        self._maybe_register_lab_alert_routes()

        # Log system startup
        logger.log_system_event(
            event_type="startup",
            component="backend",
            action="start",
            new_value={
                "version": "2.0.0",
                "authentication_enabled": self.config.web_trust_forward_auth,
                "cors_enabled": True,
                "websocket_enabled": True
            },
            metadata={
                "config_file": str(self.config.config_file) if hasattr(self.config, 'config_file') else None,
                "database_path": str(self.config.database_path)
            }
        )
    
    async def _generate_topic_from_message(self, first_message: str) -> str:
        """Generate a short topic (less than 5 words) from the first user message."""
        try:
            # First try the fallback method (no AI required)
            fallback_topic = self._generate_fallback_topic(first_message)
            if fallback_topic and fallback_topic != "Chat Topic":
                print(f"Using fallback topic: '{fallback_topic}'")
                return fallback_topic
            
            # If fallback is not good enough, try AI models
            models_to_try = list(CHAT_MODELS)
            
            for model in models_to_try:
                try:
                    # Use a fast model to generate the topic
                    topic_prompt = f"Summarize this question/message in exactly 3-4 words (no more than 5 words): '{first_message}'"
                    
                    full_response = ""
                    import asyncio
                    
                    # Add timeout to prevent hanging
                    try:
                        async with asyncio.timeout(10):  # 10 second timeout
                            async for chunk in self.client.send_message(
                                message=topic_prompt,
                                bot_name=model,
                                save_history=False  # Don't save this internal conversation
                            ):
                                full_response += chunk
                    except asyncio.TimeoutError:
                        print(f"Topic generation timed out for {model}")
                        continue
                    
                    # Clean up the response - remove quotes, extra punctuation
                    topic = full_response.strip().strip('"').strip("'").strip('.').strip()
                    
                    # Ensure it's not too long (max 5 words)
                    words = topic.split()
                    if len(words) > 5:
                        topic = ' '.join(words[:5])
                    
                    if topic and topic.lower() not in ['error', 'failed', 'sorry', 'cannot']:
                        print(f"Generated topic using {model}: '{topic}'")
                        return topic
                        
                except Exception as model_error:
                    print(f"Failed to generate topic with {model}: {model_error}")
                    continue
            
            # If all models fail, use fallback
            print("All models failed for topic generation, using fallback")
            return self._generate_fallback_topic(first_message)
            
        except Exception as e:
            print(f"Warning: Failed to generate topic: {e}")
            return self._generate_fallback_topic(first_message)
    
    def _generate_fallback_topic(self, first_message: str) -> str:
        """Generate a simple fallback topic from the first message."""
        try:
            # Remove common words and punctuation
            import re
            cleaned_message = re.sub(r'[^\w\s]', '', first_message.lower())
            
            # Split into words and filter out common words
            common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'can', 'may', 'might', 'must', 'shall', 'what', 'when', 'where', 'why', 'how', 'who', 'which', 'that', 'this', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'hello', 'hi', 'hey', 'please', 'help', 'thanks', 'thank'}
            
            words = [word for word in cleaned_message.split() if word not in common_words and len(word) > 2]
            
            # Take first 3-4 meaningful words
            if words:
                topic = ' '.join(words[:4])
                return topic.title()  # Capitalize first letter of each word
            
            # If no meaningful words, use first few characters
            if len(first_message) > 10:
                return first_message[:15].strip().title()
            else:
                return first_message.strip().title()
                
        except Exception as e:
            print(f"Warning: Fallback topic generation failed: {e}")
            # Last resort: use first few words
            words = first_message.split()[:3]
            return ' '.join(words) if words else "Chat Topic"
    
    async def _generate_and_save_topic(self, conversation_id: str, user_message: str):
        """Generate and save topic in background without blocking the WebSocket."""
        try:
            print(f"Starting topic generation for conversation {conversation_id}")
            print(f"First message: '{user_message[:100]}...'")
            
            topic = await self._generate_topic_from_message(user_message)
            
            print(f"Generated topic: '{topic}'")
            
            # Update the conversation with the generated topic
            import aiosqlite
            async with self.client.history._lock:
                async with aiosqlite.connect(self.client.history.db_path) as db:
                    await db.execute(
                        "UPDATE conversations SET topic = ? WHERE id = ?",
                        (topic, conversation_id)
                    )
                    await db.commit()
            
            print(f"Successfully saved topic '{topic}' for conversation {conversation_id}")
            
            # Notify connected clients about the topic update
            try:
                for connection in self.active_connections:
                    try:
                        await connection.send_text(json.dumps({
                            "type": "topic_updated",
                            "conversation_id": conversation_id,
                            "topic": topic
                        }))
                    except Exception as notify_error:
                        print(f"Failed to notify client about topic update: {notify_error}")
            except Exception as notify_error:
                print(f"Failed to notify clients about topic update: {notify_error}")
            
        except Exception as e:
            print(f"Failed to generate and save topic: {e}")
            import traceback
            traceback.print_exc()

    async def _fan_out_to_models(
        self,
        websocket: WebSocket,
        conversation: Dict[str, Any],
        user_message: str,
    ) -> None:
        """Stream a user message to all participants of a group/debate conversation.

        Each bot reply streams onto the shared WebSocket in frames tagged
        ``model_name``. The single user row and each assistant row are saved
        once. An ``asyncio.Lock`` serialises frame writes so concurrent
        deltas don't interleave inside a single JSON line.

        For ``chat_mode='debate'`` each model receives a per-bot transcript
        whose first entry is a synthesised system message naming the topic,
        this model's assigned role, and every other participant's role.
        """

        conversation_id = conversation['id']
        bot_names: List[str] = conversation.get('bot_names') or []
        chat_mode: str = conversation.get('chat_mode') or 'group'
        debate_topic: Optional[str] = conversation.get('debate_topic')
        bot_assignments: Dict[str, Dict[str, Any]] = (
            conversation.get('bot_assignments') or {}
        )

        # Echo the user message to the client.
        await websocket.send_text(json.dumps({
            "type": "user_message",
            "content": user_message,
            "role": "user",
        }))

        # Persist the user row once, before any model reads the transcript.
        await self.client.history.add_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )

        # Snapshot history; we'll rebuild the transcript per-bot so each
        # model can tell which assistant turns came from itself vs. the
        # other participants.
        existing = await self.client.get_conversation_messages(conversation_id)

        send_lock = asyncio.Lock()

        def _transcript_for(bot_name: str) -> List[Dict[str, str]]:
            """Build a per-bot transcript.

            Other bots' assistant turns are attributed with ``[from <Model>]:``
            so the receiving bot can distinguish speakers. Consecutive
            assistant turns from one round are collapsed into a single
            assistant turn separated by blank lines, so the upstream API
            still sees user/assistant alternation.
            """
            out: List[Dict[str, str]] = []
            pending: List[str] = []

            def flush() -> None:
                if pending:
                    out.append({"role": "assistant", "content": "\n\n".join(pending)})
                    pending.clear()

            for m in existing:
                if m["role"] == "assistant":
                    model = m.get("model_name")
                    if model and model != bot_name:
                        pending.append(f"[from {model}]: {m['content']}")
                    else:
                        pending.append(m["content"])
                else:
                    flush()
                    out.append({"role": m["role"], "content": m["content"]})
            flush()

            if chat_mode == "debate":
                system_prompt = self._build_debate_system_prompt(
                    topic=debate_topic or "",
                    this_bot=bot_name,
                    bot_names=bot_names,
                    bot_assignments=bot_assignments,
                )
            else:
                # Group mode: tell the bot the multi-bot convention so it
                # trusts the `[from <Model>]:` tag rather than treating it
                # as a prompt-injection attempt.
                system_prompt = self._build_group_system_prompt(
                    this_bot=bot_name,
                    bot_names=bot_names,
                )
            if system_prompt:
                return [{"role": "system", "content": system_prompt}, *out]
            return out

        async def _stream_one(bot_name: str) -> None:
            async with send_lock:
                await websocket.send_text(json.dumps({
                    "type": "bot_response_start",
                    "role": "assistant",
                    "model_name": bot_name,
                }))

            full_response = ""
            try:
                async for partial in self.client.send_conversation(
                    messages=_transcript_for(bot_name),
                    bot_name=bot_name,
                    conversation_id=conversation_id,
                    save_history=False,
                ):
                    if not partial:
                        continue
                    full_response += partial
                    async with send_lock:
                        await websocket.send_text(json.dumps({
                            "type": "bot_response_chunk",
                            "content": partial,
                            "role": "assistant",
                            "model_name": bot_name,
                        }))
            except Exception as exc:
                async with send_lock:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"{bot_name}: {exc}",
                        "model_name": bot_name,
                    }))

            if full_response:
                await self.client.history.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_response,
                    model_name=bot_name,
                )

            async with send_lock:
                await websocket.send_text(json.dumps({
                    "type": "bot_response_end",
                    "role": "assistant",
                    "model_name": bot_name,
                }))

        await asyncio.gather(
            *(_stream_one(bot) for bot in bot_names),
            return_exceptions=False,
        )

    @staticmethod
    def _build_group_system_prompt(
        *,
        this_bot: str,
        bot_names: List[str],
    ) -> Optional[str]:
        """Brief preamble for group-chat fan-out.

        The point is to make the multi-bot context legible so each model
        understands that text tagged with ``[from <ModelName>]:`` inside
        an assistant turn was produced by a peer, not by itself. Without
        this, models tend to read the tag as a prompt-injection attempt
        and refuse to engage with it.
        """
        others = [b for b in bot_names if b != this_bot]
        if not others:
            return None
        others_list = ", ".join(others)
        return (
            f"You are {this_bot}, participating in a group chat with: "
            f"{others_list}.\n\n"
            "In the transcript, your own prior replies appear as normal "
            "assistant turns. The other models' replies appear within "
            "assistant turns prefixed with `[from <ModelName>]:`. These "
            "prefixed segments are NOT your own words — they are the other "
            "models' contributions, included so you have the full chat "
            "context.\n\n"
            "When the user asks about another model, refer to that model by name."
        )

    @staticmethod
    def _build_debate_system_prompt(
        *,
        topic: str,
        this_bot: str,
        bot_names: List[str],
        bot_assignments: Dict[str, Dict[str, Any]],
    ) -> str:
        """Assemble a model's debate system message.

        Names the topic, this model's role, and every other participant's
        role so the model can address them explicitly. The phrasing matches
        the template in CLAUDE.local.md Phase 2 §"System prompt template".
        """

        def _describe(bot: str) -> str:
            assignment = bot_assignments.get(bot, {}) or {}
            role = assignment.get("role") or "custom"
            if role == "custom":
                label = assignment.get("custom_label") or ""
                return label or "a custom role"
            blurb = DEBATE_ROLE_PRESETS.get(role)
            return blurb or role

        others_lines = [
            f"  - {bot}: {_describe(bot)}"
            for bot in bot_names if bot != this_bot
        ]
        others_block = "\n".join(others_lines) if others_lines else "  (none)"

        return (
            "You are participating in a structured debate.\n\n"
            f"TOPIC:\n{topic}\n\n"
            f"YOUR ROLE: {_describe(this_bot)}\n\n"
            "OTHER PARTICIPANTS:\n"
            f"{others_block}\n\n"
            "Reply concisely. You may reference other participants by name. "
            "The transcript follows."
        )

    def _current_user(self, request) -> Optional[str]:
        """The signed-in user for this request (§4.8), for the UI banner.

        Reads whatever ``_OwnerScopeMiddleware`` resolved into ``owner_ctx``
        (header/edge or cookie-verify), so it works in both modes. ``None``
        when unauthenticated / auth disabled.
        """
        value = owner_ctx.get()
        return None if value is _UNSCOPED else value

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _probe_payload(self) -> Dict[str, Any]:
        return {
            "equipment_id": "pypoe_web",
            "equipment_name": "PyPoe Web UI",
            "protocol_version": "1.1",
        }

    def _component(self, connected: bool, state: str, message: Optional[str] = None) -> Dict[str, Any]:
        return {
            "connected": connected,
            "state": state,
            "message": message,
            "last_event_at": None,
        }

    def _metric(self, value: Union[float, int, str, bool], unit: Optional[str] = None) -> Dict[str, Any]:
        return {
            "value": value,
            "unit": unit,
            "timestamp": self._now_utc().isoformat(),
        }

    def _tcp_check(self, host: str, port: int, timeout_s: float = 1.0) -> Tuple[bool, Optional[float], Optional[str]]:
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                return True, elapsed_ms, None
        except OSError as exc:
            return False, None, str(exc)

    def _ip_brief(self) -> str:
        try:
            result = subprocess.run(
                ["ip", "-brief", "addr"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            return result.stdout if result.returncode == 0 else ""
        except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            return ""

    def _network_components(self) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        components: Dict[str, Any] = {}
        metrics: Dict[str, Any] = {}
        details: Dict[str, Any] = {}

        internet_ok, internet_ms, internet_error = self._tcp_check("1.1.1.1", 443)
        components["internet"] = self._component(
            internet_ok,
            "reachable" if internet_ok else "unreachable",
            internet_error,
        )
        if internet_ms is not None:
            metrics["internet_latency"] = self._metric(internet_ms, "ms")

        ip_brief = self._ip_brief()
        details["ip_brief"] = ip_brief.strip()
        tailscale_ok = "tailscale0" in ip_brief and "100.64." in ip_brief
        components["tailscale"] = self._component(
            tailscale_ok,
            "up" if tailscale_ok else "down",
            None if tailscale_ok else "tailscale0 with 100.64.x address not detected",
        )

        wifi_lines = [line for line in ip_brief.splitlines() if line.startswith(("wl", "wlan"))]
        wifi_ok = any("UP" in line and "172.31." in line for line in wifi_lines)
        components["wifi"] = self._component(
            wifi_ok,
            "associated" if wifi_ok else "not_associated",
            None if wifi_ok else "no UP WiFi interface with lab address detected",
        )
        details["wifi_interfaces"] = wifi_lines

        return components, metrics, details

    def _active_claim(self) -> Optional[Dict[str, Any]]:
        if self._claim is None:
            return None
        if self._claim["expires_at"] <= self._now_utc():
            self._claim = None
            return None
        return self._claim

    def _claimed_by(self) -> Optional[Dict[str, Any]]:
        claim = self._active_claim()
        if claim is None:
            return None
        return {
            "session_id": claim["session_id"],
            "owner": claim["owner"],
            "expires_at": claim["expires_at"].isoformat(),
        }

    @staticmethod
    def _bot_providers(bots: List[str]) -> Dict[str, Dict[str, str]]:
        """``{model: {provider, label}}`` for a roster.

        Sent alongside the existing flat ``bots`` list rather than replacing
        it: the model id remains the single identity everywhere (dropdowns, the
        ``bot_name`` history column, group/debate validation), so this is
        additive metadata that the three separate UIs can adopt at their own
        pace without any of them breaking today.
        """
        out: Dict[str, Dict[str, str]] = {}
        for model in bots:
            spec = get_provider(provider_for(model))
            out[model] = {"provider": spec.name, "label": spec.label}
        return out

    @staticmethod
    def _provider_component_names(components: Dict[str, Any]) -> List[str]:
        """Provider names that have a component in this envelope."""
        return [
            name for name in PROVIDERS
            if f"{name}_api" in components
        ]

    def _probe_model_for(self, provider_name: str) -> str:
        """Which model to probe a provider with.

        The default chat model when that provider owns it — an access problem
        on the model users actually get is what makes PyPoe unusable — else the
        provider's first roster entry. ``PYPOE_HEALTH_PROBE_MODEL`` overrides
        globally for a cheaper target.
        """
        override = os.environ.get("PYPOE_HEALTH_PROBE_MODEL")
        if override:
            return override
        if provider_for(DEFAULT_CHAT_MODEL) == provider_name:
            return DEFAULT_CHAT_MODEL
        owned = models_by_provider().get(provider_name) or []
        return owned[0] if owned else DEFAULT_CHAT_MODEL

    async def _provider_components(
        self, device_time: datetime
    ) -> Tuple[Dict[str, Any], Dict[str, Any], List[str], Optional[Dict[str, Any]], Dict[str, Any]]:
        """One ComponentStatus per model provider, from real evidence.

        This used to be a single ``poe_api`` component checked with
        ``client.get_available_bots()`` — a hardcoded local list that never
        touches the network — so it read ``connected`` whenever ``POE_API_KEY``
        was merely set, and a lapsed Poe subscription (every chat failing with
        ``subscription_required``) left the tile reporting ``ready``: exactly
        the §2.2 violation the spec forbids.

        Evidence comes from :mod:`pypoe.core.provider_health` — passively from
        real chat traffic, actively from a ``max_tokens=1`` probe only when that
        evidence has gone stale (see that module for the cost asymmetry that
        makes the probe cheap).

        Returns ``(components, metrics, healthy_provider_names, last_error,
        details)``. Providers with no key configured are omitted entirely
        rather than reported unhealthy — an unconfigured provider is not a
        fault, and listing it would make a working single-provider deployment
        permanently degraded.
        """
        components: Dict[str, Any] = {}
        metrics: Dict[str, Any] = {}
        details: Dict[str, Any] = {}
        healthy: List[str] = []
        errors: List[Tuple[str, Dict[str, Any]]] = []

        names = configured_providers(self.config)
        if not names:
            # Nothing configured at all: report Poe as the canonical missing
            # one so the envelope still explains why chat cannot work.
            names = [POE]

        for name in names:
            spec = get_provider(name)
            tracker = health.for_provider(name)
            api_key = api_key_for(spec, self.config)

            if not api_key:
                tracker.record_not_configured()
            elif tracker.needs_probe():
                start = time.perf_counter()
                ok, reason, message = await probe_provider(
                    spec, api_key, self._probe_model_for(name)
                )
                metrics[f"{name}_response_time"] = self._metric(
                    round((time.perf_counter() - start) * 1000, 2), "ms"
                )
                if ok:
                    tracker.record_success(source="probe")
                    # Balance only matters for a metered provider, and only
                    # when it can actually be reached.
                    tracker.record_credits(
                        await fetch_credits(spec, api_key=api_key)
                    )
                else:
                    tracker.record_failure(reason or "api_error", message or "", source="probe")

            state = tracker.snapshot()
            rendered = component_for(
                state,
                low_credit_threshold=(
                    getattr(self.config, "openrouter_min_credits", 0.0)
                    if spec.metered
                    else 0.0
                ),
            )
            component = self._component(
                rendered["connected"], rendered["state"], rendered["message"]
            )
            if state.observed_at is not None:
                component["last_event_at"] = state.observed_at.isoformat()
            components[f"{name}_api"] = component

            if state.credits:
                details[f"{name}_credits"] = state.credits
                remaining = state.credits.get("remaining")
                if remaining is not None:
                    metrics[f"{name}_credits_remaining"] = self._metric(remaining, "USD")

            if rendered["connected"]:
                healthy.append(name)
            elif state.reason is not None:
                errors.append(
                    (
                        name,
                        {
                            "code": state.code,
                            "message": rendered["message"],
                            # An account-level outage stops that provider doing
                            # its job at all; a rate limit or a bad model name
                            # does not.
                            "severity": (
                                "error"
                                if state.reason in ACCOUNT_BLOCKING_REASONS
                                else "warning"
                            ),
                            "timestamp": (state.observed_at or device_time).isoformat(),
                        },
                    )
                )

        details["providers"] = {
            name: {
                "label": get_provider(name).label,
                "state": components[f"{name}_api"]["state"],
                "models": models_by_provider().get(name, []),
            }
            for name in names
            if f"{name}_api" in components
        }

        # Prefer an account-level error for last_error; among equals, the
        # first configured provider wins so the field is deterministic.
        last_error = None
        if errors:
            errors.sort(key=lambda item: item[1]["severity"] != "error")
            last_error = errors[0][1]

        return components, metrics, healthy, last_error, details

    async def _status_payload(self) -> Dict[str, Any]:
        now = time.monotonic()
        if self._status_cache is not None and now < self._status_cache_expires_at:
            cached = dict(self._status_cache)
            cached["device_time"] = self._now_utc().isoformat()
            cached.setdefault("details", {})["claimed_by"] = self._claimed_by()
            return cached

        device_time = self._now_utc()
        components: Dict[str, Any] = {"web_ui": self._component(True, "serving")}
        metrics: Dict[str, Any] = {}
        details: Dict[str, Any] = {}
        last_error = None

        (
            provider_components,
            provider_metrics,
            healthy_providers,
            last_error,
            provider_details,
        ) = await self._provider_components(device_time)
        components.update(provider_components)
        metrics.update(provider_metrics)
        details.update(provider_details)

        storage_ok = True
        storage_message = None
        try:
            import os
            if os.path.exists(self.config.database_path):
                db_size = os.path.getsize(self.config.database_path)
                metrics["database_size"] = self._metric(round(db_size / 1024 / 1024, 2), "MB")
            conversations = await self.client.get_conversations()
            metrics["total_conversations"] = self._metric(len(conversations), "count")
        except Exception as exc:
            storage_ok = False
            storage_message = str(exc)
            if last_error is None:
                last_error = {
                    "code": "storage_error",
                    "message": str(exc),
                    "severity": "warning",
                    "timestamp": device_time.isoformat(),
                }
        components["storage"] = self._component(storage_ok, "ok" if storage_ok else "error", storage_message)

        network_components, network_metrics, network_details = await asyncio.to_thread(self._network_components)
        components.update(network_components)
        metrics.update(network_metrics)
        details.update(network_details)
        details["claimed_by"] = self._claimed_by()

        # Providers are graded as a group, not individually: with per-model
        # routing PyPoe can still chat as long as *one* provider answers, so a
        # dead Poe subscription alongside a working OpenRouter key is not a
        # service-level fault. Their individual components still report the
        # truth for whoever needs to see it.
        required_components = ["web_ui", "storage", "internet", "tailscale"]

        # Mutual watchdog: Uptime Kuma alerts when PyPoe is down; PyPoe's
        # /status (polled by the lab dashboard) surfaces Kuma being down.
        # Enabled by setting PYPOE_KUMA_URL (e.g. http://127.0.0.1:8005).
        import os
        kuma_url = os.environ.get("PYPOE_KUMA_URL")
        if kuma_url:
            from urllib.parse import urlparse
            parsed = urlparse(kuma_url)
            kuma_ok, kuma_ms, kuma_error = await asyncio.to_thread(
                self._tcp_check, parsed.hostname or "127.0.0.1", parsed.port or 80
            )
            components["uptime_kuma"] = self._component(
                kuma_ok,
                "reachable" if kuma_ok else "unreachable",
                kuma_error if not kuma_ok else None,
            )
            if kuma_ms is not None:
                metrics["kuma_latency"] = self._metric(kuma_ms, "ms")
            required_components.append("uptime_kuma")
        failed = [key for key in required_components if not components[key]["connected"]]
        required_ok = not failed and bool(healthy_providers)

        # Lead with the provider reason when model access is what's broken —
        # that is the difference between "a sub-component is flaky" and "no
        # chat request can succeed at all", and the operator needs the latter
        # stated plainly on the tile rather than inferred from a component name.
        provider_detail = None
        if not healthy_providers:
            broken = [
                (get_provider(name).label, components[f"{name}_api"].get("message"))
                for name in configured_providers(self.config) or [POE]
                if f"{name}_api" in components
                and not components[f"{name}_api"]["connected"]
            ]
            if broken:
                provider_detail = "; ".join(
                    f"{label}: {msg}" for label, msg in broken if msg
                ) or None

        if required_ok:
            equipment_status = "ready"
            message = None
            if len(healthy_providers) < len(self._provider_component_names(components)):
                # Still fully operational, but say which source is carrying it.
                message = "Serving via " + ", ".join(
                    get_provider(name).label for name in healthy_providers
                )
        elif components["web_ui"]["connected"] and components["storage"]["connected"]:
            equipment_status = "degraded"
            parts = []
            if not healthy_providers:
                parts.append(
                    f"No model provider available: {provider_detail}"
                    if provider_detail
                    else "No model provider available"
                )
            if failed:
                parts.append(f"Degraded components: {', '.join(failed)}")
            message = " | ".join(parts)
        else:
            equipment_status = "error"
            message = "PyPoe web service has critical component failures"

        payload = {
            "protocol_version": "1.1",
            "equipment_id": "pypoe_web",
            "equipment_name": "PyPoe Web UI",
            "equipment_kind": "other",
            "equipment_version": "2.7.0",
            "host": socket.gethostname(),
            "equipment_status": equipment_status,
            "message": message,
            "required_actions": [],
            "allowed_actions": [],
            "device_time": device_time.isoformat(),
            "uptime_seconds": None,
            "components": components,
            "metrics": metrics,
            "last_error": last_error,
            "details": details,
        }
        self._status_cache = dict(payload)
        self._status_cache_expires_at = now + 30.0
        return payload

    # Kuma heartbeat status ints → (connected, state) for ComponentStatus.
    _KUMA_BEAT_STATES = {
        0: (False, "down"),
        1: (True, "up"),
        2: (False, "pending"),
        3: (True, "maintenance"),
    }

    async def _kuma_status_payload(self) -> Dict[str, Any]:
        """STATUS_SPEC v1.0 envelope for Uptime Kuma, gateway-fronted by PyPoe.

        Registered in the lab's equipment.yaml as ``uptime_kuma`` with
        ``status_path: /kuma/status``. Per-monitor state comes from Kuma's
        unauthenticated status-page API (slug ``PYPOE_KUMA_STATUS_SLUG``,
        default ``lab``). Per the gateway rule (STATUS_SPEC §2.1), Kuma
        being unreachable reports ``equipment_status: "unknown"`` — never
        ``error``.
        """
        import os
        import re

        now = time.monotonic()
        if self._kuma_status_cache is not None and now < self._kuma_status_cache_expires_at:
            cached = dict(self._kuma_status_cache)
            cached["device_time"] = self._now_utc().isoformat()
            return cached

        kuma_url = os.environ.get("PYPOE_KUMA_URL", "http://127.0.0.1:8005").rstrip("/")
        slug = os.environ.get("PYPOE_KUMA_STATUS_SLUG", "lab")
        device_time = self._now_utc()

        components: Dict[str, Any] = {}
        metrics: Dict[str, Any] = {}
        message: Optional[str] = None
        equipment_status = "ready"

        try:
            import httpx

            async with httpx.AsyncClient(timeout=3.0) as client:
                page_resp = await client.get(f"{kuma_url}/api/status-page/{slug}")
                page_resp.raise_for_status()
                beats_resp = await client.get(
                    f"{kuma_url}/api/status-page/heartbeat/{slug}"
                )
                beats_resp.raise_for_status()
            page = page_resp.json()
            heartbeats = beats_resp.json().get("heartbeatList", {})

            monitors = [
                m
                for group in page.get("publicGroupList", [])
                for m in group.get("monitorList", [])
            ]
            up = total = 0
            down_names = []
            for monitor in monitors:
                beats = heartbeats.get(str(monitor.get("id"))) or []
                last = beats[-1] if beats else None
                if last is None:
                    connected, state = False, "pending"
                else:
                    connected, state = self._KUMA_BEAT_STATES.get(
                        last.get("status"), (False, "unknown")
                    )
                name = monitor.get("name") or f"monitor_{monitor.get('id')}"
                key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
                components[key] = self._component(connected, state, name)
                total += 1
                if connected:
                    up += 1
                elif state == "down":
                    down_names.append(name)
            metrics["monitors_up"] = self._metric(up, "count")
            metrics["monitors_total"] = self._metric(total, "count")
            if down_names:
                equipment_status = "degraded"
                message = f"{len(down_names)}/{total} monitors down: {', '.join(down_names)}"
        except Exception as exc:
            # Gateway-fronted unreachable → "unknown", never "error" (§2.1).
            equipment_status = "unknown"
            message = f"Uptime Kuma unreachable: {exc}"

        payload = {
            "protocol_version": "1.0",
            "equipment_id": "uptime_kuma",
            "equipment_name": "Uptime Kuma (alert watchdog)",
            "equipment_kind": "other",
            "equipment_version": None,
            "host": socket.gethostname(),
            "equipment_status": equipment_status,
            "message": message,
            "required_actions": [],
            "device_time": device_time.isoformat(),
            "uptime_seconds": None,
            "components": components,
            "metrics": metrics,
            "last_error": None,
            "details": {
                "status_page": f"{kuma_url}/status/{slug}",
                "gateway": "pypoe_web",
            },
        }
        self._kuma_status_cache = dict(payload)
        self._kuma_status_cache_expires_at = now + 15.0
        return payload

    def _maybe_register_lab_alert_routes(self) -> None:
        """Mount ``POST /alerts/kuma`` if the lab extra is installed AND
        ``LAB_API_URL`` / ``PYPOE_ENABLE_LAB`` is set in the environment.

        Imports stay local so PyPoe's web app still starts on hosts that
        don't have the lab extra installed.
        """
        import os
        if not (os.environ.get("LAB_API_URL") or os.environ.get("PYPOE_ENABLE_LAB")):
            return
        try:
            from ...lab.alert_routes import register_alert_routes
            from ...lab.http_client import LabClient
        except ImportError as exc:
            _stdlib_logger.warning("Lab alert routes not loaded: %s", exc)
            return

        try:
            self._lab_client = LabClient()
            register_alert_routes(self.app, client=self._lab_client)
            _stdlib_logger.info(
                "Mounted POST /alerts/kuma against %s",
                self._lab_client.base_url,
            )
        except Exception as exc:
            _stdlib_logger.warning("Failed to register /alerts/kuma: %s", exc)

    def _setup_routes(self):
        """Setup all the routes for the web application."""
        
        # Auth is enforced at the ac_auth edge (§4.8); no per-route Basic-auth
        # dependency. Per-user data scoping happens in _OwnerScopeMiddleware.
        dependencies = []

        @self.app.get("/", response_class=HTMLResponse, dependencies=dependencies)
        async def index(request: Request):
            """Main chat interface, or STATUS_SPEC probe for JSON clients."""
            accept = request.headers.get("accept", "")
            if "text/html" not in accept:
                return JSONResponse(self._probe_payload())
            try:
                conversations = await self.client.get_conversations()
                available_bots = await self.client.get_available_bots()
                return self.templates.TemplateResponse(
                    request,
                    "index.html",
                    {
                        "conversations": conversations,
                        "available_bots": available_bots,
                        "current_user": self._current_user(request),
                    },
                )
            except Exception as e:
                return HTMLResponse(f"Error loading interface: {str(e)}", status_code=500)

        @self.app.get("/health")
        async def lab_health():
            """STATUS_SPEC health endpoint."""
            return JSONResponse({"status": "healthy"})

        @self.app.get("/status")
        async def lab_status():
            """STATUS_SPEC v1.1 status endpoint for dashboard monitoring."""
            return JSONResponse(await self._status_payload())

        @self.app.get("/kuma/status")
        async def kuma_status():
            """STATUS_SPEC v1.0 envelope for Uptime Kuma (gateway-fronted)."""
            return JSONResponse(await self._kuma_status_payload())

        @self.app.post("/control/claim")
        async def claim(request: ClaimRequest):
            """Acquire a cooperative v1.1 claim."""
            active = self._active_claim()
            if active is not None and active["session_id"] != request.session_id:
                retry_after = max(0.0, (active["expires_at"] - self._now_utc()).total_seconds())
                raise HTTPException(
                    status_code=409,
                    detail={
                        "detail": "pypoe_web is already claimed",
                        "claimed_by": self._claimed_by(),
                        "retry_after_s": retry_after,
                    },
                    headers={"Retry-After": str(round(retry_after, 1))},
                )
            ttl_s = min(max(request.ttl_s, 5.0), 120.0)
            claim_token = active["claim_token"] if active else secrets.token_urlsafe(24)
            expires_at = self._now_utc() + timedelta(seconds=ttl_s)
            self._claim = {
                "claim_token": claim_token,
                "session_id": request.session_id,
                "owner": request.owner,
                "expires_at": expires_at,
            }
            return JSONResponse({
                "claim_token": claim_token,
                "heartbeat_interval_s": min(10.0, ttl_s / 2),
                "expires_at": expires_at.isoformat(),
            })

        @self.app.post("/control/heartbeat")
        async def heartbeat(x_claim_token: Optional[str] = Header(None, alias="X-Claim-Token")):
            """Refresh an active v1.1 claim."""
            active = self._active_claim()
            if active is None or x_claim_token != active["claim_token"]:
                raise HTTPException(status_code=401, detail="unknown or expired claim token")
            active["expires_at"] = self._now_utc() + timedelta(seconds=30.0)
            return Response(status_code=204)

        @self.app.post("/control/release")
        async def release(x_claim_token: Optional[str] = Header(None, alias="X-Claim-Token")):
            """Release an active v1.1 claim. Idempotent by spec."""
            active = self._active_claim()
            if active is not None and x_claim_token == active["claim_token"]:
                self._claim = None
            return Response(status_code=204)

        @self.app.get("/history", response_class=HTMLResponse, dependencies=dependencies)
        async def conversation_history(request: Request):
            """Conversation history browser."""
            try:
                conversations = await self.client.get_conversations()
                
                # Add message counts and last message info for each conversation
                for conv in conversations:
                    messages = await self.client.get_conversation_messages(conv['id'])
                    conv['message_count'] = len(messages)
                    conv['last_message'] = messages[-1] if messages else None
                
                return self.templates.TemplateResponse(
                    request,
                    "history.html",
                    {"conversations": conversations},
                )
            except Exception as e:
                return HTMLResponse(f"Error loading history: {str(e)}", status_code=500)
        
        @self.app.get("/conversation/{conversation_id}", response_class=HTMLResponse, dependencies=dependencies)
        async def view_conversation(request: Request, conversation_id: str):
            """View a specific conversation in detail."""
            try:
                # Get conversation details
                conversations = await self.client.get_conversations()
                conversation = next((c for c in conversations if c['id'] == conversation_id), None)
                
                if not conversation:
                    raise HTTPException(status_code=404, detail="Conversation not found")
                
                # Get messages
                messages = await self.client.get_conversation_messages(conversation_id)
                
                # Add some metadata
                conversation['message_count'] = len(messages)
                conversation['word_count'] = sum(len(msg['content'].split()) for msg in messages)
                
                return self.templates.TemplateResponse(
                    request,
                    "conversation_detail.html",
                    {"conversation": conversation, "messages": messages},
                )
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise e
                return HTMLResponse(f"Error loading conversation: {str(e)}", status_code=500)
        
        @self.app.get("/settings", response_class=HTMLResponse, dependencies=dependencies)
        async def settings(request: Request):
            """Settings and backend configuration page."""
            try:
                return self.templates.TemplateResponse(
                    request,
                    "settings.html",
                    {},
                )
            except Exception as e:
                return HTMLResponse(f"Error loading settings: {str(e)}", status_code=500)

        @self.app.get("/storage", response_class=HTMLResponse, dependencies=dependencies)
        async def storage_management(request: Request):
            """Storage monitoring and management page."""
            try:
                return self.templates.TemplateResponse(
                    request,
                    "storage.html",
                    {},
                )
            except Exception as e:
                return HTMLResponse(f"Error loading storage management: {str(e)}", status_code=500)
        
        @self.app.post("/api/conversation/new", dependencies=dependencies)
        async def create_conversation(conversation_data: ConversationCreate):
            """Create a new conversation."""
            try:
                # Generate timestamp-based title if title is empty
                from datetime import datetime
                if not conversation_data.title or conversation_data.title.strip() == "":
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    title = f"Chat {timestamp}"
                else:
                    title = conversation_data.title.strip()

                chat_mode = conversation_data.chat_mode or "chatbot"
                bot_names = conversation_data.bot_names
                bot_assignments_payload = conversation_data.bot_assignments
                debate_topic = conversation_data.debate_topic

                # Group/debate need an explicit participant list. Validate
                # the count and that every name is a known chat model so a
                # typo on the way in fails fast instead of much later when
                # the user tries to send their first message.
                if chat_mode in ("group", "debate"):
                    if not bot_names:
                        raise HTTPException(
                            status_code=400,
                            detail=f"chat_mode='{chat_mode}' requires bot_names (list of exactly 2 models).",
                        )
                    if len(bot_names) != 2:
                        raise HTTPException(
                            status_code=400,
                            detail=f"chat_mode='{chat_mode}' requires exactly 2 bot_names; got {len(bot_names)}.",
                        )
                    if len(set(bot_names)) != len(bot_names):
                        raise HTTPException(
                            status_code=400,
                            detail="bot_names must be unique.",
                        )
                    available = set(CHAT_MODELS)
                    unknown = [b for b in bot_names if b not in available]
                    if unknown:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unknown bot_names: {unknown}. Pick from CHAT_MODELS.",
                        )
                    # ``bot_name`` (singular) is still stored as the first
                    # participant; this keeps any code that reads only
                    # ``conversation.bot_name`` working in a sensible way.
                    primary_bot = bot_names[0]
                else:
                    bot_names = None
                    primary_bot = conversation_data.bot_name

                # Debate mode requires a pinned topic and a complete set
                # of role assignments. Group mode ignores both.
                bot_assignments_serialised: Optional[Dict[str, Dict[str, Any]]] = None
                if chat_mode == "debate":
                    if not (debate_topic and debate_topic.strip()):
                        raise HTTPException(
                            status_code=400,
                            detail="chat_mode='debate' requires a non-empty debate_topic.",
                        )
                    debate_topic = debate_topic.strip()
                    if not bot_assignments_payload:
                        raise HTTPException(
                            status_code=400,
                            detail="chat_mode='debate' requires bot_assignments for every participant.",
                        )
                    bot_assignments_serialised = _validate_bot_assignments(
                        bot_assignments_payload, bot_names
                    )
                else:
                    debate_topic = None

                # Go through the client wrapper so HistoryManager is lazily
                # initialized; otherwise a fresh DB has no tables yet.
                conversation_id = await self.client.create_conversation(
                    title=title,
                    bot_name=primary_bot,
                    chat_mode=chat_mode,
                    topic=None,  # Topic will be generated from first message
                    bot_names=bot_names,
                    bot_assignments=bot_assignments_serialised,
                    debate_topic=debate_topic,
                )
                return JSONResponse({"conversation_id": conversation_id})
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/conversations", dependencies=dependencies)
        async def get_conversations():
            """Get all conversations with enhanced metadata."""
            try:
                conversations = await self.client.get_conversations()
                
                # Add metadata for each conversation
                for conv in conversations:
                    messages = await self.client.get_conversation_messages(conv['id'])
                    conv['message_count'] = len(messages)
                    conv['last_message'] = messages[-1] if messages else None
                    
                    # Add locking information based on conversation state
                    user_messages = [msg for msg in messages if msg.get('role') == 'user']
                    conv['has_messages'] = len(user_messages) > 0
                    conv['bot_locked'] = len(user_messages) > 0  # Bot is locked after first user message
                    conv['chat_mode_locked'] = len(user_messages) > 0  # Chat mode is locked after first user message
                
                # Sort by last updated (most recent first). Coerce to string
                # so legacy rows with NULL ``updated_at`` don't break sorting.
                conversations.sort(
                    key=lambda x: (x.get('updated_at') or x.get('created_at') or ''),
                    reverse=True,
                )
                
                return JSONResponse(conversations)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/conversation/{conversation_id}/messages", dependencies=dependencies)
        async def get_conversation_messages(conversation_id: str):
            """Get messages for a specific conversation."""
            try:
                messages = await self.client.get_conversation_messages(conversation_id)
                return JSONResponse(messages)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.patch("/api/conversation/{conversation_id}", dependencies=dependencies)
        async def patch_conversation(conversation_id: str, payload: ConversationPatch):
            """Edit a conversation's debate topic and/or role assignments.

            Only debate-mode conversations should be touched here in v1;
            other modes simply have nothing to patch and rejecting the call
            saves a confusing no-op.
            """
            try:
                conversations = await self.client.get_conversations()
                conv = next((c for c in conversations if c['id'] == conversation_id), None)
                if not conv:
                    raise HTTPException(status_code=404, detail="Conversation not found")
                if conv.get('chat_mode') != 'debate':
                    raise HTTPException(
                        status_code=400,
                        detail="Only debate conversations can be patched.",
                    )

                new_topic: Optional[str] = None
                if payload.debate_topic is not None:
                    if not payload.debate_topic.strip():
                        raise HTTPException(
                            status_code=400,
                            detail="debate_topic must be non-empty if provided.",
                        )
                    new_topic = payload.debate_topic.strip()

                new_assignments: Optional[Dict[str, Dict[str, Any]]] = None
                if payload.bot_assignments is not None:
                    bot_names = conv.get('bot_names') or []
                    new_assignments = _validate_bot_assignments(
                        payload.bot_assignments, bot_names
                    )

                await self.client.history.update_conversation_debate_metadata(
                    conversation_id,
                    debate_topic=new_topic,
                    bot_assignments=new_assignments,
                )
                return JSONResponse({
                    "conversation_id": conversation_id,
                    "debate_topic": new_topic if new_topic is not None else conv.get('debate_topic'),
                    "bot_assignments": new_assignments if new_assignments is not None else conv.get('bot_assignments'),
                })
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.delete("/api/conversation/{conversation_id}", dependencies=dependencies)
        async def delete_conversation(conversation_id: str):
            """Delete a conversation with enhanced media cleanup tracking."""
            try:
                # Check if media tracking is available for cleanup
                media_cleanup_info = {"media_tracking": False, "media_files_deleted": 0}
                
                # Check if media tracking is available
                media_tracking_available = hasattr(self.client.history, 'get_media_stats')

                if media_tracking_available:
                    # Enhanced storage available - get media stats before deletion
                    stats_before = await self.client.history.get_media_stats()
                    media_cleanup_info["media_tracking"] = True
                    media_cleanup_info["stats_before"] = stats_before
                
                # Delete the conversation
                await self.client.delete_conversation(conversation_id)
                
                if media_cleanup_info["media_tracking"]:
                    # Get stats after deletion to calculate cleanup
                    stats_after = await self.client.history.get_media_stats()
                    media_cleanup_info["stats_after"] = stats_after
                    media_cleanup_info["media_files_deleted"] = (
                        stats_before.get('total_files', 0) - stats_after.get('total_files', 0)
                    )
                    media_cleanup_info["storage_freed_mb"] = (
                        (stats_before.get('total_size_bytes', 0) - stats_after.get('total_size_bytes', 0)) 
                        / 1024 / 1024
                    )
                
                return JSONResponse({
                    "success": True,
                    "message": "Conversation deleted successfully",
                    "media_cleanup": media_cleanup_info
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/storage/stats", dependencies=dependencies)
        async def get_storage_stats():
            """Get comprehensive storage statistics."""
            try:
                # Basic conversation stats (always available)
                conversations = await self.client.get_conversations()
                total_conversations = len(conversations)
                
                basic_stats = {
                    "total_conversations": total_conversations,
                    "database_path": str(self.config.database_path),
                    "media_tracking_available": hasattr(self.client.history, 'get_media_stats')
                }
                
                # Enhanced storage stats (if available)
                if hasattr(self.client.history, 'get_media_stats'):
                    media_stats = await self.client.history.get_media_stats()
                    
                    # Calculate database size
                    import os
                    db_size = 0
                    if os.path.exists(self.config.database_path):
                        db_size = os.path.getsize(self.config.database_path)
                    
                    # Get media directory info
                    media_dir_size = 0
                    media_dir_path = "N/A"
                    if hasattr(self.client.history, 'media_dir'):
                        media_dir_path = str(self.client.history.media_dir)
                        if os.path.exists(media_dir_path):
                            media_dir_size = sum(
                                os.path.getsize(os.path.join(dirpath, filename))
                                for dirpath, dirnames, filenames in os.walk(media_dir_path)
                                for filename in filenames
                            )
                    
                    enhanced_stats = {
                        "media_files": {
                            "total_files": media_stats.get('total_files', 0),
                            "total_size_bytes": media_stats.get('total_size_bytes', 0),
                            "total_size_mb": media_stats.get('total_size_bytes', 0) / 1024 / 1024,
                            "by_type": media_stats.get('by_type', {})
                        },
                        "storage_locations": {
                            "database": {
                                "path": str(self.config.database_path),
                                "size_bytes": db_size,
                                "size_mb": db_size / 1024 / 1024
                            },
                            "media_directory": {
                                "path": media_dir_path,
                                "size_bytes": media_dir_size,
                                "size_mb": media_dir_size / 1024 / 1024
                            }
                        },
                        "total_storage": {
                            "size_bytes": db_size + media_dir_size,
                            "size_mb": (db_size + media_dir_size) / 1024 / 1024
                        }
                    }
                    
                    return JSONResponse({**basic_stats, **enhanced_stats})
                
                return JSONResponse(basic_stats)
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/storage/cleanup", dependencies=dependencies)
        async def cleanup_orphaned_media():
            """Clean up orphaned media files."""
            try:
                if not hasattr(self.client.history, 'cleanup_orphaned_media'):
                    return JSONResponse({
                        "success": False,
                        "message": "Enhanced storage not available",
                        "files_cleaned": 0
                    })
                
                # Get stats before cleanup
                stats_before = await self.client.history.get_media_stats()
                
                # Run cleanup
                await self.client.history.cleanup_orphaned_media()
                
                # Get stats after cleanup
                stats_after = await self.client.history.get_media_stats()
                
                files_cleaned = stats_before.get('total_files', 0) - stats_after.get('total_files', 0)
                storage_freed = (stats_before.get('total_size_bytes', 0) - stats_after.get('total_size_bytes', 0)) / 1024 / 1024
                
                return JSONResponse({
                    "success": True,
                    "message": f"Cleaned up {files_cleaned} orphaned files",
                    "files_cleaned": files_cleaned,
                    "storage_freed_mb": storage_freed,
                    "stats_before": stats_before,
                    "stats_after": stats_after
                })
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/storage/conversations", dependencies=dependencies)
        async def get_conversations_with_storage_info():
            """Get conversations with enhanced storage information."""
            try:
                conversations = await self.client.get_conversations()
                
                # If media storage is available, add media info
                if hasattr(self.client.history, 'get_conversations'):
                    conversations_with_media = await self.client.history.get_conversations()
                    
                    # Create a lookup for media data
                    media_lookup = {conv['id']: conv for conv in conversations_with_media}
                    
                    # Enhance the conversation data
                    for conv in conversations:
                        enhanced_data = media_lookup.get(conv['id'], {})
                        conv.update({
                            'media_count': enhanced_data.get('media_count', 0),
                            'has_media': enhanced_data.get('has_media', False),
                            'message_count': enhanced_data.get('message_count', 0)
                        })
                
                return JSONResponse(conversations)
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/health")
        async def health_check():
            """Health check endpoint for React frontend."""
            try:
                # Check if client is working
                await self.client.get_available_bots()
                return JSONResponse({"status": "healthy", "version": "2.0.0"})
            except Exception as e:
                return JSONResponse({"status": "unhealthy", "error": str(e)}, status_code=503)

        @self.app.post("/api/conversation/{conversation_id}/send", dependencies=dependencies)
        async def send_message(conversation_id: str, message_data: MessageSend):
            """Send a message to a conversation (non-streaming)."""
            try:
                # Get the conversation to determine the bot
                conversations = await self.client.get_conversations()
                conversation = next((c for c in conversations if c['id'] == conversation_id), None)
                
                if not conversation:
                    raise HTTPException(status_code=404, detail="Conversation not found")
                
                # Get existing messages to check if conversation has started
                existing_messages = await self.client.get_conversation_messages(conversation_id)
                conversation_bot = conversation.get('bot_name') or DEFAULT_CHAT_MODEL
                conversation_chat_mode = conversation.get('chat_mode', 'chatbot')
                
                # Group/debate conversations cannot use the non-streaming
                # /send fallback; they require the WebSocket fan-out path.
                if conversation_chat_mode in ('group', 'debate'):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Conversations with chat_mode='{conversation_chat_mode}' "
                               f"must use the WebSocket endpoint /ws/chat/{{id}}.",
                    )

                # Validation for conversations with existing messages
                if existing_messages:
                    user_messages = [msg for msg in existing_messages if msg.get('role') == 'user']

                    # Bot locking only applies to single-bot chatbot mode.
                    if (
                        conversation_chat_mode == 'chatbot'
                        and user_messages
                        and message_data.bot_name
                        and message_data.bot_name != conversation_bot
                    ):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cannot change bot mid-conversation. This conversation is locked to {conversation_bot}. "
                                   f"Current conversation has {len(user_messages)} user messages."
                        )

                    # Chat mode locking: prevent changing chat mode mid-conversation
                    if user_messages and message_data.chat_mode and message_data.chat_mode != conversation_chat_mode:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cannot change chat mode mid-conversation. This conversation is locked to {conversation_chat_mode} mode. "
                                   f"Current conversation has {len(user_messages)} user messages."
                        )

                    bot_name = conversation_bot
                else:
                    # New conversation - allow bot and chat mode selection
                    bot_name = message_data.bot_name or conversation_bot
                
                # Collect the full response
                full_response = ""
                async for partial_response in self.client.send_message(
                    message=message_data.message,
                    bot_name=bot_name,
                    conversation_id=conversation_id,
                    save_history=True
                ):
                    full_response += partial_response
                
                return JSONResponse({
                    "message": full_response,
                    "role": "assistant",
                    "bot_name": bot_name,
                    "conversation_id": conversation_id
                })
            except HTTPException:
                # Validation rejections already carry the right status; don't
                # paint over them with a generic 500.
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/bots", dependencies=dependencies)
        async def get_available_bots(conversation_id: str = None):
            """Get list of available bots with locking information for a specific conversation."""
            try:
                bots = await self.client.get_available_bots()
                
                # If conversation_id is provided, add locking information
                if conversation_id:
                    conversations = await self.client.get_conversations()
                    conversation = next((c for c in conversations if c['id'] == conversation_id), None)
                    
                    if conversation:
                        messages = await self.client.get_conversation_messages(conversation_id)
                        user_messages = [msg for msg in messages if msg.get('role') == 'user']
                        has_user_messages = len(user_messages) > 0
                        
                        conversation_bot = conversation.get('bot_name') or DEFAULT_CHAT_MODEL
                        conversation_chat_mode = conversation.get('chat_mode', 'chatbot')
                        
                        # Add locking metadata for the frontend
                        locking_info = {
                            "conversation_locked": has_user_messages,
                            "locked_bot": conversation_bot if has_user_messages else None,
                            "locked_chat_mode": conversation_chat_mode if has_user_messages else None,
                            "available_chat_modes": ["chatbot", "group", "debate"]
                        }
                        
                        return JSONResponse({
                            "bots": bots,
                            "providers": self._bot_providers(bots),
                            "locking": locking_info
                        })

                # Default response without locking information
                return JSONResponse({
                    "bots": bots,
                    "providers": self._bot_providers(bots),
                    "locking": {
                        "conversation_locked": False,
                        "locked_bot": None,
                        "locked_chat_mode": None,
                        "available_chat_modes": ["chatbot", "group", "debate"]
                    }
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/conversations/search", dependencies=dependencies)
        async def search_conversations(
            q: str = "", 
            bot: str = "", 
            chat_mode: str = "",
            has_messages: bool = None,
            limit: int = 50,
            sort_by: str = "updated_at",  # updated_at, created_at, message_count, title
            sort_order: str = "desc"      # asc, desc
        ):
            """Advanced search and filtering for conversations."""
            try:
                conversations = await self.client.get_conversations()
                
                # Add metadata first (we'll need this for filtering and sorting)
                for conv in conversations:
                    messages = await self.client.get_conversation_messages(conv['id'])
                    conv['message_count'] = len(messages)
                    conv['last_message'] = messages[-1] if messages else None
                    
                    # Add locking information
                    user_messages = [msg for msg in messages if msg.get('role') == 'user']
                    conv['has_messages'] = len(user_messages) > 0
                    conv['bot_locked'] = len(user_messages) > 0
                    conv['chat_mode_locked'] = len(user_messages) > 0
                    
                    # Add search-friendly content for full-text search
                    conv['searchable_content'] = ' '.join([
                        conv.get('title', ''),
                        ' '.join([msg.get('content', '') for msg in messages])
                    ]).lower()
                
                # Apply filters
                filtered_conversations = []
                
                for conv in conversations:
                    # Filter by bot
                    if bot and conv.get('bot_name', '').lower() != bot.lower():
                        continue
                    
                    # Filter by chat mode
                    if chat_mode and conv.get('chat_mode', '').lower() != chat_mode.lower():
                        continue
                    
                    # Filter by message presence
                    if has_messages is not None:
                        if has_messages and not conv['has_messages']:
                            continue
                        if not has_messages and conv['has_messages']:
                            continue
                    
                    # Search by query (title and content)
                    if q and q.lower() not in conv['searchable_content']:
                        continue
                    
                    filtered_conversations.append(conv)
                
                # Sort conversations
                reverse_order = sort_order.lower() == "desc"
                
                if sort_by == "message_count":
                    filtered_conversations.sort(key=lambda x: x.get('message_count') or 0, reverse=reverse_order)
                elif sort_by == "title":
                    filtered_conversations.sort(key=lambda x: (x.get('title') or '').lower(), reverse=reverse_order)
                elif sort_by == "created_at":
                    filtered_conversations.sort(key=lambda x: x.get('created_at') or '', reverse=reverse_order)
                else:  # default to updated_at
                    filtered_conversations.sort(
                        key=lambda x: (x.get('updated_at') or x.get('created_at') or ''),
                        reverse=reverse_order,
                    )
                
                # Limit results
                filtered_conversations = filtered_conversations[:limit]
                
                # Clean up search field before returning
                for conv in filtered_conversations:
                    del conv['searchable_content']
                
                return JSONResponse({
                    "conversations": filtered_conversations,
                    "total_found": len(filtered_conversations),
                    "filters_applied": {
                        "query": q if q else None,
                        "bot": bot if bot else None,
                        "chat_mode": chat_mode if chat_mode else None,
                        "has_messages": has_messages,
                        "sort_by": sort_by,
                        "sort_order": sort_order,
                        "limit": limit
                    }
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/stats", dependencies=dependencies)
        async def get_stats():
            """Get comprehensive conversation statistics."""
            try:
                conversations = await self.client.get_conversations()
                
                total_conversations = len(conversations)
                total_messages = 0
                total_user_messages = 0
                total_assistant_messages = 0
                total_words = 0
                total_user_words = 0
                total_assistant_words = 0
                bot_usage = {}
                chat_mode_usage = {}
                active_conversations = 0  # Conversations with messages
                
                for conv in conversations:
                    messages = await self.client.get_conversation_messages(conv['id'])
                    conversation_message_count = len(messages)
                    total_messages += conversation_message_count
                    
                    if conversation_message_count > 0:
                        active_conversations += 1
                    
                    user_messages_count = 0
                    assistant_messages_count = 0
                    
                    for msg in messages:
                        content = msg.get('content', '')
                        words = len(content.split())
                        total_words += words
                        
                        if msg.get('role') == 'user':
                            total_user_messages += 1
                            total_user_words += words
                            user_messages_count += 1
                        elif msg.get('role') == 'assistant':
                            total_assistant_messages += 1
                            total_assistant_words += words
                            assistant_messages_count += 1
                    
                    # Count bot usage
                    bot_name = conv.get('bot_name', 'Unknown')
                    bot_usage[bot_name] = bot_usage.get(bot_name, 0) + 1
                    
                    # Count chat mode usage
                    chat_mode = conv.get('chat_mode', 'chatbot')
                    chat_mode_usage[chat_mode] = chat_mode_usage.get(chat_mode, 0) + 1
                
                return JSONResponse({
                    "total_conversations": total_conversations,
                    "active_conversations": active_conversations,
                    "total_messages": total_messages,
                    "total_user_messages": total_user_messages,
                    "total_assistant_messages": total_assistant_messages,
                    "total_words": total_words,
                    "total_user_words": total_user_words,
                    "total_assistant_words": total_assistant_words,
                    "bot_usage": bot_usage,
                    "chat_mode_usage": chat_mode_usage,
                    "avg_messages_per_conversation": total_messages / total_conversations if total_conversations > 0 else 0,
                    "avg_messages_per_active_conversation": total_messages / active_conversations if active_conversations > 0 else 0,
                    "avg_words_per_message": total_words / total_messages if total_messages > 0 else 0,
                    "avg_user_words_per_message": total_user_words / total_user_messages if total_user_messages > 0 else 0,
                    "avg_assistant_words_per_message": total_assistant_words / total_assistant_messages if total_assistant_messages > 0 else 0
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/network-status", dependencies=dependencies)
        async def get_network_status():
            """Get current network interface status (dynamic detection)."""
            try:
                import subprocess
                import platform
                from datetime import datetime
                
                network_interfaces = {}
                detected_ips = set()
                
                # Use the same comprehensive detection logic
                system = platform.system().lower()
                
                if system == "darwin":  # macOS
                    try:
                        result = subprocess.run(['ifconfig'], capture_output=True, text=True, timeout=5)
                        if result.returncode == 0:
                            lines = result.stdout.split('\n')
                            for line in lines:
                                if 'inet ' in line and 'inet 127.' not in line and 'inet 169.254.' not in line:
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        ip = parts[1]
                                        if '.' in ip and not ip.startswith('127.') and not ip.startswith('169.254.'):
                                            detected_ips.add(ip)
                    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                        pass
                
                elif system == "linux":
                    try:
                        result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True, timeout=5)
                        if result.returncode == 0:
                            lines = result.stdout.split('\n')
                            for line in lines:
                                if 'inet ' in line and '/127.' not in line and '/169.254.' not in line:
                                    parts = line.strip().split()
                                    for part in parts:
                                        if '.' in part and '/' in part:
                                            ip = part.split('/')[0]
                                            if not ip.startswith('127.') and not ip.startswith('169.254.'):
                                                detected_ips.add(ip)
                    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                        pass
                
                # Fallback detection methods
                test_connections = [('8.8.8.8', 80), ('1.1.1.1', 80)]
                for host, port in test_connections:
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                            s.connect((host, port))
                            local_ip = s.getsockname()[0]
                            if not local_ip.startswith('127.') and not local_ip.startswith('169.254.'):
                                detected_ips.add(local_ip)
                    except:
                        continue
                
                print(f"[Network Status] Found IPs: {sorted(detected_ips)}")
                
                # Categorize and test detected IPs
                for ip in detected_ips:
                    category = None
                    if ip.startswith('100.64.'):
                        category = 'tailscale'
                    elif ip.startswith('172.29.'):
                        category = 'compsci_vpn'
                    elif ip.startswith('172.31.'):
                        category = 'compsci_wifi'
                    elif ip.startswith('192.168.') or ip.startswith('10.'):
                        category = 'local'
                    
                    if category:
                        # Test connectivity instead of binding (more reliable)
                        is_reachable = False
                        try:
                            # Try to connect to ourselves on this interface (if backend is running)
                            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
                                test_sock.settimeout(1)  # Quick timeout
                                result = test_sock.connect_ex((ip, 8000))
                                is_reachable = (result == 0)  # 0 means connection successful
                        except:
                            # If connection test fails, assume interface is reachable
                            # (backend might not be bound to this interface yet)
                            is_reachable = True
                        
                        # Always add detected interfaces (if we can detect them, they're likely usable)
                        status = 'active' if is_reachable else 'detected'
                        network_interfaces[category] = {
                            'ip': ip,
                            'frontend_url': f'http://{ip}:5173',
                            'backend_url': f'http://{ip}:8000',
                            'status': status,
                            'last_checked': str(datetime.now())
                        }
                        print(f"[Network Status] {category} network detected: {ip} (status: {status})")
                        
                        # Log network detection event
                        logger.log_network_event(
                            event_type="detection",
                            network_type=category,
                            ip_address=ip,
                            status=status,
                            frontend_url=f'http://{ip}:5173',
                            backend_url=f'http://{ip}:8000',
                            metadata={
                                "detection_method": "network-status-endpoint",
                                "is_reachable": is_reachable,
                                "detected_ips_count": len(detected_ips)
                            }
                        )
                
                return JSONResponse({
                    "network_interfaces": network_interfaces,
                    "total_interfaces": len(network_interfaces),
                    "timestamp": str(datetime.now())
                })
            except Exception as e:
                print(f"[Network Status] Error: {str(e)}")
                return JSONResponse({
                    "network_interfaces": {"error": f"Failed to detect interfaces: {str(e)}"},
                    "total_interfaces": 0,
                    "timestamp": str(datetime.now())
                })

        @self.app.get("/api/config", dependencies=dependencies)
        async def get_config_info():
            """Get backend configuration information."""
            try:
                import socket
                from datetime import datetime
                
                available_bots = await self.client.get_available_bots()
                
                # Get network interfaces using comprehensive detection
                network_interfaces = {}
                try:
                    import subprocess
                    import platform
                    
                    detected_ips = set()
                    
                    # Method 1: Use platform-specific commands for comprehensive interface detection
                    system = platform.system().lower()
                    
                    if system == "darwin":  # macOS
                        try:
                            # Get all interface IPs using ifconfig
                            result = subprocess.run(['ifconfig'], capture_output=True, text=True, timeout=5)
                            if result.returncode == 0:
                                lines = result.stdout.split('\n')
                                for line in lines:
                                    if 'inet ' in line and 'inet 127.' not in line and 'inet 169.254.' not in line:
                                        # Extract IP using split
                                        parts = line.split()
                                        if len(parts) >= 2:
                                            ip = parts[1]
                                            # Validate it's a proper IP
                                            if '.' in ip and not ip.startswith('127.') and not ip.startswith('169.254.'):
                                                detected_ips.add(ip)
                        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                            pass
                    
                    elif system == "linux":
                        try:
                            # Try ip command first
                            result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True, timeout=5)
                            if result.returncode == 0:
                                lines = result.stdout.split('\n')
                                for line in lines:
                                    if 'inet ' in line and '/127.' not in line and '/169.254.' not in line:
                                        # Extract IP using split
                                        parts = line.strip().split()
                                        for part in parts:
                                            if '.' in part and '/' in part:
                                                ip = part.split('/')[0]
                                                if not ip.startswith('127.') and not ip.startswith('169.254.'):
                                                    detected_ips.add(ip)
                        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                            # Fallback to ifconfig on Linux
                            try:
                                result = subprocess.run(['ifconfig'], capture_output=True, text=True, timeout=5)
                                if result.returncode == 0:
                                    lines = result.stdout.split('\n')
                                    for line in lines:
                                        if 'inet ' in line and 'inet 127.' not in line:
                                            parts = line.split()
                                            if len(parts) >= 2:
                                                ip = parts[1]
                                                if '.' in ip and not ip.startswith('127.') and not ip.startswith('169.254.'):
                                                    detected_ips.add(ip)
                            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                                pass
                    
                    # Method 2: Fallback to socket-based detection for any missed interfaces
                    test_connections = [
                        ('8.8.8.8', 80),  # Google DNS
                        ('1.1.1.1', 80),  # Cloudflare DNS
                    ]
                    
                    for host, port in test_connections:
                        try:
                            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                                s.connect((host, port))
                                local_ip = s.getsockname()[0]
                                if not local_ip.startswith('127.') and not local_ip.startswith('169.254.'):
                                    detected_ips.add(local_ip)
                        except:
                            continue
                    
                    # Method 3: Also try connecting to common local network gateways
                    local_gateways = ['192.168.1.1', '192.168.0.1', '10.0.0.1', '172.16.0.1']
                    for gateway in local_gateways:
                        try:
                            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                                s.settimeout(1)
                                s.connect((gateway, 53))  # DNS port
                                local_ip = s.getsockname()[0]
                                if not local_ip.startswith('127.') and not local_ip.startswith('169.254.'):
                                    detected_ips.add(local_ip)
                        except:
                            continue
                    
                    print(f"[Network Detection] Found IPs: {sorted(detected_ips)}")
                    
                    # Categorize and test connectivity of detected IPs
                    for ip in detected_ips:
                        category = None
                        if ip.startswith('100.64.'):
                            category = 'tailscale'
                        elif ip.startswith('172.29.'):
                            category = 'compsci_vpn'
                        elif ip.startswith('172.31.'):
                            category = 'compsci_wifi'
                        elif ip.startswith('192.168.') or ip.startswith('10.'):
                            category = 'local'
                        
                        if category:
                            # Always add detected interfaces (if we can detect them, they're likely usable)
                            network_interfaces[category] = {
                                'ip': ip,
                                'frontend_url': f'http://{ip}:5173',
                                'backend_url': f'http://{ip}:8000',
                                'status': 'detected'
                            }
                            print(f"[Network Detection] {category} network detected: {ip}")
                            
                            # Log network detection event
                            logger.log_network_event(
                                event_type="detection",
                                network_type=category,
                                ip_address=ip,
                                status='detected',
                                frontend_url=f'http://{ip}:5173',
                                backend_url=f'http://{ip}:8000',
                                metadata={
                                    "detection_method": "config-endpoint",
                                    "detected_ips_count": len(detected_ips)
                                }
                            )
                    
                except Exception as e:
                    print(f"[Network Detection] Error: {str(e)}")
                    network_interfaces = {"error": f"Failed to detect interfaces: {str(e)}"}
                
                config_info = {
                    "backend_version": "2.0.0",
                    "database_path": str(self.config.database_path),
                    "authentication_enabled": self.config.web_trust_forward_auth,
                    "auth_mode": "ac_auth_edge" if self.config.web_trust_forward_auth else "open",
                    "available_bots": available_bots,
                    "total_bots": len(available_bots),
                    "network_interfaces": network_interfaces,
                    "api_endpoints": [
                        "/api/health",
                        "/api/conversations",  # Enhanced with metadata and locking info
                        "/api/conversations/search",  # Advanced search with filtering/sorting
                        "/api/bots",  # Enhanced with conversation-specific locking
                        "/api/stats",  # Comprehensive statistics
                        "/api/storage/stats",  # Storage monitoring and analytics
                        "/api/storage/cleanup",  # Media cleanup operations
                        "/api/storage/conversations",  # Conversations with storage info
                        "/api/account/status",  # Account status and usage monitoring
                        "/api/network-status",  # Dynamic network interface detection
                        "/api/logs/network",  # Network activity logs
                        "/api/logs/system",  # System activity logs
                        "/api/config",
                        "/api/conversation/new",
                        "/api/conversation/{id}/messages",
                        "/api/conversation/{id}/send",
                        "/ws/chat/{id}"
                    ],
                    "cors_enabled": True,
                    "websocket_enabled": True,
                    "features": {
                        "real_time_streaming": True,
                        "conversation_history": True,
                        "multi_bot_support": True,
                        "advanced_search": True,  # Enhanced search with filtering/sorting
                        "conversation_metadata": True,  # Message counts, locking info, etc.
                        "comprehensive_stats": True,  # Detailed statistics including word counts
                        "dynamic_locking": True,  # Context-aware bot/mode locking
                        "account_monitoring": True,  # API key status and usage tracking
                        "authentication": self.config.web_trust_forward_auth,
                        "websocket_chat": True,
                        "api_only_mode": False,
                        "bot_locking": True,
                        "chat_mode_locking": True,
                        "database_consistency": True,
                        "backend_business_logic": True  # All logic handled in backend
                    }
                }
                
                return JSONResponse(config_info)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/logs/network", dependencies=dependencies)
        async def get_network_logs(
            limit: int = 100,
            network_type: str = None,
            since: str = None
        ):
            """Get network activity logs."""
            try:
                logs = logger.get_network_logs(
                    limit=limit,
                    network_type=network_type,
                    since=since
                )
                summary = logger.get_network_summary()
                
                return JSONResponse({
                    "logs": logs,
                    "summary": summary,
                    "total_logs": len(logs),
                    "filters": {
                        "limit": limit,
                        "network_type": network_type,
                        "since": since
                    }
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/logs/system", dependencies=dependencies)
        async def get_system_logs(
            limit: int = 100,
            component: str = None,
            since: str = None
        ):
            """Get system activity logs."""
            try:
                logs = logger.get_system_logs(
                    limit=limit,
                    component=component,
                    since=since
                )
                
                return JSONResponse({
                    "logs": logs,
                    "total_logs": len(logs),
                    "filters": {
                        "limit": limit,
                        "component": component,
                        "since": since
                    }
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/account/status", dependencies=dependencies)
        async def get_account_status():
            """Get comprehensive account status information."""
            try:
                import time
                from datetime import datetime, timedelta
                
                status_data = {
                    "timestamp": datetime.now().isoformat(),
                    "api_key_configured": bool(self.config.poe_api_key),
                    "api_key_status": "unknown",
                    "connectivity": {
                        "status": "unknown",
                        "response_time_ms": None,
                        "last_checked": None
                    },
                    "storage_usage": {
                        "database_size_mb": 0,
                        "total_conversations": 0
                    }
                }
                
                # Test API key and connectivity
                if self.config.poe_api_key:
                    try:
                        start_time = time.time()
                        
                        # Quick connectivity test - try to get available bots
                        await self.client.get_available_bots()
                        
                        end_time = time.time()
                        response_time = (end_time - start_time) * 1000  # Convert to milliseconds
                        
                        status_data["api_key_status"] = "valid"
                        status_data["connectivity"]["status"] = "connected"
                        status_data["connectivity"]["response_time_ms"] = round(response_time, 2)
                        status_data["connectivity"]["last_checked"] = datetime.now().isoformat()
                        
                    except Exception as api_error:
                        error_msg = str(api_error).lower()
                        if "invalid" in error_msg or "unauthorized" in error_msg:
                            status_data["api_key_status"] = "invalid"
                        elif "insufficient" in error_msg or "quota" in error_msg:
                            status_data["api_key_status"] = "quota_exceeded"
                        else:
                            status_data["api_key_status"] = "error"
                        
                        status_data["connectivity"]["status"] = "error"
                        status_data["connectivity"]["error"] = str(api_error)
                else:
                    status_data["api_key_status"] = "not_configured"
                
                # Get storage information
                try:
                    import os
                    if os.path.exists(self.config.database_path):
                        db_size = os.path.getsize(self.config.database_path)
                        status_data["storage_usage"]["database_size_mb"] = round(db_size / 1024 / 1024, 2)
                    
                    conversations = await self.client.get_conversations()
                    status_data["storage_usage"]["total_conversations"] = len(conversations)
                    
                except Exception as storage_error:
                    status_data["storage_usage"]["error"] = str(storage_error)
                
                return JSONResponse(status_data)
                
            except Exception as e:
                return JSONResponse({
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                    "api_key_configured": bool(self.config.poe_api_key),
                    "api_key_status": "error"
                }, status_code=500)

        @self.app.websocket("/ws/chat/{conversation_id}")
        async def websocket_chat(websocket: WebSocket, conversation_id: str):
            """WebSocket endpoint for real-time chat."""
            
            # Handle authentication for WebSocket if enabled
            if self.security:
                auth_valid = False
                
                # Method 1: Try authorization header (if browser supports it)
                try:
                    auth_header = websocket.headers.get("authorization", "")
                    if auth_header.startswith("Basic "):
                        import base64
                        import secrets
                        encoded_credentials = auth_header.split(" ", 1)[1]
                        decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
                        username, password = decoded_credentials.split(":", 1)
                        correct_username = secrets.compare_digest(username, self.config.web_username)
                        correct_password = secrets.compare_digest(password, self.config.web_password)
                        auth_valid = correct_username and correct_password
                except Exception:
                    pass
                
                # Method 2: Try query parameters (WebSocket fallback)
                if not auth_valid:
                    query_params = dict(websocket.query_params)
                    if "username" in query_params and "password" in query_params:
                        import secrets
                        username = query_params["username"]
                        password = query_params["password"]
                        correct_username = secrets.compare_digest(username, self.config.web_username)
                        correct_password = secrets.compare_digest(password, self.config.web_password)
                        auth_valid = correct_username and correct_password
                
                # Method 3: Check if connection is from same origin (localhost exception)
                if not auth_valid:
                    origin = websocket.headers.get("origin", "")
                    host = websocket.headers.get("host", "")
                    # Allow localhost connections if they're from the same host
                    if origin and host:
                        import urllib.parse
                        try:
                            parsed_origin = urllib.parse.urlparse(origin)
                            if (parsed_origin.hostname in ["localhost", "127.0.0.1"] and 
                                host.startswith(("localhost:", "127.0.0.1:"))):
                                auth_valid = True
                        except Exception:
                            pass
                
                # Method 4: If no security is configured, allow all connections
                if not auth_valid and not self.config.web_username:
                    auth_valid = True
                
                if not auth_valid:
                    await websocket.close(code=1008, reason="Authentication required")
                    return
            
            await websocket.accept()
            self.active_connections.append(websocket)
            
            try:
                while True:
                    # Receive message from client
                    data = await websocket.receive_text()
                    message_data = json.loads(data)
                    
                    user_message = message_data.get("message", "")
                    requested_bot = message_data.get("bot_name") or DEFAULT_CHAT_MODEL
                    # ``None`` (not provided) means "keep the conversation's
                    # mode". Defaulting to "chatbot" here would fire a spurious
                    # mode-lock error every time a group/debate frontend (which
                    # doesn't set this field) sends a follow-up.
                    requested_chat_mode = message_data.get("chat_mode")
                    
                    if not user_message:
                        continue
                    
                    # Get conversation info and validate bot/chat mode selection
                    try:
                        conversations = await self.client.get_conversations()
                        conversation = next((c for c in conversations if c['id'] == conversation_id), None)
                        
                        if not conversation:
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "content": "Conversation not found"
                            }))
                            continue
                        
                        # Get existing messages to check if conversation has started
                        existing_messages = await self.client.get_conversation_messages(conversation_id)
                        conversation_bot = conversation.get('bot_name') or DEFAULT_CHAT_MODEL
                        conversation_chat_mode = conversation.get('chat_mode', 'chatbot')
                        conversation_bot_names = conversation.get('bot_names') or []
                        is_multi_mode = (
                            conversation_chat_mode in ('group', 'debate')
                            and conversation_bot_names
                        )

                        # Validation for conversations with existing messages
                        if existing_messages:
                            user_messages = [msg for msg in existing_messages if msg.get('role') == 'user']

                            # Bot locking only applies to single-bot chatbot mode.
                            # Group/debate freeze ``bot_names`` at creation; the
                            # requested ``bot_name`` in WS frames is ignored.
                            if (
                                conversation_chat_mode == 'chatbot'
                                and user_messages
                                and requested_bot != conversation_bot
                            ):
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "content": f"Cannot change bot mid-conversation. This conversation is locked to {conversation_bot}. "
                                              f"Current conversation has {len(user_messages)} user messages."
                                }))
                                continue

                            # Chat mode locking: only enforce when the client
                            # actively asks for a different mode. Missing field
                            # = "use whatever the conversation already is".
                            if (
                                user_messages
                                and requested_chat_mode
                                and requested_chat_mode != conversation_chat_mode
                            ):
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "content": f"Cannot change chat mode mid-conversation. This conversation is locked to {conversation_chat_mode} mode. "
                                              f"Current conversation has {len(user_messages)} user messages."
                                }))
                                continue

                            bot_name = conversation_bot
                        else:
                            # New conversation - allow bot and chat mode selection
                            bot_name = requested_bot

                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "content": f"Error validating conversation: {str(e)}"
                        }))
                        continue

                    if is_multi_mode:
                        # Fan out to all participants concurrently. The helper
                        # owns echoing the user message, saving history, and
                        # streaming per-model frames tagged with ``model_name``.
                        await self._fan_out_to_models(
                            websocket=websocket,
                            conversation=conversation,
                            user_message=user_message,
                        )
                    else:
                        # Single-bot path (existing behaviour, unchanged shape).

                        # Send user message back to confirm receipt
                        await websocket.send_text(json.dumps({
                            "type": "user_message",
                            "content": user_message,
                            "role": "user"
                        }))

                        # Send bot response start indicator
                        await websocket.send_text(json.dumps({
                            "type": "bot_response_start",
                            "role": "assistant"
                        }))

                        # Stream bot response (filtering already handled in client.py)
                        full_response = ""

                        async for partial_response in self.client.send_message(
                            message=user_message,
                            bot_name=bot_name,
                            conversation_id=conversation_id,
                            save_history=True
                        ):
                            # Only send non-empty chunks (client.py already filters generating messages)
                            if partial_response:
                                full_response += partial_response
                                await websocket.send_text(json.dumps({
                                    "type": "bot_response_chunk",
                                    "content": partial_response,
                                    "role": "assistant"
                                }))

                        # Send bot response end indicator
                        await websocket.send_text(json.dumps({
                            "type": "bot_response_end",
                            "role": "assistant"
                        }))
                    
                    # Generate topic if this was the first user message and no topic exists yet
                    try:
                        conversation = next((c for c in conversations if c['id'] == conversation_id), None)
                        if conversation:
                            # Check if conversation has no topic yet
                            if not conversation.get('topic'):
                                # Get all messages to check if this was the first user message
                                all_messages = await self.client.get_conversation_messages(conversation_id)
                                user_messages = [msg for msg in all_messages if msg.get('role') == 'user']
                                
                                # If this was the first user message, generate a topic in background
                                if len(user_messages) == 1:
                                    # Use asyncio.create_task to run topic generation in background
                                    import asyncio
                                    asyncio.create_task(self._generate_and_save_topic(conversation_id, user_message))
                    except Exception as e:
                        print(f"Failed to start topic generation: {e}")
                    
            except WebSocketDisconnect:
                self.active_connections.remove(websocket)
            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Error: {str(e)}"
                }))
                self.active_connections.remove(websocket)
    
    async def close(self):
        """Clean up resources."""
        # Log system shutdown
        logger.log_system_event(
            event_type="shutdown",
            component="backend",
            action="stop",
            metadata={
                "active_connections": len(self.active_connections),
                "graceful_shutdown": True
            }
        )
        await self.client.close()

def create_app(config: Config = None) -> FastAPI:
    """Factory function to create the FastAPI app."""
    if not WEB_AVAILABLE:
        raise RuntimeError("Web UI dependencies not installed.")
    
    web_app = WebApp(config)
    return web_app.app

def run_server(host: str = "localhost", port: int = 8000, config: Config = None):
    """Run the web server."""
    if not WEB_AVAILABLE:
        print("Web UI dependencies not installed. Please install with: pip install -e '.[web-ui]'")
        return
    
    app = create_app(config)
    
    # Enhanced uvicorn configuration for production
    uvicorn_config = {
        "app": app,
        "host": host,
        "port": port,
        "log_level": "info",
        "access_log": True,
        "server_header": False,  # Hide server header for security
        "date_header": False,    # Hide date header for security
    }
    
    # Add graceful shutdown handling
    import signal
    import asyncio
    
    def signal_handler(sig, frame):
        print(f"\nReceived signal {sig}, shutting down gracefully...")
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        print("\nServer shutdown complete")
    except Exception as e:
        print(f"Server error: {e}")
        raise 