import { useCallback, useEffect, useRef, useState } from "react";
import { chatWsUrl, getMessages } from "./api.js";

// Mirrors the legacy app.js protocol on /ws/chat/{id}:
//   client -> {message, bot_name}
//   server -> {type: user_message|bot_response_start|bot_response_chunk|
//              bot_response_end|error|topic_updated, content?, model_name?, ...}
// model_name is set for group/debate fan-out (one stream per model) and null
// for single-bot chats. "Thinking..." / "Generating..." chunks are ephemeral
// placeholders, not content (same regex as the legacy UI).
const THINKING_RE = /^(Thinking|Generating)\.+(\s*\(\d+s elapsed\))?$/;
const SINGLE = "__single__";
const SEND_TIMEOUT_MS = 60_000;

/**
 * Chat state for one conversation: history, live streams, sending state.
 *
 * @param conversationId  active conversation (null = none selected)
 * @param onTopicUpdated  (conversationId, topic) => void
 */
export function useChat(conversationId, onTopicUpdated) {
  const [messages, setMessages] = useState([]); // {role, content, model_name?, timestamp?}
  const [streams, setStreams] = useState({}); // key -> {content, thinking}
  const [busy, setBusy] = useState(false);
  const [wsReady, setWsReady] = useState(false);
  const [loadError, setLoadError] = useState(null);

  const wsRef = useRef(null);
  const timeoutRef = useRef(null);
  const onTopicRef = useRef(onTopicUpdated);
  onTopicRef.current = onTopicUpdated;

  const clearSendTimeout = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  useEffect(() => {
    setMessages([]);
    setStreams({});
    setBusy(false);
    setWsReady(false);
    setLoadError(null);
    if (!conversationId) return undefined;

    let cancelled = false;

    getMessages(conversationId)
      .then((msgs) => {
        if (!cancelled) setMessages(msgs);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(String(e.message || e));
      });

    const ws = new WebSocket(chatWsUrl(conversationId));
    wsRef.current = ws;

    ws.onopen = () => {
      if (!cancelled) setWsReady(true);
    };
    ws.onclose = () => {
      if (!cancelled) setWsReady(false);
    };
    ws.onerror = () => {
      if (!cancelled) setWsReady(false);
    };

    ws.onmessage = (event) => {
      if (cancelled) return;
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      const key = data.model_name || SINGLE;

      switch (data.type) {
        case "user_message":
          clearSendTimeout();
          setMessages((m) => [
            ...m,
            { role: "user", content: data.content, timestamp: new Date().toISOString() },
          ]);
          break;

        case "bot_response_start":
          setStreams((s) => ({ ...s, [key]: { content: "", thinking: "" } }));
          setBusy(true);
          break;

        case "bot_response_chunk": {
          const chunk = data.content ?? "";
          setStreams((s) => {
            const cur = s[key] ?? { content: "", thinking: "" };
            if (THINKING_RE.test(chunk.trim())) {
              // Ephemeral status line; only show while no real content yet.
              return cur.content ? s : { ...s, [key]: { ...cur, thinking: chunk } };
            }
            return { ...s, [key]: { content: cur.content + chunk, thinking: "" } };
          });
          break;
        }

        case "bot_response_end":
          setStreams((s) => {
            const cur = s[key];
            const next = { ...s };
            delete next[key];
            if (cur?.content) {
              setMessages((m) => [
                ...m,
                {
                  role: "assistant",
                  content: cur.content,
                  model_name: data.model_name || null,
                  timestamp: new Date().toISOString(),
                },
              ]);
            }
            if (Object.keys(next).length === 0) {
              setBusy(false);
              clearSendTimeout();
            }
            return next;
          });
          break;

        case "error":
          setStreams((s) => {
            const next = { ...s };
            delete next[key];
            if (Object.keys(next).length === 0) {
              setBusy(false);
              clearSendTimeout();
            }
            return next;
          });
          setMessages((m) => [
            ...m,
            {
              role: "error",
              content: data.model_name ? `${data.model_name}: ${data.content}` : data.content,
              model_name: data.model_name || null,
            },
          ]);
          break;

        case "topic_updated":
          if (data.conversation_id && data.topic) {
            onTopicRef.current?.(data.conversation_id, data.topic);
          }
          break;

        default:
          break;
      }
    };

    return () => {
      cancelled = true;
      clearSendTimeout();
      try {
        ws.close();
      } catch {
        /* already closed */
      }
      if (wsRef.current === ws) wsRef.current = null;
    };
  }, [conversationId]);

  const send = useCallback(
    (text, botName) => {
      const ws = wsRef.current;
      if (!text.trim() || !ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(JSON.stringify({ message: text, bot_name: botName ?? null }));
      setBusy(true);
      clearSendTimeout();
      timeoutRef.current = setTimeout(() => {
        setBusy(false);
        setMessages((m) => [
          ...m,
          { role: "error", content: "Response timeout. Please try again." },
        ]);
      }, SEND_TIMEOUT_MS);
      return true;
    },
    [],
  );

  return { messages, streams, busy, wsReady, loadError, send };
}
