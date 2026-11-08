import { useEffect, useLayoutEffect, useRef, useState } from "react";
import "./Chat.css";

const SUGGESTIONS = [
  "Kolik Ryanairů je teď nad ČR?",
  "Co krouží nad Prahou?",
  "Letí teď nějaké vojenské letadlo?",
  "Které letadlo je nejvýš?",
];

// iOS doesn't shrink the layout viewport for the keyboard; expose the covered height so the
// sheet (and its input) can sit right above the keyboard.
function useKeyboardInset() {
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const root = document.documentElement.style;
    const update = () => {
      root.setProperty("--kb", `${Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop))}px`);
      root.setProperty("--vvh", `${Math.round(vv.height)}px`);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
      root.removeProperty("--kb");
      root.removeProperty("--vvh");
    };
  }, []);
}

// Replies may use a little Markdown: render **bold** and "- " bullets, everything else as plain text.
function Rich({ text }) {
  return text
    .replace(/^[-*] /gm, "• ")
    .split(/(\*\*[^*]+\*\*)/)
    .map((part, i) => (part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part));
}

async function ask(messages) {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (r.status === 429) throw new Error("Hodinový limit dotazů je vyčerpaný. Zkus to prosím později.");
  if (!r.ok) throw new Error("Odpověď se nepodařilo získat. Zkus to znovu.");
  return (await r.json()).reply;
}

// History lives in module memory only: it survives switching tabs, not a reload.
let history = [];

export default function Chat() {
  const [messages, setHistory] = useState(history);
  const setMessages = (m) => setHistory((history = m));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const list = useRef(null);
  const input = useRef(null);
  useKeyboardInset();

  // Grow the input with its text (up to the CSS max-height).
  useLayoutEffect(() => {
    const el = input.current;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [text]);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy, error]);

  const send = async (content) => {
    content = content.trim();
    if (!content || busy) return;
    const next = [...messages, { role: "user", content }];
    setMessages(next);
    setText("");
    setError(null);
    setBusy(true);
    try {
      const reply = await ask(next);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch (e) {
      // Drop the unanswered question so roles keep alternating; put it back in the input.
      setMessages(messages);
      setText(content);
      setError(e.message || "Odpověď se nepodařilo získat.");
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(text);
    }
  };

  return (
    <div className="chat">
      <div className="chat__list" ref={list}>
        {messages.length === 0 && (
          <div className="chat__intro">
            <div className="empty__icon">✦</div>
            <p className="empty__title">Zeptej se na provoz</p>
            <p>Odpovídám z aktuálních dat o letadlech nad Českem.</p>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg--${m.role}`}>
            {m.role === "assistant" ? <Rich text={m.content} /> : m.content}
          </div>
        ))}
        {busy && (
          <div className="msg msg--assistant msg--typing" aria-label="Píšu odpověď">
            <span /><span /><span />
          </div>
        )}
        {error && <div className="chat__error" role="alert">{error}</div>}
      </div>

      {/* After the first message the suggestions stay available as a scrollable row above the input. */}
      {messages.length > 0 && (
        <div className="chips chips--bar">
          {SUGGESTIONS.filter((s) => !messages.some((m) => m.role === "user" && m.content === s)).map((s) => (
            <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="chat__form"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
          input.current?.focus();
        }}
      >
        <textarea
          ref={input}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Napiš otázku…"
          aria-label="Otázka"
          enterKeyHint="send"
          maxLength={1000}
        />
        <button className="send" disabled={busy || !text.trim()} aria-label="Odeslat">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" /></svg>
        </button>
      </form>
      <p className="chat__note">Odpovídá AI z živých dat. Odpovědi nejsou ověřené.</p>
    </div>
  );
}
