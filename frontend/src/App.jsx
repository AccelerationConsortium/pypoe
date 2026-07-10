import { useCallback, useEffect, useState } from "react";
import {
  deleteConversation,
  getBots,
  getStats,
  listConversations,
} from "./lib/api.js";
import { Sidebar } from "./components/Sidebar.jsx";
import { ChatView } from "./components/ChatView.jsx";
import { NewChatModal } from "./components/NewChatModal.jsx";
import { StorageView } from "./components/StorageView.jsx";
import { SettingsView } from "./components/SettingsView.jsx";
import { StatusBar } from "./components/StatusBar.jsx";

const COLLAPSE_KEY = "pypoe.react.sidebarCollapsed";

export default function App() {
  const [view, setView] = useState("chat"); // chat | storage | settings
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [bots, setBots] = useState([]);
  const [stats, setStats] = useState(null);
  const [showNewChat, setShowNewChat] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  const refresh = useCallback(() => {
    listConversations().then(setConversations).catch(() => {});
    getStats().then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    getBots()
      .then((r) => setBots(r.bots ?? []))
      .catch(() => {});
  }, [refresh]);

  function toggleSidebar() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* private mode */
      }
      return !c;
    });
  }

  const active = conversations.find((c) => c.id === activeId) ?? null;

  const handleTopicUpdated = useCallback((conversationId, topic) => {
    setConversations((list) =>
      list.map((c) => (c.id === conversationId ? { ...c, topic } : c)),
    );
  }, []);

  async function handleDelete(id) {
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await deleteConversation(id);
    } finally {
      if (id === activeId) setActiveId(null);
      refresh();
    }
  }

  function handleCreated(id) {
    setShowNewChat(false);
    setView("chat");
    refresh();
    setActiveId(id);
  }

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        stats={stats}
        collapsed={collapsed}
        onSelect={(id) => {
          setView("chat");
          setActiveId(id);
        }}
        onDelete={handleDelete}
        onNewChat={() => setShowNewChat(true)}
      />

      <div className="main-col">
        <nav className="topnav">
          <button className="icon-btn" title="Toggle conversation list" onClick={toggleSidebar}>
            ☰
          </button>
          <div className="tabs">
            {["chat", "storage", "settings"].map((v) => (
              <button
                key={v}
                className={`tab${view === v ? " active" : ""}`}
                onClick={() => setView(v)}
              >
                {v[0].toUpperCase() + v.slice(1)}
              </button>
            ))}
          </div>
        </nav>

        <main className="main-view">
          {view === "chat" && (
            <ChatView conversation={active} onTopicUpdated={handleTopicUpdated} />
          )}
          {view === "storage" && (
            <StorageView
              onDeleteConversation={async (id) => {
                await deleteConversation(id).catch(() => {});
                if (id === activeId) setActiveId(null);
                refresh();
              }}
            />
          )}
          {view === "settings" && <SettingsView />}
        </main>

        <StatusBar />
      </div>

      {showNewChat && (
        <NewChatModal
          bots={bots}
          onClose={() => setShowNewChat(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
