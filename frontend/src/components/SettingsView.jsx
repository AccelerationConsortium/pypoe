import { useEffect, useState } from "react";
import { getConfig, getStats } from "../lib/api.js";

export function SettingsView() {
  const [config, setConfig] = useState(null);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getConfig().then(setConfig).catch((e) => setError(String(e.message || e)));
    getStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div className="page">
      <h2>Settings</h2>
      {error && <p className="form-error">{error}</p>}

      {config && (
        <>
          <h3 className="section-title">Backend</h3>
          <dl className="kv">
            <dt>Version</dt>
            <dd>{config.backend_version}</dd>
            <dt>Database</dt>
            <dd>{config.database_path}</dd>
            <dt>Authentication</dt>
            <dd>
              {config.authentication_enabled ? `enabled (${config.auth_mode})` : "open"}
            </dd>
            <dt>Available bots</dt>
            <dd>{(config.available_bots || []).join(", ")}</dd>
          </dl>
        </>
      )}

      {stats && (
        <>
          <h3 className="section-title">Usage</h3>
          <dl className="kv">
            <dt>Conversations</dt>
            <dd>
              {stats.total_conversations} total · {stats.active_conversations} active
            </dd>
            <dt>Messages</dt>
            <dd>
              {stats.total_messages} ({stats.total_user_messages} user /{" "}
              {stats.total_assistant_messages} assistant)
            </dd>
            <dt>Words</dt>
            <dd>{stats.total_words}</dd>
            <dt>Bot usage</dt>
            <dd>
              {Object.entries(stats.bot_usage || {})
                .map(([b, n]) => `${b}: ${n}`)
                .join(" · ") || "—"}
            </dd>
            <dt>Modes</dt>
            <dd>
              {Object.entries(stats.chat_mode_usage || {})
                .map(([m, n]) => `${m}: ${n}`)
                .join(" · ") || "—"}
            </dd>
          </dl>
        </>
      )}
    </div>
  );
}
