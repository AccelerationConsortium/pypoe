"""SPA-serving wrapper for the PyPoe React UI (parallel-deploy migration).

Wraps the normal :func:`create_app` FastAPI instance — all of ``/api/*``,
``/ws/*``, ``/status``, ``/health``, ``/auth/*``, ``/control/*`` are unchanged —
and serves the built React app (``frontend/dist``) for page navigations. This
runs as a *second* service (``pypoe-web-next``) on its own port, so the new UI
can be previewed behind the edge at ``/pypoe-next/`` without touching the live
Jinja UI on :8006. See ``docs/REACT_UI_MIGRATION.md``.

Run it (reads ``PYPOE_SPA_DIST`` for the built dist):

    PYPOE_SPA_DIST=/path/to/frontend/dist \\
      uvicorn pypoe.interfaces.web.spa_app:get_app --factory --host 127.0.0.1 --port 8007
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ...core.config import Config
from .app import create_app

# Path prefixes that must reach the real backend routes, never the SPA shell.
# Everything else, for an HTML GET, is a client-side route -> serve index.html.
_RESERVED_PREFIXES = (
    "/api",
    "/ws",
    "/control",
    "/assets",   # hashed build assets (mounted below)
    "/static",   # legacy Jinja static (harmless to keep reserved)
    "/auth",     # the edge serves /auth; reserved just in case
    "/health",
    "/status",
)


def _resolve_dist(dist_dir: str | None) -> Path:
    raw = dist_dir or os.environ.get("PYPOE_SPA_DIST") or ""
    if not raw:
        raise RuntimeError(
            "PYPOE_SPA_DIST is not set — point it at the built React app "
            "(frontend/dist). Build it first: `cd frontend && VITE_BASE=/pypoe-next/ npm run build`."
        )
    dist = Path(raw).expanduser().resolve()
    if not (dist / "index.html").is_file():
        raise RuntimeError(f"No index.html under PYPOE_SPA_DIST={dist} — build the frontend first.")
    return dist


def create_spa_app(config: Config = None, dist_dir: str | None = None):
    """Build the full PyPoe app, then layer React SPA serving on top."""
    dist = _resolve_dist(dist_dir)
    index_html = dist / "index.html"

    app = create_app(config)

    # Serve the content-hashed build assets. Vite emits them under /assets and
    # references them as <base>/assets/... ; the edge strips the <base> prefix,
    # so the backend sees /assets/... here.
    app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="spa-assets")

    @app.middleware("http")
    async def _spa_fallback(request, call_next):
        # Serve the SPA shell for browser page navigations (HTML GETs) to any
        # non-backend path. Runs before routing, so it takes precedence over the
        # legacy Jinja page routes without removing them. API/JSON/asset/status
        # requests fall through to the real handlers.
        if request.method in ("GET", "HEAD"):
            path = request.url.path
            accept = request.headers.get("accept", "")
            if "text/html" in accept and not path.startswith(_RESERVED_PREFIXES):
                return FileResponse(index_html)
        return await call_next(request)

    return app


def get_app():
    """Uvicorn factory entrypoint (`--factory`); reads PYPOE_SPA_DIST from env."""
    return create_spa_app()
