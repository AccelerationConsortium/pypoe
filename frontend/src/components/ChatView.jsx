import { useEffect, useRef, useState } from "react";
import { useChat } from "../lib/useChat.js";

function timeLabel(ts) {
  if (!ts) return "";
  const d = new Date(ts.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Message({ msg }) {
  return (
    <div className={`msg ${msg.role}`}>
      <div className="msg-bubble">
        {msg.model_name && msg.role === "assistant" && (
          <div className="msg-model">{msg.model_name}</div>
        )}
        <div className="msg-content">{msg.content}</div>
        {msg.timestamp && <div className="msg-time">{timeLabel(msg.timestamp)}</div>}
      </div>
    </div>
  );
}

function StreamingMessage({ modelName, stream }) {
  return (
    <div className="msg assistant streaming">
      <div className="msg-bubble">
        {modelName !== "__single__" && <div className="msg-model">{modelName}</div>}
        <div className="msg-content">
          {stream.content || (
            <span className="thinking">{stream.thinking || "Thinking…"}</span>
          )}
          <span className="cursor" aria-hidden>
            ▍
          </span>
        </div>
      </div>
    </div>
  );
}

export function ChatView({ conversation, onTopicUpdated }) {
  const { messages, streams, busy, wsReady, loadError, send } = useChat(
    conversation?.id ?? null,
    onTopicUpdated,
  );
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  const streamEntries = Object.entries(streams);

  // Follow the tail as messages/chunks arrive.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streamEntries.length, streams]);

  useEffect(() => {
    if (!busy) inputRef.current?.focus();
  }, [busy, conversation?.id]);

  if (!conversation) {
    return (
      <div className="chat-empty">
        <h2>Welcome to PyPoe</h2>
        <p>Select a conversation on the left, or start a new chat.</p>
      </div>
    );
  }

  function submit() {
    const text = draft.trim();
    if (!text || busy) return;
    if (send(text, conversation.bot_name)) setDraft("");
  }

  const isDebate = conversation.chat_mode === "debate";

  return (
    <div className="chat">
      <header className="chat-header">
        <div className="chat-headline">
          <h2>{conversation.topic || conversation.title || "Untitled"}</h2>
          <div className="chat-sub">
            {conversation.bot_names?.length
              ? conversation.bot_names.join(" · ")
              : conversation.bot_name}
            {conversation.chat_mode && conversation.chat_mode !== "chatbot" && (
              <span className={`mode-chip ${conversation.chat_mode}`}>
                {conversation.chat_mode}
              </span>
            )}
            <span
              className={`ws-dot ${wsReady ? "on" : "off"}`}
              title={wsReady ? "Connected" : "Disconnected"}
            />
          </div>
        </div>
      </header>

      {isDebate && conversation.debate_topic && (
        <div className="debate-banner">
          <span className="debate-label">Debate topic</span>
          <span className="debate-topic">{conversation.debate_topic}</span>
        </div>
      )}

      <div className="chat-scroll" ref={scrollRef}>
        {loadError && <div className="msg error"><div className="msg-bubble">{loadError}</div></div>}
        {messages.map((m, i) => (
          <Message key={i} msg={m} />
        ))}
        {streamEntries.map(([model, stream]) => (
          <StreamingMessage key={model} modelName={model} stream={stream} />
        ))}
      </div>

      <div className="chat-input">
        <textarea
          ref={inputRef}
          rows={2}
          value={draft}
          disabled={busy || !wsReady}
          placeholder={
            !wsReady ? "Connecting…" : busy ? "Waiting for response…" : "Type your message…"
          }
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button className="btn primary" onClick={submit} disabled={busy || !wsReady || !draft.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
