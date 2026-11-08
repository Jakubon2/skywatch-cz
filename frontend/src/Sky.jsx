// "Obloha" tab: "Pohled z okna". Point the phone at the sky and see which plane it is.
// With orientation sensors: a full-screen AR view over the live rear camera, labels placed by azimuth/elevation.
// Without sensors (desktop, denied): a top-down sky dome in the panel.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PLANE_SVG, altitudeHue, callsign } from "./aircraft.js";
import { useApp } from "./state.jsx";
import {
  altitudeM, angleBetween, angleDiff, cameraDir, extrapolate, groundDistance, lookAngles, pointing, project,
  rotateHeading, smoothRotation, timeToSet,
} from "./skymath.js";
import { useCamera, useObserver, useOrientation, useRoute } from "./skyhooks.js";
import "./Sky.css";

const MAX_KM = 120; // farther planes are specks on the horizon
const MIN_ELEVATION = 0.5; // degrees; below this the plane is behind the horizon (or hills)
const SET_ELEVATION = 2; // "zmizí za obzorem" once it sinks below this
const CAMERA_FOV_LONG = 67; // field of view across the long side of a typical phone main camera (≈26 mm equiv.)
const FOV_V = 60; // vertical field of view of the view without camera
const CATCH_DEG = 6; // a plane this close to the crosshair counts as "in the crosshair"
const SMOOTHING = 0.12; // per frame; lower = calmer but laggier
const POOR_COMPASS_DEG = 25; // iOS compass accuracy worse than this -> ask for a figure-eight
const FULL_LABELS = 6; // planes closest to the crosshair get the full label, the rest just a callsign

const RAD = Math.PI / 180;
const DIRS = ["S", "SV", "V", "JV", "J", "JZ", "Z", "SZ"];
const dirName = (az) => DIRS[Math.round(az / 45) % 8];
const fmt = (n, d = 0) => n.toLocaleString("cs-CZ", { maximumFractionDigits: d });
const fmtAlt = (m) => `${fmt(Math.round(m / 10) * 10)} m`;
const fmtKm = (m) => `${fmt(m / 1000, m < 10000 ? 1 : 0)} km`;
const PLANE_PATH = PLANE_SVG.match(/d="([^"]+)"/)[1];
const isPhone = () => typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;

// Every plane above the horizon within MAX_KM, moved forward by dead reckoning since the last snapshot.
function skyPlanes(aircraft, observer, seconds) {
  const out = [];
  for (const a of aircraft) {
    const alt = altitudeM(a);
    if (alt == null || a.lat == null) continue;
    const p = extrapolate(a, seconds);
    const dist = groundDistance(observer, p);
    if (dist > MAX_KM * 1000) continue;
    const look = lookAngles(observer, { lat: p.lat, lon: p.lon, alt });
    if (look.elevation < MIN_ELEVATION) continue;
    out.push({ a, lat: p.lat, lon: p.lon, alt, dist, ...look });
  }
  return out;
}

// "Zmizí za obzorem za ~X min": computed once per plane per snapshot, lazily (only for planes we show).
function useSetTimes(aircraft, observer, snapAt) {
  const cache = useRef({ list: null, key: null, map: new Map() });
  const key = observer ? `${observer.lat},${observer.lon},${observer.alt}` : null;
  if (cache.current.list !== aircraft || cache.current.key !== key) cache.current = { list: aircraft, key, map: new Map() };
  return (a) => {
    const map = cache.current.map;
    if (!map.has(a.hex)) {
      const r = observer && timeToSet(observer, a, { minElevation: SET_ELEVATION, maxDistM: MAX_KM * 1000 });
      map.set(a.hex, r && { ...r, at: snapAt + r.seconds * 1000 });
    }
    return map.get(a.hex);
  };
}

function setText(r, now, long = false) {
  if (!r) return null;
  if (r.seconds === Infinity) return long ? "Na obloze zůstane ještě přes hodinu" : "na obloze přes 1 h";
  const where = r.why === "range" ? "z dohledu" : "za obzorem";
  const min = (r.at - now) / 60000;
  if (min < 1) return long ? `Každou chvíli zmizí ${where}` : `brzy zmizí ${where}`;
  return long ? `Zmizí ${where} asi za ${fmt(min)} min` : `${where} za ~${fmt(min)} min`;
}

