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

async function request(path, options) {
  const res = await fetch(apiUrl(path), options);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function getJson(path) {
  return request(path, { headers: { Accept: "application/json" } });
}

export function postJson(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

export function patchJson(path, body) {
  return request(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

export function deleteJson(path) {
  return request(path, { method: "DELETE" });
}

// ---- typed-ish wrappers over the existing PyPoe API (unchanged backend) ----

export const listConversations = () => getJson("/conversations");
export const getMessages = (id) => getJson(`/conversation/${id}/messages`);
export const createConversation = (payload) => postJson("/conversation/new", payload);
export const deleteConversation = (id) => deleteJson(`/conversation/${id}`);
export const patchConversation = (id, payload) => patchJson(`/conversation/${id}`, payload);
export const getBots = () => getJson("/bots");
export const getStats = () => getJson("/stats");
export const getConfig = () => getJson("/config");
export const getAccountStatus = () => getJson("/account/status");
export const getStorageStats = () => getJson("/storage/stats");
export const getStorageConversations = () => getJson("/storage/conversations");
export const runStorageCleanup = () => postJson("/storage/cleanup");
