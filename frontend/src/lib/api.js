// All URLs derive from Vite's build-time base (import.meta.env.BASE_URL, e.g.
// "/pypoe-next/" in the preview build or "/" in dev). That single value keeps
// the app working behind the edge prefix without a runtime header. The edge
// strips the prefix, so the backend still sees its own root paths (/api/*, /ws/*).

const BASE = import.meta.env.BASE_URL; // always ends with "/"

/** Absolute-path URL for a backend API route. `path` should start with "/". */
export function apiUrl(path) {
  return `${BASE}api${path}`;
}

/** WebSocket URL for a chat room, prefix- and scheme-aware. */
export function chatWsUrl(conversationId) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${BASE}ws/chat/${conversationId}`;
}

export async function getJson(path) {
  const res = await fetch(apiUrl(path), { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json();
}

export async function postJson(path, body) {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status}`);
  return res.json();
}
