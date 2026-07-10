# PyPoe Web UI — React migration note

**Status:** planning note (not started). Captures how to redesign the PyPoe web
UI in React so it drops cleanly behind the SDL2 single-edge setup, and what
current hand-rolled plumbing it replaces.

## Goal & scope

Replace the **frontend only** — the Jinja templates + hand-written
`static/app.js` / `static/style.css` / `static/status-bar.js` — with a React
app (Vite recommended). The **FastAPI backend stays as-is**: `/api/*`, the chat
WebSocket `/ws/chat/*`, `/status`, `/health`, and `/auth/*` behaviour are
unchanged. This is a UI rewrite, not a backend rewrite.

## Why do this

The current UI is served by FastAPI `StaticFiles` with no content-hashing and
no `Cache-Control`, which is why stale-asset bugs kept appearing (a deploy
would ship new JS but browsers served the old cached copy). React/Vite
**content-hashes every asset at build time** and the framework handles cache
invalidation automatically — so the whole class of "hard-refresh or it's
broken" goes away, and several pieces of interim plumbing (below) can be
deleted.

## Copy the working example: LaAgenteAnalitica

`LaAgenteAnalitica` (the agent chat) is already a Vite/React app served behind
the same edge at `/agente/`, with the shared sign-in banner on top. **PyPoe in
React is the same pattern at `/pypoe/`.** Use it as the reference for the Vite
base config, the edge route, and the banner, instead of re-deriving any of it.

## The four things to get right (edge integration)

1. **Build for the base path `/pypoe/`.** With Vite, set `base: '/pypoe/'` (the
   equivalent of agente's `VITE_BASE=/agente/`). This bakes the prefix into the
   built asset URLs, so the runtime `X-Forwarded-Prefix` / `base_path()` trick
   the current server-rendered UI uses is **no longer needed** — the base is a
   build-time constant. Point the app's API/WS base at the same prefix
   (`/pypoe/api`, `ws(s)://<host>/pypoe/ws/...`), matching how agente sets
   `VITE_API_URL` / `VITE_WS_URL`.

2. **Keep the shared auth banner.** The built `index.html` must still include
   `<script src="/auth/banner.js" defer></script>` — **absolute, at the edge
   root, NOT under `/pypoe/`** (the auth surface lives at the edge root so the
   host-only `ac_auth_session` cookie and the banner's `/auth/*` calls resolve
   same-origin). Also add a favicon `<link rel="icon" ...>` (Vite handles this
   from `public/`).

3. **Keep `/status` (and `/health`).** The dashboard aggregator polls
   `GET :8006/status` to render PyPoe's tile in `equipment.yaml`
   (`pypoe_web`). Do not drop or move it during the rewrite.

4. **SPA fallback + serving the build.** Two options:
   - *Simplest:* keep the FastAPI process and serve the Vite `dist/` from it —
     mount the hashed `assets/` and return `dist/index.html` for any non-API,
     non-`/status` path (client-side routing needs an index.html fallback).
   - *Or* follow agente exactly (a small Node server serving the SPA). Either
     works; serving `dist/` from the existing FastAPI keeps it one process and
     one systemd unit (`pypoe-web`).

   The Caddy route stays `handle_path /pypoe/* { reverse_proxy :8006 }` (it
   strips `/pypoe`, so the backend sees its own root paths). Because the base
   is baked into the build, the `header_up X-Forwarded-Prefix /pypoe` line
   becomes optional — harmless to leave, unnecessary once the runtime prefix
   plumbing is gone.

## What this rewrite lets you delete (interim plumbing)

Once the React app ships, remove:

- `templates/*.html` (Jinja templates).
- `static/app.js`, `static/style.css`, `static/status-bar.js` (hand-written).
- `_ForwardedPrefixMiddleware` + the `base_path()` Jinja global in `app.py`
  (base path is now a build-time constant).
- The `asset_v` cache-busting token + the `?v={{ asset_v }}` on asset URLs
  (Vite content-hashes filenames instead).

Keep everything under `/api/*`, `/ws/chat/*`, `/status`, `/health`, `/auth/*`.

## Auth (unchanged for now)

PyPoe stays **banner-only, not enforced** — anyone reachable can use it; the
banner is just the sign-in surface. To enforce later, add a `forward_auth`
block on the `/pypoe` Caddy route (like `/agente` and `/analytica` have) and/or
turn on PyPoe's own cookie-verify mode (`PYPOE_AUTH_VERIFY_COOKIE=true`); the
React app would trust the edge-injected `X-Auth-User`, same as agente.

## Rough step order

1. Scaffold a Vite React app (mirror agente's config: `base: '/pypoe/'`, API/WS
   base under `/pypoe`).
2. Rebuild the current screens (chat list, conversation view, storage,
   settings) against the existing `/api/*` + `/ws/chat/*` — the API contract
   doesn't change.
3. Add `<script src="/auth/banner.js" defer>` + a favicon to `index.html`.
4. Serve `dist/` from FastAPI (or a Node server) with an SPA index.html
   fallback; keep `/status`, `/health`, `/api/*`, `/ws/*`.
5. Delete the interim plumbing listed above.
6. Test **behind the edge** at `http://100.64.254.6/pypoe/`: page loads,
   hashed assets 200, `/pypoe/api/conversations` 200, chat WebSocket upgrades,
   banner shows, favicon present, and the dashboard tile still reads `ready`
   from `/status`.

## See also

- `docs/README_WEB.md` — current web UI + how it's served/run.
- `LaAgenteAnalitica` repo — the Vite + edge + banner reference implementation.
- `ac-organic-lab/docs/AUTH_DESIGN.md` — the "every web service carries the
  central auth" policy and the banner/edge model.
- `ac-organic-lab/deploy/Caddyfile.single-edge` — the `/pypoe` edge route.
