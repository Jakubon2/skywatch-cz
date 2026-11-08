// "Mapa" tab: live event feed with history search and sharing.
// FeedLive (the tab's overlay, always mounted) owns the SSE stream, alert toasts, haptics/chime,
// the map ring for an opened event and ?event= / ?hex= deep links. The tab talks to it through `bus`.
import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { useApp, useMapLayer, useVisible } from "./state.jsx";
import {
  FILTER_TYPES, HIJACK_NOTE, eventCallsign, eventDetail, eventLabel, eventType, isExplanationPending, isHijackSquawk, timeAgo,
} from "./events.js";
import { shareImage, shareLink } from "./share.js";
import "./Feed.css";

const SOUND_KEY = "skywatch.sound"; // toggled in Settings
const PAGE = 50;

// ---------- Tiny pub/sub between the overlay and the tab ----------

const listeners = new Set();
const bus = {
  shared: null, // event opened from a ?event= link, shown pinned at the top of the feed
  on(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  emit(msg) {
    listeners.forEach((fn) => fn(msg));
  },
};

// ---------- Haptics and chime ----------

let audio;
const soundOn = () => {
  try {
    return JSON.parse(localStorage.getItem(SOUND_KEY) ?? "true") !== false;
  } catch {
    return true;
  }
};

function unlockAudio() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  audio ||= new AC();
  if (audio.state === "suspended") audio.resume();
}

// Two soft sine notes (three, a little higher, for an emergency).
function chime(urgent) {
  if (!soundOn()) return;
  navigator.vibrate?.(urgent ? [180, 80, 180] : [90]);
  if (!audio || audio.state !== "running") return; // browsers allow sound only after a tap
  const notes = urgent ? [784, 988, 784] : [659, 988];
  const t0 = audio.currentTime + 0.02;
  notes.forEach((f, i) => {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    const t = t0 + i * 0.14;
    osc.type = "sine";
    osc.frequency.value = f;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.12, t + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.6);
    osc.connect(gain).connect(audio.destination);
    osc.start(t);
    osc.stop(t + 0.65);
  });
}

// ---------- Opening an event: select the plane if it's live, else show where it happened ----------

function useOpenEvent() {
  const { aircraft, select, flyTo, setOpen, map } = useApp();
  return (e) => {
    bus.emit({ kind: "focus", event: e });
    const live = aircraft.find((a) => a.hex === e.hex);
    if (live && live.lat != null) {
      select(e.hex);
      flyTo(live.lat, live.lon);
    } else if (e.lat != null) {
      if (matchMedia("(min-width: 960px)").matches) flyTo(e.lat, e.lon, 10);
      else {
        // Phone: lower the sheet so the spot is visible, and center it in the map above the peeking sheet.
        setOpen(false);
        map?.flyToBounds(L.latLng(e.lat, e.lon).toBounds(100), { paddingTopLeft: [12, 70], paddingBottomRight: [12, 90], maxZoom: 10, duration: 0.6 });
      }
    }
  };
}

// ---------- Overlay ----------

const RING_SVG = '<span class="ev-ring__pulse"></span><span class="ev-ring__dot"></span>';

// Deep links are read once at load (not in a state initializer: StrictMode runs those twice), then removed from the URL.
const INITIAL_LINK = (() => {
  const p = new URLSearchParams(location.search);
  const event = p.get("event"), hex = p.get("hex");
  if (event || hex) {
    p.delete("event");
    p.delete("hex");
    history.replaceState(null, "", location.pathname + (p.size ? `?${p}` : "") + location.hash);
  }
  return { event: /^\d+$/.test(event || "") ? event : null, hex: /^[0-9a-f~]{6,7}$/i.test(hex || "") ? hex.toLowerCase() : null };
})();

