import { useEffect, useState } from "react";
import { getStorageStats, getStorageConversations, runStorageCleanup } from "../lib/api.js";

function mb(v) {
  return v == null ? "—" : `${Number(v).toFixed(2)} MB`;
}

export function StorageView({ onDeleteConversation }) {
  const [stats, setStats] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [cleanupResult, setCleanupResult] = useState(null);

  function refresh() {
    getStorageStats().then(setStats).catch((e) => setError(String(e.message || e)));
    getStorageConversations().then(setRows).catch((e) => setError(String(e.message || e)));
  }

  useEffect(refresh, []);

  async function cleanup() {
    setCleanupResult(null);
    try {
      const res = await runStorageCleanup();
      setCleanupResult(res.message || `Cleaned ${res.files_cleaned ?? 0} file(s).`);
      refresh();
    } catch (e) {
      setCleanupResult(`Cleanup failed: ${e.message || e}`);
    }
  }

  return (
    <div className="page">
      <h2>Storage</h2>
      {error && <p className="form-error">{error}</p>}

      {stats && (
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-value">{stats.total_conversations}</div>
            <div className="stat-label">Conversations</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{mb(stats.storage_locations?.database?.size_mb)}</div>
            <div className="stat-label">Database</div>
            <div className="stat-hint">{stats.database_path}</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.media_files?.total_files ?? 0}</div>
            <div className="stat-label">Media files ({mb(stats.media_files?.total_size_mb)})</div>
          </div>
        </div>
      )}

      <div className="page-actions">
        <button className="btn" onClick={cleanup}>
          Clean up orphaned media
        </button>
        {cleanupResult && <span className="subtle">{cleanupResult}</span>}
      </div>

      {rows && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Conversation</th>
              <th>Mode</th>
              <th>Bot(s)</th>
              <th>Messages</th>
              <th>Media</th>
              <th>Updated</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>{c.topic || c.title || "Untitled"}</td>
                <td>{c.chat_mode || "chatbot"}</td>
                <td>{c.bot_names?.length ? c.bot_names.join(", ") : c.bot_name}</td>
                <td>{c.message_count}</td>
                <td>{c.media_count}</td>
                <td>{c.updated_at}</td>
                <td>
                  <button
                    className="icon-btn danger"
                    title="Delete conversation"
                    onClick={() => onDeleteConversation(c.id).then(refresh)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