// Re-render on every animation frame (AR view) or once a second (dome, for the gliding planes).
function useClock(everyFrame, onFrame) {
  const [now, setNow] = useState(Date.now);
  const cb = useRef(onFrame);
  cb.current = onFrame;
  useEffect(() => {
    let id;
    if (everyFrame) {
      const loop = () => {
        cb.current?.();
        setNow(Date.now());
        id = requestAnimationFrame(loop);
      };
      loop();
      return () => cancelAnimationFrame(id);
    }
    id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [everyFrame]);
  return now;
}

function useSize(ref) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

const PlaneGlyph = ({ hue, rot = 0, size = 22 }) => (
  <svg className="sky-glyph" viewBox="0 0 24 24" width={size} height={size} style={{ "--h": hue ?? 0, transform: `rotate(${rot}deg)` }} aria-hidden="true">
    <path d={PLANE_PATH} />
  </svg>
);

// Direction from the observer to where the plane will be shortly: gives its heading on screen.
function dirTo(p, ahead) {
  const de = (ahead.lon - p.lon) * Math.cos(p.lat * RAD) * 111320;
  const dn = (ahead.lat - p.lat) * 111320;
  const v = [p.dir[0] * p.range + de, p.dir[1] * p.range + dn, p.dir[2] * p.range];
  const l = Math.hypot(...v) || 1;
  return v.map((c) => c / l);
}

const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/* ---------- AR view (sensors on), full screen ---------- */

function ArView({ planes, m, caught, nearest, pickedHex, camera, accuracy, offset, aligning, sets, now, card, hint, on }) {
  const ref = useRef(null);
  const { w, h } = useSize(ref);
  const vs = camera.on && camera.size;
  // Pixels per unit of tan(angle). With the camera, match the picture: object-fit: cover scales the video
  // by max(w/vw, h/vh), and the camera's long side spans CAMERA_FOV_LONG.
  const f = vs
    ? (Math.max(vs.w, vs.h) / 2 / Math.tan((CAMERA_FOV_LONG / 2) * RAD)) * Math.max(w / vs.w, h / vs.h)
    : h / 2 / Math.tan((FOV_V / 2) * RAD);
  const sa = screen.orientation?.angle ?? window.orientation ?? 0;
  const toScreen = (dir) => {
    const q = project(m, dir, sa);
    return { ...q, sx: w / 2 + q.x * f, sy: h / 2 - q.y * f };
  };
  const inView = (s, pad = 40) => s.front && s.sx > -pad && s.sx < w + pad && s.sy > -pad && s.sy < h + pad;
  const look = pointing(m);
  const ring = f * Math.tan(CATCH_DEG * RAD);

  const close = useRef(on.close);
  close.current = on.close;
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && close.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Horizon as a polyline of points every 5° around the current heading.
  const horizon = [];
  for (let k = -18; k <= 18; k++) {
    const az = (look.azimuth + k * 5) * RAD;
    const s = toScreen([Math.sin(az), Math.cos(az), 0]);
    if (s.front) horizon.push(`${s.sx.toFixed(1)},${s.sy.toFixed(1)}`);
  }
  const cardinals = DIRS.map((d, i) => ({ d, s: toScreen([Math.sin(i * 45 * RAD), Math.cos(i * 45 * RAD), 0]) })).filter((c) => inView(c.s, 0));

  // Planes in view, most important first; labels placed greedily so they don't overlap.
  const prio = (p) => (p.a.hex === caught?.a.hex ? -2 : p.a.hex === pickedHex ? -1 : p.off);
  const items = planes
    .map((p) => ({ p, s: toScreen(p.dir) }))
    .filter((it) => inView(it.s, -10)) // only planes whose centre is on screen; the rest get the edge arrow
    .sort((x, y) => prio(x.p) - prio(y.p));
  const cross = { x: w / 2 - ring, y: h / 2 - ring, w: ring * 2, h: ring * 2 };
  const boxes = [];
  for (const [i, it] of items.entries()) {
    const ahead = extrapolate({ ...it.p.a, lat: it.p.lat, lon: it.p.lon }, 30);
    const t = toScreen(dirTo(it.p, ahead));
    it.rot = Math.atan2(t.sx - it.s.sx, it.s.sy - t.sy) / RAD;
    for (const full of i < FULL_LABELS ? [true, false] : [false]) {
      const bw = full ? 158 : 88, bh = full ? 54 : 24;
      const right = it.s.sx + 18 + bw < w - 6;
      const x = right ? it.s.sx + 18 : it.s.sx - 18 - bw;
      const box = { x: Math.max(6, Math.min(w - 6 - bw, x)), y: it.s.sy - bh / 2, w: bw, h: bh };
      // Keep the crosshair clear, except for the plane that matters most (caught or tapped).
      if (boxes.some((b) => overlaps(b, box)) || (prio(it.p) >= 0 && overlaps(cross, box))) continue;
      boxes.push(box);
      it.label = { full, box };
      break;
    }
  }

  // Arrow at the edge towards the closest plane when it's out of view.
  let arrow = null;
  if (!caught && nearest && w) {
    const s = toScreen(nearest.dir);
    if (!inView(s, -10)) {
      const ang = Math.atan2(-s.y, s.x); // screen space, y down
      arrow = { x: w / 2 + Math.cos(ang) * (w / 2 - 34), y: h / 2 + Math.sin(ang) * (h / 2 - 150), rot: ang / RAD + 90 };
    }
  }

  const poor = accuracy != null && (accuracy < 0 || accuracy > POOR_COMPASS_DEG);
  const tap = (p) => (aligning ? on.align(p) : on.pick(p.a.hex));

  return createPortal(
    <div className={`sky-ar ${camera.on ? "sky-ar--camera" : ""}`} ref={ref} role="dialog" aria-label="Pohled z okna">
      {camera.on && <video ref={camera.videoRef} onLoadedMetadata={camera.onLoaded} className="sky-ar__video" playsInline muted autoPlay />}
      {w > 0 && (
        <>
          <svg className="sky-ar__grid" width={w} height={h} aria-hidden="true">
            {horizon.length > 1 && <polyline points={horizon.join(" ")} />}
            {cardinals.map((c) => (
              <text key={c.d} x={c.s.sx} y={c.s.sy - 8} className={c.d === "S" ? "is-north" : ""}>
                {c.d}
              </text>
            ))}
          </svg>
          {[...items].reverse().map(({ p, s, rot, label }) => {
            const isCaught = caught?.a.hex === p.a.hex;
            const isPicked = pickedHex === p.a.hex;
            const st = label?.full && setText(sets(p.a), now);
            return (
              <div key={p.a.hex} className={`sky-mark ${isCaught ? "is-caught" : ""} ${isPicked ? "is-picked" : ""}`}>
                <button className="sky-mark__plane" style={{ transform: `translate(${s.sx}px, ${s.sy}px)` }} onClick={() => tap(p)} aria-label={callsign(p.a)}>
                  <PlaneGlyph hue={altitudeHue(p.a)} rot={rot} size={isCaught || isPicked ? 30 : 24} />
                </button>
                {label && (
                  <button
                    className={`sky-tag ${label.full ? "" : "sky-tag--short"}`}
                    style={{ transform: `translate(${label.box.x}px, ${label.box.y}px)`, width: label.box.w }}
                    onClick={() => tap(p)}
                  >
                    <b>
                      {callsign(p.a)} {label.full && p.a.t && <span>{p.a.t}</span>}
                    </b>
                    {label.full && (
                      <>
                        <span>{fmtAlt(p.alt)} · {fmtKm(p.dist)}</span>
                        {st && <span className="sky-tag__set">{st}</span>}
                      </>
                    )}
                  </button>
                )}
              </div>
            );
          })}
          {arrow && (
            <div className="sky-arrow" style={{ transform: `translate(${arrow.x}px, ${arrow.y}px)` }}>
              <span style={{ transform: `rotate(${arrow.rot}deg)` }}>▲</span>
            </div>
          )}
          <div className={`sky-cross ${caught ? "is-caught" : ""} ${aligning ? "is-aligning" : ""}`} style={{ width: ring * 2, height: ring * 2 }} aria-hidden="true" />
        </>
      )}

      <div className="sky-ar__top">
        <div className="sky-ar__row">
          <span className="sky-chip sky-chip--glass">
            {dirName(look.azimuth)} {fmt(look.azimuth)}° · {fmt(Math.abs(look.elevation))}° {look.elevation >= 0 ? "nad obzorem" : "pod obzorem"}
          </span>
          <button className="sky-btn sky-btn--round" onClick={on.close} aria-label="Zavřít pohled z okna">✕</button>
        </div>
        {poor && (
          <span className="sky-chip sky-chip--warn">
            {accuracy < 0 ? "Kompas není zkalibrovaný" : `Kompas je nepřesný (±${fmt(accuracy)}°)`}: zamávej telefonem do osmičky
          </span>
        )}
        {camera.error && <span className="sky-chip sky-chip--glass sky-chip--error">{camera.error}</span>}
      </div>

      <div className="sky-ar__bottom">
        {aligning ? (
          <div className="sky-align">
            <span>Namiř křížek na skutečné letadlo a klepni na jeho popisek. Tím opravíš směr kompasu.</span>
            <span className="sky-align__btns">
              {offset !== 0 && <button className="sky-btn" onClick={on.resetAlign}>Vynulovat</button>}
              <button className="sky-btn" onClick={on.cancelAlign}>Zrušit</button>
            </span>
          </div>
        ) : (
          card || <p className="sky-ar__hint">{hint}</p>
        )}
        <div className="sky-ar__controls">
          <button className={`sky-btn ${camera.on ? "is-on" : ""}`} onClick={camera.toggle} aria-pressed={camera.on}>
            {camera.on ? "Kamera zap." : "Kamera vyp."}
          </button>
          <button className={`sky-btn ${aligning ? "is-on" : ""}`} onClick={on.startAlign} aria-pressed={aligning}>
            {offset ? `Zarovnáno ${offset > 0 ? "+" : "−"}${fmt(Math.abs(offset))}°` : "Zarovnat"}
          </button>
        </div>
        <p className="sky-ar__credit">Data: adsb.lol (ODbL) · Obraz z kamery se nikam neposílá ani neukládá.</p>
      </div>
    </div>,
    document.body,
  );
}

/* ---------- Sky dome (no sensors) ---------- */

const DOME_R = 92;
const domeXY = (az, el) => {
  const r = ((90 - Math.max(0, el)) / 90) * DOME_R;
  return [r * Math.sin(az * RAD), -r * Math.cos(az * RAD)];
};

function Dome({ planes, picked, onPick }) {
  const sorted = [...planes].sort((p, q) => p.elevation - q.elevation); // higher planes drawn on top
  const ticks = Array.from({ length: 36 }, (_, i) => i * 10);
  return (
    <div className="sky-dome">
      <svg viewBox="-112 -112 224 224" role="img" aria-label="Obloha shora: střed je přímo nad tebou, okraj je obzor, sever nahoře">
        <defs>
          <radialGradient id="sky-dome-fill">
            <stop offset="0" className="sky-dome__zenith" />
            <stop offset="1" className="sky-dome__horizon" />
          </radialGradient>
        </defs>
        <circle r={DOME_R} fill="url(#sky-dome-fill)" className="sky-dome__disc" />
        {[30, 60].map((el) => (
          <circle key={el} r={((90 - el) / 90) * DOME_R} className="sky-dome__ring" />
        ))}
        <path d={`M0 ${-DOME_R}V${DOME_R}M${-DOME_R} 0H${DOME_R}`} className="sky-dome__ring" />
        {ticks.map((az) => {
          const [x1, y1] = domeXY(az, 0);
          const [x2, y2] = domeXY(az, az % 30 ? 3 : 6);
          return <line key={az} x1={x1} y1={y1} x2={x2} y2={y2} className="sky-dome__tick" />;
        })}
        {["S", "V", "J", "Z"].map((d, i) => {
          const [x, y] = domeXY(i * 90, -12).map((c) => c * 1.11);
          return (
            <text key={d} x={x} y={y} className={`sky-dome__dir ${d === "S" ? "is-north" : ""}`}>
              {d}
            </text>
          );
        })}
        {[30, 60].map((el) => {
          const [x, y] = domeXY(45, el);
          return (
            <text key={el} x={x + 3} y={y - 3} className="sky-dome__deg">
              {el}°
            </text>
          );
        })}
        <circle r="2.6" className="sky-dome__me" />

        {sorted.map((p) => {
          const [x, y] = domeXY(p.azimuth, p.elevation);
          const sel = picked?.a.hex === p.a.hex;
          return (
            <g
              key={p.a.hex}
              transform={`translate(${x.toFixed(2)} ${y.toFixed(2)})`}
              className={`sky-dome__plane ${sel ? "is-picked" : ""}`}
              style={{ "--h": altitudeHue(p.a) ?? 0 }}
              onClick={() => onPick(p.a.hex)}
            >
              <title>{callsign(p.a)}</title>
              <circle r="9" className="sky-dome__hit" />
              {sel && <circle r="8.5" className="sky-dome__sel" />}
              <path d={PLANE_PATH} transform={`rotate(${p.a.track ?? 0}) scale(${sel ? 0.5 : 0.4}) translate(-12 -12)`} />
              {sel && (
                <text y={y < -DOME_R * 0.7 ? 14 : -12} className="sky-dome__label">
                  {callsign(p.a)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ---------- Card for the plane in the crosshair / picked ---------- */

function routeText(route) {
  if (!route || route === "loading") return null;
  const code = (ap) => ap?.iata || ap?.icao || "?";
  const place = (ap) => ap?.location || ap?.name || code(ap);
  return {
    codes: `${code(route.origin)} → ${code(route.destination)}`,
    places: `${place(route.origin)} → ${place(route.destination)}`,
    unsure: !route.plausible,
  };
}

function PlaneCard({ p, kicker, live, sets, compact, onOpen }) {
  const flight = (p.a.flight || "").trim().toUpperCase();
  const route = useRoute(flight);
  const r = routeText(route);
  const hue = altitudeHue(p.a);
  return (
    <button className={`sky-card ${live ? "is-live" : ""} ${compact ? "sky-card--compact" : ""}`} onClick={onOpen}>
      <span className="sky-card__head">
        <span className="sky-card__icon" style={{ "--h": hue ?? 0 }}>
          <PlaneGlyph hue={hue} rot={p.a.track ?? 0} />
        </span>
        <span className="sky-card__title">
          <span className="sky-card__kicker">{kicker}</span>
          <span className="sky-card__name">
            {callsign(p.a)} {p.a.t && <span className="sky-card__type">{p.a.t}</span>}
          </span>
          <span className="sky-card__route">
            {route === "loading" ? "Hledám trasu…" : r ? (
              <>
                <b>{r.codes}</b> {r.places !== r.codes && <span>{r.places}</span>}
                {r.unsure && <em> · trasa nejistá</em>}
              </>
            ) : flight ? "Trasa neznámá" : "Bez volacího znaku"}
          </span>
        </span>
        <span className="sky-card__go" aria-hidden="true">›</span>
      </span>
      {compact ? (
        <span className="sky-card__line">
          {fmtAlt(p.alt)} · {fmtKm(p.dist)} · {fmt(p.elevation)}° nad obzorem
        </span>
      ) : (
        <span className="sky-card__stats">
          <span><small>Výška</small>{fmtAlt(p.alt)}</span>
          <span><small>Vzdálenost</small>{fmtKm(p.dist)}</span>
          <span><small>Nad obzorem</small>{fmt(p.elevation)}°</span>
          <span><small>Směr</small>{dirName(p.azimuth)} {fmt(p.azimuth)}°</span>
        </span>
      )}
      {sets && <span className="sky-card__sets">{sets}</span>}
    </button>
  );
}

/* ---------- Tab ---------- */

const SENSOR_NOTES = {
  denied: "Přístup k pohybu a orientaci je zakázaný. Načti stránku znovu a při dotazu ho povol.",
  nodata: "Zařízení neposílá data o orientaci. Na počítači to nejde, zkus to na telefonu (přes https).",
  relative: "Prohlížeč nehlásí, kde je sever, takže by letadla neseděla. Zkus Chrome nebo Safari.",
  unsupported: "Tenhle prohlížeč orientaci telefonu nepodporuje.",
};

const GEO_NOTES = {
  denied: "Přístup k poloze je zakázaný, počítám s domovem.",
  error: "Polohu se nepodařilo zjistit, počítám s domovem.",
  unsupported: "Tenhle prohlížeč polohu neumí.",
};

export default function Sky() {
  const { aircraft, status, home, select, flyTo, setView } = useApp();
  const { observer, geo, locate } = useObserver(home);
  const sensor = useOrientation();
  const camera = useCamera();
  const on = sensor.status === "on";
  const [pickedHex, setPickedHex] = useState(null);
  const [offset, setOffset] = useState(0); // "Zarovnat": manual compass correction in degrees, this visit only
  const [aligning, setAligning] = useState(false);
  const [phone] = useState(isPhone);

  // Smoothed orientation, advanced once per frame, then the manual correction on top.
  const smooth = useRef(null);
  const now = useClock(on, () => {
    if (sensor.matrix.current) smooth.current = smoothRotation(smooth.current, sensor.matrix.current, SMOOTHING);
  });
  const m = on && smooth.current ? rotateHeading(smooth.current, offset) : null;

  // When did this snapshot arrive? Dead reckoning runs from there (capped so stale data doesn't fly off).
  const snap = useRef({ list: null, at: 0 });
  if (snap.current.list !== aircraft) snap.current = { list: aircraft, at: now };
  const planes = observer ? skyPlanes(aircraft, observer, Math.min(15, Math.max(0, (now - snap.current.at) / 1000))) : [];
  const sets = useSetTimes(aircraft, observer, snap.current.at);

  // Crosshair: the plane closest to where the camera points, with a little hysteresis against flicker.
  let nearest = null;
  if (m) {
    const cam = cameraDir(m);
    for (const p of planes) {
      p.off = angleBetween(cam, p.dir);
      if (!nearest || p.off < nearest.off) nearest = p;
    }
  }
  const lastCaught = useRef(null);
  const prev = m && lastCaught.current ? planes.find((p) => p.a.hex === lastCaught.current) : null;
  const caught = prev && prev.off <= CATCH_DEG * 1.4 ? prev : nearest && nearest.off <= CATCH_DEG ? nearest : null;
  const caughtHex = caught?.a.hex ?? null;

  useEffect(() => {
    if (!caughtHex) return;
    lastCaught.current = caughtHex;
    setPickedHex(null); // the crosshair wins over an earlier tap
    navigator.vibrate?.(12); // light tick; silently unsupported on iOS
  }, [caughtHex]);

  const stop = () => {
    camera.stop();
    sensor.stop();
    smooth.current = null;
    lastCaught.current = null;
    setAligning(false);
  };
  const start = (withCamera) => {
    // One tap starts everything: iOS needs the orientation permission and the camera inside a user gesture.
    sensor.start();
    if (withCamera) camera.start();
    if (observer?.source !== "gps") locate();
  };
  const handlers = {
    close: stop,
    pick: (hex) => setPickedHex(hex),
    // The real plane is in the crosshair: make the camera heading equal to its computed azimuth.
    align: (p) => {
      setOffset(Math.round(angleDiff(pointing(smooth.current).azimuth, p.azimuth)));
      setAligning(false);
    },
    startAlign: () => setAligning(true),
    cancelAlign: () => setAligning(false),
    resetAlign: () => {
      setOffset(0);
      setAligning(false);
    },
  };

  const open = (p) => {
    select(p.a.hex); // opens the detail; this tab unmounts, which stops the sensors and the camera
    flyTo(p.lat, p.lon, 9);
  };

  if (!observer)
    return (
      <div className="empty sky-empty">
        <div className="empty__icon" aria-hidden="true">✦</div>
        <p className="empty__title">Co je to za letadlo?</p>
        <p>Potřebuju vědět, odkud se díváš. Povol polohu, nebo si nastav domov.</p>
        <div className="sky-empty__actions">
          <button className="btn btn--primary" onClick={locate} disabled={geo === "locating"}>
            {geo === "locating" ? "Zjišťuji polohu…" : "Použít moji polohu"}
          </button>
          <button className="btn btn--ghost" onClick={() => setView("near")}>Nastavit domov</button>
        </div>
        {GEO_NOTES[geo] && <p className="form-note form-note--error">{GEO_NOTES[geo].replace(", počítám s domovem", "")}</p>}
      </div>
    );

  // Card: in AR the plane in the crosshair, else a tapped one, else the last one caught (so you can lower
  // the phone and tap it). On the dome the tapped one, else the highest.
  const byHex = (hex) => hex && planes.find((p) => p.a.hex === hex);
  let card = null;
  if (on) {
    const picked = byHex(pickedHex);
    const last = byHex(lastCaught.current);
    if (caught) card = { p: caught, kicker: "V záměrném kříži", live: true };
    else if (picked) card = { p: picked, kicker: "Vybrané letadlo" };
    else if (last) card = { p: last, kicker: "Naposledy v kříži" };
  } else {
    const picked = byHex(pickedHex);
    const top = planes.reduce((best, p) => (!best || p.elevation > best.elevation ? p : best), null);
    if (picked || top) card = { p: picked || top, kicker: picked ? "Vybrané letadlo" : "Nejvýš na obloze" };
  }
  const cardEl = card && (
    <PlaneCard key={card.p.a.hex} {...card} compact={on} sets={setText(sets(card.p.a), now, true)} onOpen={() => open(card.p)} />
  );

  const hint = !aircraft.length && status !== "live"
    ? status === "offline" ? "Letadla se nepodařilo načíst, zkouším to znovu." : "Načítám letadla…"
    : on
    ? nearest
      ? `Namiř křížek na letadlo. Nejbližší je ${callsign(nearest.a)}, ${fmt(nearest.off)}° od křížku.`
      : "Nad obzorem teď nic neletí."
    : `Do ${MAX_KM} km teď nad obzorem nic neletí.`;

  return (
    <div className="sky">
      <div className="sky__bar">
        <span className="sky-chip">
          <span className={`sky-chip__dot ${observer.source === "gps" ? "is-gps" : ""}`} />
          {observer.source === "gps"
            ? `Tvoje poloha${observer.accuracy ? ` ±${fmt(observer.accuracy)} m` : ""}`
            : `Domov · ${observer.label}`}
        </span>
        {observer.source !== "gps" && geo !== "denied" && geo !== "unsupported" && (
          <button className="btn btn--small" onClick={locate} disabled={geo === "locating"}>
            {geo === "locating" ? "Zjišťuji…" : "Použít GPS"}
          </button>
        )}
      </div>
      {GEO_NOTES[geo] && <p className="form-note">{GEO_NOTES[geo]}</p>}

      {!on && phone && (
        <div className="sky-start">
          <div className="sky-start__text">
            <b>Pohled z okna</b>
            <span>Namiř telefon na oblohu a uvidíš popisky letadel přímo v obraze kamery. Obraz zůstává v telefonu, nic se nenahrává ani neodesílá.</span>
          </div>
          <div className="sky-start__btns">
            <button className="btn btn--primary" onClick={() => start(true)} disabled={sensor.status === "asking"}>
              {sensor.status === "asking" ? "Spouštím…" : "Spustit s kamerou"}
            </button>
            <button className="btn btn--ghost" onClick={() => start(false)} disabled={sensor.status === "asking"}>
              Bez kamery
            </button>
          </div>
          {SENSOR_NOTES[sensor.status] && <p className="form-note form-note--error">{SENSOR_NOTES[sensor.status]}</p>}
        </div>
      )}

      {m && (
        <ArView
          planes={planes} m={m} caught={caught} nearest={nearest} pickedHex={pickedHex} camera={camera}
          accuracy={sensor.accuracy} offset={offset} aligning={aligning} sets={sets} now={now}
          card={cardEl} hint={hint} on={handlers}
        />
      )}

      <Dome planes={planes} picked={card?.p} onPick={setPickedHex} />
      <p className="sky__hint">
        {planes.length ? `${planes.length} letadel nad obzorem do ${MAX_KM} km. ` : ""}Střed je přímo nad tebou, okraj je obzor.
        {!phone && " Na telefonu je pohled z okna: popisky letadel přímo v obraze kamery."}
      </p>

      {on ? null : cardEl || (!planes.length && <p className="sky__hint">{hint}</p>)}

      <p className="sky__note">
        Přesnost závisí na kompasu telefonu (obvykle ±5–15°, u kovu a magnetů víc), nesedí-li to, zamávej telefonem do
        osmičky nebo použij Zarovnat. Výška letadel je tlaková, skutečná se liší o desítky až stovky metrů. Čas do zmizení
        je odhad pro let rovně stejnou rychlostí.
      </p>
    </div>
  );
}
