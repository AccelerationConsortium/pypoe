import { useMemo, useState } from "react";

function timeLabel(ts) {
  if (!ts) return "";
  const d = new Date(ts.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function Sidebar({
  conversations,
  activeId,
  stats,
  collapsed,
  onSelect,
  onDelete,
  onNewChat,
}) {
  const [query, setQuery] = useState("");
  const [botFilter, setBotFilter] = useState("");

  const botsInUse = useMemo(() => {
    const set = new Set();
    conversations.forEach((c) => {
      (c.bot_names?.length ? c.bot_names : [c.bot_name]).forEach((b) => b && set.add(b));
    });
    return [...set].sort();
  }, [conversations]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return conversations.filter((c) => {
      if (botFilter) {
        const bots = c.bot_names?.length ? c.bot_names : [c.bot_name];
        if (!bots.includes(botFilter)) return false;
      }
      if (!q) return true;
      return `${c.topic ?? ""} ${c.title ?? ""}`.toLowerCase().includes(q);
    });
  }, [conversations, query, botFilter]);

  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="sidebar-head">
        <h1 className="brand">PyPoe</h1>
        <button className="btn primary" onClick={onNewChat}>
          + New chat
        </button>
      </div>

      <div className="sidebar-filters">
        <input
          type="search"
          placeholder="Search conversations…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={botFilter} onChange={(e) => setBotFilter(e.target.value)}>
          <option value="">All bots</option>
          {botsInUse.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
      </div>

      {stats && (
        <div className="sidebar-stats">
          <span>
            <strong>{stats.total_conversations}</strong> chats
          </span>
          <span>
            <strong>{stats.total_messages}</strong> messages
          </span>
        </div>
      )}

      <ul className="conv-list">
        {visible.map((c) => (
          <li
            key={c.id}
            className={`conv-item${c.id === activeId ? " active" : ""}`}
            onClick={() => onSelect(c.id)}
          >
            <div className="conv-body">
              <div className="conv-title">{c.topic || c.title || "Untitled"}</div>
              <div className="conv-meta">
                <span className="conv-bots">
                  {c.bot_names?.length ? c.bot_names.join(" · ") : c.bot_name}
                </span>
                {c.chat_mode && c.chat_mode !== "chatbot" && (
                  <span className={`mode-chip ${c.chat_mode}`}>{c.chat_mode}</span>
                )}
                <span className="conv-time">{timeLabel(c.updated_at || c.created_at)}</span>
              </div>
            </div>
            <button
              className="icon-btn danger"
              title="Delete conversation"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(c.id);
              }}
            >
              ✕
            </button>
          </li>
        ))}
        {visible.length === 0 && <li className="conv-empty">No conversations</li>}
      </ul>
    </aside>
  );
}
