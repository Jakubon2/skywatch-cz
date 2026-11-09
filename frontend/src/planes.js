// Aircraft drawn on one canvas instead of ~180 DOM markers. DOM markers (each its own GPU layer, all
// repositioned on every pinch-zoom frame) made the map stutter on phones. Leaflet's canvas renderer does the
// positioning, padding and zoom animation; this file only draws. While the map moves nothing is redrawn:
// the canvas moves (or scales) with the map and is redrawn once on moveend.
import L from "leaflet";
import { AIRCRAFT_ICONS, EMERGENCY_SQUAWKS, aircraftKind, altitudeHue, callsign, isGround } from "./aircraft.js";

const GLIDE_MS = 10_000; // planes glide to each new position over one snapshot interval
const TICK_MS = 250; // redraw rate while gliding (planes move ~1 px per tick at zoom 9)
const LABEL_FONT = '11.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, system-ui, sans-serif';

const PATHS = Object.fromEntries(Object.entries(AIRCRAFT_ICONS).map(([k, svg]) => [k, new Path2D(svg.match(/ d="([^"]+)"/)[1])]));
const fmt = (n) => Math.round(n).toLocaleString("cs-CZ");

// Second label line: altitude, speed and a climb/descent arrow, metric.
export function labelInfo(a) {
  if (isGround(a)) return "na zemi";
  const parts = [];
  if (typeof a.alt_baro === "number") {
    const arrow = a.baro_rate > 500 ? "↑" : a.baro_rate < -500 ? "↓" : "";
    parts.push(`${arrow}${fmt(Math.round((a.alt_baro * 0.3048) / 10) * 10)} m`);
  }
  if (a.gs != null) parts.push(`${fmt(a.gs * 1.852)} km/h`);
  return parts.join(" · ");
}

// Which label wins when two overlap: selected, emergency, military, heavy, then higher planes.
function labelPriority(a, sel) {
  let p = a.alt_baro === "ground" ? 0 : 20 + Math.min(a.alt_baro || 0, 45000) / 1000;
  if (sel) p += 1000;
  if (a.squawk in EMERGENCY_SQUAWKS) p += 500;
  if (a.dbFlags & 1) p += 100;
  if (aircraftKind(a) === "heavy") p += 30;
  return p;
}

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

export const PlaneLayer = L.Canvas.extend({
  options: { padding: 0.5, pane: "planes", labelZoom: 7, groundLabelZoom: 13 },

  initialize(options) {
    L.Canvas.prototype.initialize.call(this, options);
    this.planes = new globalThis.Map(); // hex -> { a, from: [lat, lon], to: [lat, lon], t0, rot }
    this.selected = null;
    this.dimmed = null;
    this.shownLabels = new Set();
  },

  onAdd(map) {
    if (!map.getPane("planes")) map.createPane("planes").style.zIndex = 610; // above overlays, below popups
    L.Canvas.prototype.onAdd.call(this, map);
    this._container.style.pointerEvents = "none"; // taps go to the map; see planeAt()
    this._readColors = () => ((this.colors = null), this.redraw());
    darkQuery.addEventListener("change", this._readColors);
    map.on("movestart", this._moveStart, this).on("moveend", this._moveEnd, this).on("labelschange", this.redraw, this);
    this._tick = setInterval(() => this._gliding() && this.redraw(), TICK_MS);
  },

  onRemove(map) {
    clearInterval(this._tick);
    darkQuery.removeEventListener("change", this._readColors);
    map.off("movestart", this._moveStart, this).off("moveend", this._moveEnd, this).off("labelschange", this.redraw, this);
    L.Canvas.prototype.onRemove.call(this, map);
  },

  _moveStart() {
    this._moving = true;
  },
  _moveEnd() {
    this._moving = false;
  },

  // Leaflet calls _update on moveend (resizes, clears and translates the canvas); then we draw.
  _update() {
    if (this._map._animatingZoom && this._bounds) return;
    L.Canvas.prototype._update.call(this);
    this._drawPlanes();
  },
  _draw() {}, // no vector paths of our own

  /** Replace the aircraft list (one snapshot). `glide` false = jump to the new positions. */
  setAircraft(list, glide) {
    const now = performance.now();
    const seen = new Set();
    for (const a of list) {
      seen.add(a.hex);
      const p = this.planes.get(a.hex);
      if (!p) {
        this.planes.set(a.hex, { a, from: [a.lat, a.lon], to: [a.lat, a.lon], t0: now, rot: a.track ?? 0 });
        continue;
      }
      p.from = glide ? this._pos(p, now) : [a.lat, a.lon];
      p.to = [a.lat, a.lon];
      p.t0 = now;
      p.a = a;
      if (a.track != null) p.rot = a.track;
    }
    for (const hex of this.planes.keys()) if (!seen.has(hex)) this.planes.delete(hex);
    this.redraw();
  },

  setSelected(hex) {
    this.selected = hex;
    this.redraw();
  },
  setDimmed(set) {
    this.dimmed = set;
    this.redraw();
  },

  /** Current (gliding) position of a plane as [lat, lon]. */
  position(hex) {
    const p = this.planes.get(hex);
    return p && this._pos(p, performance.now());
  },

  /** Hex of the plane under a container point (a tap), or null. */
  planeAt(point, radius = 20) {
    if (!this._map) return null;
    const now = performance.now();
    let best = null, bestD = radius;
    for (const [hex, p] of this.planes) {
      const c = this._map.latLngToContainerPoint(this._pos(p, now));
      const d = Math.hypot(c.x - point.x, c.y - point.y);
      if (d < bestD) (best = hex), (bestD = d);
    }
    return best;
  },

  redraw() {
    if (!this._map || this._moving || this._map._animatingZoom || !this._ctx) return;
    const ctx = this._ctx, c = this._container;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.restore();
    this._drawPlanes();
    return this;
  },

  _gliding() {
    const now = performance.now();
    for (const p of this.planes.values()) if (now - p.t0 < GLIDE_MS && (p.from[0] !== p.to[0] || p.from[1] !== p.to[1])) return true;
    return false;
  },

  _pos(p, now) {
    const t = Math.min(1, (now - p.t0) / GLIDE_MS);
    return [p.from[0] + (p.to[0] - p.from[0]) * t, p.from[1] + (p.to[1] - p.from[1]) * t];
  },

  _colors() {
    if (!this.colors) {
      const s = getComputedStyle(this._map.getContainer());
      const v = (n) => s.getPropertyValue(n).trim();
      this.colors = {
        planeL: v("--plane-l"), stroke: v("--plane-stroke"), muted: v("--muted"), danger: v("--danger"),
        accent: v("--accent"), accentSoft: v("--accent-soft"), surface: v("--surface-strong"), border: v("--border"), text: v("--text"),
      };
    }
    return this.colors;
  },

  _drawPlanes() {
    const map = this._map;
    const ctx = this._ctx;
    if (!map || !ctx) return;
    const col = this._colors();
    const z = map.getZoom();
    const base = z <= 6 ? 15 : z === 7 ? 18 : 22; // smaller planes when zoomed out, so busy airspace isn't a blob
    const box = map.getContainer();
    const labelsOn = z >= this.options.labelZoom && !box.classList.contains("labels-off");
    const groundLabels = z >= this.options.groundLabelZoom;
    const view = this._bounds;
    const now = performance.now();

    const items = [];
    for (const [hex, p] of this.planes) {
      const pt = map.latLngToLayerPoint(this._pos(p, now));
      if (pt.x < view.min.x - 40 || pt.y < view.min.y - 40 || pt.x > view.max.x + 40 || pt.y > view.max.y + 40) continue;
      const sel = hex === this.selected;
      const dim = !sel && Boolean(this.dimmed?.has(hex));
      items.push({ hex, p, pt, sel, dim, order: sel ? 3 : dim ? 0 : p.a.squawk in EMERGENCY_SQUAWKS ? 2 : 1 });
    }
    items.sort((x, y) => x.order - y.order);

    for (const { p, pt, sel, dim } of items) {
      const a = p.a, kind = aircraftKind(a), ground = isGround(a);
      let size = base * (kind === "heavy" ? 1.2 : 1) * (ground ? 0.7 : 1);
      if (sel) {
        size += 8;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 22, 0, 2 * Math.PI);
        ctx.fillStyle = col.accentSoft;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = col.accent;
        ctx.stroke();
      }
      ctx.save();
      ctx.globalAlpha = dim ? 0.22 : 1;
      ctx.translate(pt.x, pt.y);
      ctx.rotate((p.rot * Math.PI) / 180);
      ctx.scale(size / 24, size / 24);
      ctx.translate(-12, -12);
      ctx.fillStyle = dim || ground ? col.muted : a.squawk in EMERGENCY_SQUAWKS ? col.danger : `hsl(${altitudeHue(a) ?? 0} 85% ${col.planeL})`;
      ctx.strokeStyle = col.stroke;
      ctx.lineWidth = 1.4;
      ctx.lineJoin = "round";
      ctx.stroke(PATHS[kind]); // stroke first: a halo that separates the plane from the map
      ctx.fill(PATHS[kind]);
      ctx.restore();
    }

    this._drawLabels(items.filter((i) => i.sel || (labelsOn && !i.dim && (groundLabels || !isGround(i.p.a)))), col);
  },

  // Greedy label placement: best label first, skip any that would overlap one already placed.
  _drawLabels(items, col) {
    const ctx = this._ctx;
    ctx.font = LABEL_FONT;
    const boxes = items.map(({ hex, p, pt, sel }) => {
      const a = p.a, name = callsign(a), type = a.t || "", info = labelInfo(a);
      ctx.font = `700 ${LABEL_FONT}`;
      const wName = ctx.measureText(name).width;
      ctx.font = `600 10.5px ${LABEL_FONT.split("px ")[1]}`;
      const wType = type ? ctx.measureText(type).width + 4 : 0;
      ctx.font = LABEL_FONT;
      const wInfo = info ? ctx.measureText(info).width : 0;
      // Label sits right of the plane, like the old DOM label (left 29px, top 3px of a 32px icon).
      const r = { x: Math.round(pt.x + 13), y: Math.round(pt.y - 13), w: Math.ceil(Math.max(wName + wType, wInfo)) + 16, h: info ? 36 : 21 };
      // Small bonus for labels already shown, so they don't flicker between snapshots.
      const prio = labelPriority(a, sel) + (this.shownLabels.has(hex) ? 5 : 0);
      return { hex, sel, r, name, type, info, wName, prio };
    });
    boxes.sort((x, y) => y.prio - x.prio);
    const placed = [];
    this.shownLabels = new Set();
    for (const b of boxes) {
      const r = b.r;
      if (!b.sel && placed.some((q) => r.x < q.x + q.w + 2 && q.x < r.x + r.w + 2 && r.y < q.y + q.h + 2 && q.y < r.y + r.h + 2)) continue;
      placed.push(r);
      this.shownLabels.add(b.hex);
      ctx.beginPath();
      ctx.roundRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1, 8);
      ctx.fillStyle = col.surface;
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = b.sel ? col.accent : col.border;
      ctx.stroke();
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = col.text;
      ctx.font = `700 ${LABEL_FONT}`;
      ctx.fillText(b.name, r.x + 8, r.y + 15);
      if (b.type) {
        ctx.fillStyle = col.muted;
        ctx.font = `600 10.5px ${LABEL_FONT.split("px ")[1]}`;
        ctx.fillText(b.type, r.x + 8 + b.wName + 4, r.y + 15);
      }
      if (b.info) {
        ctx.fillStyle = col.muted;
        ctx.font = LABEL_FONT;
        ctx.fillText(b.info, r.x + 8, r.y + 29);
      }
    }
  },
});