export function FeedLive() {
  const { aircraft, map, select, flyTo } = useApp();
  const openEvent = useOpenEvent();
  const [focus, setFocus] = useState(null);
  const [toast, setToast] = useState(null);
  const [link, setLink] = useState(INITIAL_LINK);
  const visible = useVisible();
  const streamed = useRef(false);

  // SSE. EventSource reconnects by itself; after a drop the feed refetches to fill the gap.
  // Closed while the page is hidden (battery); reopening counts as a drop, so the feed catches up.
  useEffect(() => {
    if (!visible) return;
    const es = new EventSource("/api/stream");
    let dropped = streamed.current;
    streamed.current = true;
    es.onopen = () => {
      if (dropped) bus.emit({ kind: "reconnected" });
      dropped = false;
    };
    es.onerror = () => {
      dropped = true;
    };
    es.onmessage = (m) => {
      let msg;
      try {
        msg = JSON.parse(m.data);
      } catch {
        return;
      }
      bus.emit(msg);
      if (msg.kind === "event" && msg.event.type === "emergency") {
        chime(true);
        setToast({ id: Date.now(), urgent: true, title: `${eventLabel(msg.event)}: ${eventCallsign(msg.event)}`, message: eventDetail(msg.event), event: msg.event });
      } else if (msg.kind === "alert_hit") {
        chime(false);
        setToast({ id: Date.now(), title: msg.title, message: msg.message, hex: msg.hex, lat: msg.lat, lon: msg.lon });
      }
    };
    window.addEventListener("pointerdown", unlockAudio, { once: true });
    return () => {
      es.close();
      window.removeEventListener("pointerdown", unlockAudio);
    };
  }, [visible]);

  useEffect(() => bus.on((m) => m.kind === "focus" && setFocus(m.event)), []);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), toast.urgent ? 12000 : 8000);
    return () => clearTimeout(id);
  }, [toast]);

  // ?event=<id>: fetch it, pin it in the feed and open it once the map exists.
  useEffect(() => {
    if (!link.event || !map) return;
    fetch(`/api/events/${link.event}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((e) => {
        if (!e) return;
        bus.shared = e;
        bus.emit({ kind: "shared", event: e });
        openEvent(e);
      })
      .catch(() => {});
    setLink((l) => ({ ...l, event: null }));
  }, [link.event, map]); // eslint-disable-line react-hooks/exhaustive-deps

  // ?hex=<hex>: select now (the detail appears with the next data), fly there once the plane shows up.
  useEffect(() => {
    if (link.hex) select(link.hex);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!link.hex || !map) return;
    const a = aircraft.find((x) => x.hex === link.hex);
    if (a?.lat != null) {
      flyTo(a.lat, a.lon);
      setLink((l) => ({ ...l, hex: null }));
    }
  }, [aircraft, map, link.hex]); // eslint-disable-line react-hooks/exhaustive-deps

  // A pulsing ring where the opened event happened; fades after a while.
  useMapLayer(
    (m) => {
      if (!focus || focus.lat == null) return;
      const ring = L.marker([focus.lat, focus.lon], {
        icon: L.divIcon({ className: `ev-ring ${focus.type === "emergency" ? "ev-ring--danger" : ""}`, html: RING_SVG, iconSize: [44, 44] }),
        interactive: false,
        keyboard: false,
      }).addTo(m);
      const id = setTimeout(() => setFocus(null), 30000);
      return () => {
        clearTimeout(id);
        ring.remove();
      };
    },
    [focus],
  );

  if (!toast) return null;
  const onToast = () => {
    if (toast.event) openEvent(toast.event);
    else {
      select(toast.hex);
      if (toast.lat != null) flyTo(toast.lat, toast.lon);
    }
    setToast(null);
  };
  return (
    <div key={toast.id} className={`toast ${toast.urgent ? "toast--danger" : ""}`} role="status">
      <button className="toast__main" onClick={onToast}>
        <span className="toast__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d={toast.urgent ? eventType({ type: "emergency" }).icon : "M6 9.5a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15.5 6 9.5zM10 20.5a2.2 2.2 0 0 0 4 0"} />
          </svg>
        </span>
        <span className="toast__text">
          <b>{toast.title}</b>
          {toast.message && <span>{toast.message}</span>}
        </span>
      </button>
      <button className="toast__close" onClick={() => setToast(null)} aria-label="Zavřít upozornění">
        ✕
      </button>
    </div>
  );
}

// ---------- Tab ----------

const PERIODS = [
  ["", "Kdykoli"],
  ["24h", "24 h"],
  ["7d", "7 dní"],
  ["30d", "30 dní"],
];
const PERIOD_MS = { "24h": 864e5, "7d": 7 * 864e5, "30d": 30 * 864e5 };

function query({ q, types, period }, beforeId) {
  const p = new URLSearchParams({ limit: PAGE });
  if (beforeId) p.set("before_id", beforeId);
  if (q) p.set("q", q);
  types.forEach((t) => p.append("type", t));
  if (period) p.set("since", new Date(Date.now() - PERIOD_MS[period]).toISOString().slice(0, 19) + "+00:00");
  return `/api/events?${p}`;
}

const mergeNewest = (fresh, old) => {
  const ids = new Set(fresh.map((e) => e.id));
  return [...fresh, ...old.filter((e) => !ids.has(e.id))].sort((a, b) => b.id - a.id);
};

function useNow(ms) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

const Icon = ({ d }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d={d} />
  </svg>
);
const SHARE_ICON = "M12 3.5v11M8 7.5l4-4 4 4M5.5 12v6.5a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V12";
const IMAGE_ICON = "M5 4.5h14A1.5 1.5 0 0 1 20.5 6v12a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 18V6A1.5 1.5 0 0 1 5 4.5zM3.5 15.5l5-5 4.5 4.5 2.5-2.5 5 5M15.5 8.5h.01";
const SEARCH_ICON = "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.5 15.5 20 20";

function EventCard({ e, now, onOpen, pinned }) {
  const [note, setNote] = useState(null);
  const t = eventType(e);
  const detail = eventDetail(e);
  const aircraft = e.data?.type_name && e.type !== "interesting" ? e.data.type_name : e.aircraft_type;

  const share = async (fn, done) => {
    try {
      const r = await fn(e);
      if (r) setNote(done[r]);
    } catch {
      setNote("Sdílení se nepovedlo");
    }
    setTimeout(() => setNote(null), 2500);
  };

  return (
    <li className={`ev ev--${e.type} ${pinned ? "ev--pinned" : ""}`} style={{ "--h": t.hue }}>
      <button className="ev__main" onClick={() => onOpen(e)}>
        <span className="ev__icon">
          <Icon d={t.icon} />
        </span>
        <span className="ev__body">
          <span className="ev__top">
            <span className="ev__label">{pinned ? `Sdíleno · ${eventLabel(e)}` : eventLabel(e)}</span>
            <time dateTime={e.started_at} title={new Date(e.started_at).toLocaleString("cs-CZ")}>{timeAgo(e.started_at, now)}</time>
          </span>
          <span className="ev__title">
            {eventCallsign(e)}
            {aircraft && <span className="ev__type">{aircraft}</span>}
          </span>
          {detail && <span className="ev__detail">{detail}</span>}
          {isHijackSquawk(e) && <span className="ev__warn">{HIJACK_NOTE}</span>}
          {e.explanation ? (
            <span className="ev__ai">
              <span className="ev__ai-label">Vysvětlení od AI, neověřeno</span>
              {e.explanation}
            </span>
          ) : (
            isExplanationPending(e, now) && (
              <span className="ev__ai ev__ai--pending" aria-label="Vysvětlení se připravuje">
                <span className="skel" />
                <span className="skel" />
                <span className="skel skel--short" />
              </span>
            )
          )}
        </span>
      </button>
      <div className="ev__foot">
        {note && <span className="ev__toast" role="status">{note}</span>}
        <button className="ev__act" onClick={() => share(shareLink, { copied: "Odkaz zkopírován", shared: "Sdíleno" })} aria-label="Sdílet odkaz">
          <Icon d={SHARE_ICON} />
          Sdílet
        </button>
        <button className="ev__act" onClick={() => share(shareImage, { saved: "Obrázek uložen", shared: "Sdíleno" })} aria-label="Sdílet jako obrázek">
          <Icon d={IMAGE_ICON} />
          Obrázek
        </button>
      </div>
    </li>
  );
}

export default function Feed() {
  const openEvent = useOpenEvent();
  const now = useNow(30_000);
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [types, setTypes] = useState([]);
  const [period, setPeriod] = useState("");
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [more, setMore] = useState({ done: false, busy: false });
  const [shared, setShared] = useState(bus.shared);
  const sentinel = useRef(null);

  const filters = useMemo(() => ({ q, types, period }), [q, types, period]);
  const searching = Boolean(q || types.length || period);
  const live = useRef(!searching);
  live.current = !searching;

  // Debounce typing.
  useEffect(() => {
    const id = setTimeout(() => setQ(text.trim()), 300);
    return () => clearTimeout(id);
  }, [text]);

  // First page for the current filters.
  useEffect(() => {
    const ac = new AbortController();
    setStatus("loading");
    fetch(query(filters), { signal: ac.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((list) => {
        setItems(list);
        setMore({ done: list.length < PAGE, busy: false });
        setStatus("ready");
      })
      .catch((err) => err?.name !== "AbortError" && setStatus("error"));
    return () => ac.abort();
  }, [filters]);

  // Live updates. Search results don't take new events; explanations update everywhere.
  useEffect(
    () =>
      bus.on((m) => {
        if (m.kind === "event" && live.current) setItems((list) => (list.some((e) => e.id === m.event.id) ? list : [m.event, ...list]));
        else if (m.kind === "explanation") {
          const patch = (e) => (e.id === m.id ? { ...e, explanation: m.explanation, explained_at: m.explained_at } : e);
          setItems((list) => list.map(patch));
          setShared((s) => s && patch(s));
        } else if (m.kind === "shared") setShared(m.event);
        else if (m.kind === "reconnected" && live.current)
          fetch(query({ q: "", types: [], period: "" }))
            .then((r) => (r.ok ? r.json() : []))
            .then((fresh) => setItems((list) => mergeNewest(fresh, list)))
            .catch(() => {});
      }),
    [],
  );

  // Infinite scroll.
  const loadMore = () => {
    if (more.done || more.busy || !items.length) return;
    setMore({ done: false, busy: true });
    fetch(query(filters, items[items.length - 1].id))
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((list) => {
        setItems((old) => mergeNewest(old, list));
        setMore({ done: list.length < PAGE, busy: false });
      })
      .catch(() => setMore({ done: false, busy: false }));
  };
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(([en]) => en.isIntersecting && loadMoreRef.current(), { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [status]);

  const toggleType = (t) => setTypes((ts) => (ts.includes(t) ? ts.filter((x) => x !== t) : [...ts, t]));
  const clear = () => {
    setText("");
    setQ("");
    setTypes([]);
    setPeriod("");
  };
  const showShared = shared && !searching;
  const list = showShared ? items.filter((e) => e.id !== shared.id) : items;

  return (
    <div className="feed">
      <div className="feed__head">
        <h2 className="section-title">{searching ? "Hledání v historii" : "Co se teď děje nad Českem"}</h2>
      </div>

      <div className="feed-search" role="search">
        <label className="feed-search__field">
          <Icon d={SEARCH_ICON} />
          <input
            type="search"
            value={text}
            onChange={(ev) => setText(ev.target.value)}
            placeholder="Let, typ, registrace…"
            aria-label="Hledat v událostech"
            enterKeyHint="search"
          />
        </label>
        <select className="feed-search__period" value={period} onChange={(ev) => setPeriod(ev.target.value)} aria-label="Období">
          {PERIODS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>
      <div className="pick-chips" role="group" aria-label="Typ události">
        {FILTER_TYPES.map(([t, l]) => (
          <button key={t} className={`pick-chip ${types.includes(t) ? "is-on" : ""}`} aria-pressed={types.includes(t)} onClick={() => toggleType(t)} style={{ "--h": eventType({ type: t }).hue }}>
            {l}
          </button>
        ))}
      </div>

      {status === "error" && (
        <div className="empty">
          <div className="empty__icon">!</div>
          <p className="empty__title">Události se nenačetly</p>
          <p>Backend teď neodpovídá. Zkusím to znovu, až se změní filtr, nebo obnov stránku.</p>
        </div>
      )}

      {status === "loading" && (
        <ul className="ev-list" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <li key={i} className="ev ev--ghost">
              <span className="ev__icon" />
              <span className="ev__body">
                <span className="skel skel--short" />
                <span className="skel skel--title" />
                <span className="skel" />
              </span>
            </li>
          ))}
        </ul>
      )}

      {status === "ready" && !list.length && !showShared && (
        <div className="empty">
          <div className="empty__icon">{searching ? "⌕" : "✈︎"}</div>
          <p className="empty__title">{searching ? "Nic nenalezeno" : "Zatím klid"}</p>
          <p>{searching ? "Zkus jiný výraz, typ nebo delší období." : "Jakmile se nad Českem stane něco zajímavého, uvidíš to tady i s vysvětlením."}</p>
          {searching && (
            <button className="btn btn--ghost btn--small" onClick={clear}>
              Zrušit filtry
            </button>
          )}
        </div>
      )}

      {status === "ready" && (list.length > 0 || showShared) && (
        <ul className="ev-list">
          {showShared && <EventCard e={shared} now={now} onOpen={openEvent} pinned />}
          {list.map((e) => (
            <EventCard key={e.id} e={e} now={now} onOpen={openEvent} />
          ))}
        </ul>
      )}
      {status === "ready" && list.length > 0 && (
        <div ref={sentinel} className="feed__end">
          {more.busy ? "Načítám starší…" : more.done ? (searching ? `Nalezeno ${list.length}` : "Starší události už nejsou") : ""}
        </div>
      )}
    </div>
  );
}
