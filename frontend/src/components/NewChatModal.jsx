import { useState } from "react";
import { createConversation } from "../lib/api.js";

// Mirrors the backend's DEBATE_ROLE_PRESETS (app.py).
const DEBATE_ROLES = [
  { key: "defend", label: "Defend the topic" },
  { key: "critique", label: "Critique — find flaws" },
  { key: "steelman_opposite", label: "Steelman the opposite view" },
  { key: "devils_advocate", label: "Devil's advocate" },
  { key: "synthesizer", label: "Synthesizer — merge views" },
  { key: "custom", label: "Custom role…" },
];

export function NewChatModal({ bots, onClose, onCreated }) {
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState("chatbot");
  const [bot, setBot] = useState(bots[0] ?? "");
  const [botA, setBotA] = useState(bots[0] ?? "");
  const [botB, setBotB] = useState(bots[1] ?? bots[0] ?? "");
  const [debateTopic, setDebateTopic] = useState("");
  const [roleA, setRoleA] = useState("defend");
  const [roleB, setRoleB] = useState("critique");
  const [customA, setCustomA] = useState("");
  const [customB, setCustomB] = useState("");
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  const multi = mode === "group" || mode === "debate";

  async function submit(e) {
    e.preventDefault();
    setError(null);

    const payload = { title: title.trim() || null, chat_mode: mode };
    if (multi) {
      if (botA === botB) {
        setError("Pick two different participants.");
        return;
      }
      payload.bot_names = [botA, botB];
      payload.bot_name = botA;
      if (mode === "debate") {
        if (!debateTopic.trim()) {
          setError("Debate mode needs a topic.");
          return;
        }
        if ((roleA === "custom" && !customA.trim()) || (roleB === "custom" && !customB.trim())) {
          setError("Custom roles need a description.");
          return;
        }
        payload.debate_topic = debateTopic.trim();
        payload.bot_assignments = {
          [botA]: { role: roleA, custom_label: roleA === "custom" ? customA.trim() : null },
          [botB]: { role: roleB, custom_label: roleB === "custom" ? customB.trim() : null },
        };
      }
    } else {
      payload.bot_name = bot;
    }

    setPending(true);
    try {
      const res = await createConversation(payload);
      onCreated(res.conversation_id);
    } catch (err) {
      setError(String(err.message || err));
      setPending(false);
    }
  }

  const roleRow = (label, value, setValue, custom, setCustom) => (
    <div className="form-row">
      <label>{label}</label>
      <select value={value} onChange={(e) => setValue(e.target.value)}>
        {DEBATE_ROLES.map((r) => (
          <option key={r.key} value={r.key}>
            {r.label}
          </option>
        ))}
      </select>
      {value === "custom" && (
        <input
          type="text"
          placeholder="Describe the role…"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
        />
      )}
    </div>
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>New chat</h3>

        <div className="form-row">
          <label>Title (optional)</label>
          <input
            type="text"
            value={title}
            placeholder="Auto-generated if empty"
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div className="form-row">
          <label>Mode</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="chatbot">Chat bot — one model</option>
            <option value="group">Group chat — two models</option>
            <option value="debate">AI debate — two models + topic</option>
          </select>
        </div>

        {!multi && (
          <div className="form-row">
            <label>Bot</label>
            <select value={bot} onChange={(e) => setBot(e.target.value)}>
              {bots.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </div>
        )}

        {multi && (
          <>
            <div className="form-row">
              <label>Participant 1</label>
              <select value={botA} onChange={(e) => setBotA(e.target.value)}>
                {bots.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>Participant 2</label>
              <select value={botB} onChange={(e) => setBotB(e.target.value)}>
                {bots.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}

        {mode === "debate" && (
          <>
            <div className="form-row">
              <label>Debate topic</label>
              <input
                type="text"
                value={debateTopic}
                placeholder="The proposition to debate"
                onChange={(e) => setDebateTopic(e.target.value)}
              />
            </div>
            {roleRow(`${botA} role`, roleA, setRoleA, customA, setCustomA)}
            {roleRow(`${botB} role`, roleB, setRoleB, customB, setCustomB)}
          </>
        )}

        {error && <p className="form-error">{error}</p>}

        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={pending}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={pending}>
            {pending ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
