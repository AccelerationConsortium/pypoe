import { useEffect, useState } from "react";
import { getJson } from "./lib/api.js";

// Migration skeleton: proves the React app builds, loads behind the edge
// prefix, carries the shared banner, and talks to the EXISTING PyPoe API
// (unchanged). The real screens (chat view, group/debate, storage, settings)
// get rebuilt against these same /api/* + /ws/chat/* endpoints from here.
export default function App() {
  const [conversations, setConversations] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getJson("/conversations")
      .then(setConversations)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <h1 className="brand">PyPoe</h1>
        <p className="subtle">React UI — migration preview</p>
        {error && <p className="error">Failed to load: {error}</p>}
        {!conversations && !error && <p className="subtle">Loading…</p>}
        <ul className="conv-list">
          {conversations?.map((c) => (
            <li key={c.id} className="conv-item">
              <div className="conv-title">
                {c.topic || c.title || "Untitled"}
              </div>
              <div className="conv-meta">
                {Array.isArray(c.bot_names) && c.bot_names.length
                  ? c.bot_names.join(" · ")
                  : c.bot_name}
              </div>
            </li>
          ))}
        </ul>
      </aside>
      <main className="main">
        <div className="placeholder">
          <p>
            {conversations
              ? `${conversations.length} conversations loaded from the existing API.`
              : "Connecting to the PyPoe backend…"}
          </p>
          <p className="subtle">
            Chat view, modes, storage and settings will be rebuilt here.
          </p>
        </div>
      </main>
    </div>
  );
}
