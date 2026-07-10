import { useEffect, useState } from "react";
import { getAccountStatus } from "../lib/api.js";

// Compact footer strip mirroring the legacy status-bar.js: API key validity,
// Poe connectivity, storage size — polled every 30 s.
export function StatusBar() {
  const [status, setStatus] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getAccountStatus()
        .then((s) => {
          if (alive) {
            setStatus(s);
            setFailed(false);
          }
        })
        .catch(() => {
          if (alive) setFailed(true);
        });
    load();
    const iv = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  const items = [];
  if (failed) {
    items.push({ tone: "err", text: "Status unavailable" });
  } else if (status) {
    items.push({
      tone: status.api_key_status === "valid" ? "ok" : "err",
      text: `API: ${status.api_key_status ?? "unknown"}`,
    });
    const conn = status.connectivity;
    items.push({
      tone: conn?.status === "connected" ? "ok" : "err",
      text:
        conn?.status === "connected"
          ? `Connected${conn.response_time_ms ? ` (${conn.response_time_ms}ms)` : ""}`
          : `Connection: ${conn?.status ?? "unknown"}`,
    });
    const sizeMb = status.storage_usage?.database_size_mb;
    if (sizeMb != null) items.push({ tone: "ok", text: `Storage: ${sizeMb.toFixed(1)} MB` });
  }

  return (
    <footer className="status-bar">
      {items.map((it, i) => (
        <span key={i} className={`status-item ${it.tone}`}>
          <span className="dot" />
          {it.text}
        </span>
      ))}
    </footer>
  );
}
