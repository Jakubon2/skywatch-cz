// History playback state, shared by the Stats tab (controls) and the always-mounted map overlay (Playback.jsx).
// Lives outside React so playback keeps running when the user switches tabs.
// Data: GET /api/history?from=&to=&step= (backend keeps 24 h, max ~240 frames per request), fetched in windows.
import { useSyncExternalStore } from "react";

export const SPEEDS = [60, 300, 900]; // simulated seconds per real second
const TICK_MS = 500;
const WINDOW_FRAMES = 120; // frames per fetched window
const RETENTION_S = 24 * 3600;

let state = {
  active: false,
  playing: false,
  speed: 300,
  t: 0, // current playback time, unix seconds
  min: 0, // slider range
  max: 0,
  data: null, // last /api/history response covering t
  loading: false,
  error: false,
};
const subs = new Set();
const set = (patch) => {
  state = { ...state, ...patch };
  subs.forEach((f) => f());
};

export const usePlayback = () =>
  useSyncExternalStore(
    (f) => (subs.add(f), () => subs.delete(f)),
    () => state,
  );

const stepFor = (speed) => Math.max(30, Math.round((speed * TICK_MS) / 1000));

// ---- fetching ----

let reqId = 0;
let prefetching = false;

function fetchWindow(start, background = false) {
  const step = stepFor(state.speed);
  const from = Math.max(state.min, Math.floor(start));
  const to = Math.min(state.max, from + step * WINDOW_FRAMES);
  const id = ++reqId;
  if (background) prefetching = true;
  else set({ loading: true, error: false });
  return fetch(`/api/history?from=${from}&to=${to}&step=${step}`)
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((data) => {
      if (id !== reqId || !state.active) return;
      // A background prefetch only replaces the data once playback has moved into it.
      set({ data, loading: false, error: false });
    })
    .catch(() => {
      if (id === reqId && state.active) set({ loading: false, error: true, playing: false });
    })
    .finally(() => {
      if (background) prefetching = false;
    });
}

const covers = (d, t) => d && t >= d.from && t <= d.to;

let seekTimer = null;
function ensure(t, { debounce = false } = {}) {
  const d = state.data;
  const step = stepFor(state.speed);
  if (covers(d, t) && d.step === step) {
    // Prefetch the next window when 75 % through, so playing doesn't stall.
    const span = d.to - d.from;
    if (state.playing && !prefetching && d.to < state.max && t > d.from + span * 0.75) fetchWindow(t - step * 2, true);
    return;
  }
  const start = t - step * (state.playing ? 2 : WINDOW_FRAMES / 2);
  clearTimeout(seekTimer);
  if (debounce) seekTimer = setTimeout(() => fetchWindow(start), 200);
  else fetchWindow(start);
}

// ---- ticking ----

let timer = null;
function tick() {
  if (!state.playing || state.loading) return;
  const t = Math.min(state.max, state.t + (state.speed * TICK_MS) / 1000);
  set({ t, playing: t < state.max });
  ensure(t);
}

// ---- public actions ----

export const playback = {
  // `earliest`: first moment with recorded data (from /api/stats), so we don't start in an empty past.
  start(earliest) {
    const max = Math.floor(Date.now() / 1000);
    const min = Math.max(max - RETENTION_S, earliest ? Math.floor(earliest) : 0);
    const t = min; // "přehrát posledních 24 h": from the start of the range
    set({ active: true, playing: true, min, max, t, data: null, error: false });
    ensure(t);
    clearInterval(timer);
    timer = setInterval(tick, TICK_MS);
  },
  stop() {
    clearInterval(timer);
    clearTimeout(seekTimer);
    reqId++;
    set({ active: false, playing: false, data: null, loading: false, error: false });
  },
  toggle() {
    if (state.playing) return set({ playing: false });
    // At the end: start over from the beginning of the range.
    const t = state.t >= state.max ? state.min : state.t;
    set({ playing: true, t });
    ensure(t);
  },
  seek(t) {
    set({ t });
    ensure(t, { debounce: true });
  },
  setSpeed(speed) {
    set({ speed });
    ensure(state.t);
  },
  retry() {
    ensure(state.t);
  },
};

// Latest frame at or before t (frames are oldest first). Returns the same object for the same frame.
export function frameAt(data, t) {
  const frames = data?.frames;
  if (!frames?.length) return null;
  let lo = 0;
  let hi = frames.length - 1;
  if (t < frames[0].t) return null;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid].t <= t) lo = mid;
    else hi = mid - 1;
  }
  return frames[lo];
}

export const TICK_SECONDS = TICK_MS / 1000;
