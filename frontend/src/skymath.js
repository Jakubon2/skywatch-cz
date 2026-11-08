// Pure geometry for the "Obloha" tab: where a plane is in the sky as seen by an observer,
// and where that direction lands on a phone screen. No DOM, no React: run `node src/skymath.test.js`.
//
// World frame is local ENU at the observer: x = east, y = north, z = up (same as the W3C
// DeviceOrientation "earth frame"). Angles in degrees unless a name says otherwise.

const RAD = Math.PI / 180;
const WGS84_A = 6378137;
const WGS84_E2 = 6.69437999014e-3;
const EARTH_R = 6371000; // mean radius, for distances and dead reckoning
const FT = 0.3048;

export const norm360 = (d) => ((d % 360) + 360) % 360;

// Pressure altitude (ft, or "ground") -> metres above sea level, roughly.
// alt_baro is referenced to 1013.25 hPa, not the real sea-level pressure: true altitude differs by
// about 8–9 m per hPa (typically ±100–300 m). Plenty for pointing a phone; don't use it for more.
export function altitudeM(a, groundM = null) {
  if (a.alt_baro === "ground") return groundM;
  return typeof a.alt_baro === "number" ? a.alt_baro * FT : null;
}

function ecef(lat, lon, h) {
  const sl = Math.sin(lat * RAD), cl = Math.cos(lat * RAD);
  const n = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
  return [(n + h) * cl * Math.cos(lon * RAD), (n + h) * cl * Math.sin(lon * RAD), (n * (1 - WGS84_E2) + h) * sl];
}

// Vector from observer to target in the observer's ENU frame (metres). Accounts for Earth's curvature,
// so far planes sink towards (and below) the horizon as they should.
export function enu(obs, tgt) {
  const [x0, y0, z0] = ecef(obs.lat, obs.lon, obs.alt ?? 0);
  const [x1, y1, z1] = ecef(tgt.lat, tgt.lon, tgt.alt ?? 0);
  const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0;
  const sl = Math.sin(obs.lat * RAD), cl = Math.cos(obs.lat * RAD);
  const so = Math.sin(obs.lon * RAD), co = Math.cos(obs.lon * RAD);
  return [
    -so * dx + co * dy,
    -sl * co * dx - sl * so * dy + cl * dz,
    cl * co * dx + cl * so * dy + sl * dz,
  ];
}

// Great-circle ground distance (m).
export function groundDistance(a, b) {
  const dLat = (b.lat - a.lat) * RAD, dLon = (b.lon - a.lon) * RAD;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(h)));
}

// Azimuth (0 = north, clockwise), elevation above the horizon, slant range (m) and the unit direction vector.
export function lookAngles(obs, tgt) {
  const v = enu(obs, tgt);
  const range = Math.hypot(...v);
  if (range < 1) return { azimuth: 0, elevation: 90, range: 0, dir: [0, 0, 1] };
  return {
    azimuth: norm360(Math.atan2(v[0], v[1]) / RAD),
    elevation: Math.asin(v[2] / range) / RAD,
    range,
    dir: v.map((c) => c / range),
  };
}

export function dirFromAngles(azimuth, elevation) {
  const ce = Math.cos(elevation * RAD);
  return [ce * Math.sin(azimuth * RAD), ce * Math.cos(azimuth * RAD), Math.sin(elevation * RAD)];
}

// Point at `dist` metres along `bearing` from (lat, lon), on a sphere.
export function destination(lat, lon, bearing, dist) {
  const d = dist / EARTH_R, b = bearing * RAD, p1 = lat * RAD, l1 = lon * RAD;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return { lat: p2 / RAD, lon: l2 / RAD };
}

// Dead reckoning between 10 s snapshots, so planes glide instead of jumping. gs in knots.
export function extrapolate(a, seconds) {
  if (a.gs == null || a.track == null || a.alt_baro === "ground" || seconds <= 0) return a;
  const p = destination(a.lat, a.lon, a.track, a.gs * 0.514444 * seconds);
  return { ...a, lat: p.lat, lon: p.lon };
}

// Device orientation (alpha, beta, gamma, degrees) -> rotation matrix whose columns are the device axes
// (x = right edge, y = top edge, z = out of the screen) in the ENU frame. Formula from the W3C spec.
// With absolute alpha (Android) the frame is true ENU; with relative alpha (iOS) add the compass offset first.
export function rotationMatrix(alpha, beta, gamma) {
  const cX = Math.cos(beta * RAD), sX = Math.sin(beta * RAD);
  const cY = Math.cos(gamma * RAD), sY = Math.sin(gamma * RAD);
  const cZ = Math.cos(alpha * RAD), sZ = Math.sin(alpha * RAD);
  return [
    [cZ * cY - sZ * sX * sY, -cX * sZ, cY * sZ * sX + cZ * sY],
    [cY * sZ + cZ * sX * sY, cZ * cX, sZ * sY - cZ * cY * sX],
    [-cX * sY, sX, cX * cY],
  ];
}

const col = (m, i) => [m[0][i], m[1][i], m[2][i]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const unit = (v) => {
  const l = Math.hypot(...v) || 1;
  return v.map((c) => c / l);
};
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

// The rear camera looks along the device's -z axis.
export const cameraDir = (m) => col(m, 2).map((c) => -c);

export function headingOf(v) {
  return norm360(Math.atan2(v[0], v[1]) / RAD);
}

// Where the phone points: azimuth and elevation of the rear camera.
export function pointing(m) {
  const c = cameraDir(m);
  return { azimuth: headingOf(c), elevation: Math.asin(Math.max(-1, Math.min(1, c[2]))) / RAD };
}

// The heading iOS reports in webkitCompassHeading for this device pose: the top edge when the phone lies
// flat, the camera direction when it is held up. null in between, where it's ambiguous (don't calibrate then).
export function compassHeadingFor(m) {
  const el = pointing(m).elevation;
  if (Math.abs(el) < 50) return headingOf(cameraDir(m));
  if (Math.abs(el) > 70) return headingOf(col(m, 1));
  return null;
}

// Shortest signed difference b - a in degrees, in (-180, 180].
export function angleDiff(a, b) {
  const d = norm360(b - a);
  return d > 180 ? d - 360 : d;
}

// Exponential smoothing of a rotation: blend each axis, then re-orthonormalise.
export function smoothRotation(prev, next, k) {
  if (!prev) return next;
  const mix = (i) => col(prev, i).map((c, j) => c + (col(next, i)[j] - c) * k);
  const y = unit(mix(1));
  const x = unit(cross(y, mix(2)));
  const z = cross(x, y);
  return [0, 1, 2].map((r) => [x[r], y[r], z[r]]);
}

// Project a world direction onto the screen. Returns screen-plane offsets in units of the focal length
// (multiply by f = (viewHeight / 2) / tan(fovV / 2) to get pixels; y grows upwards) and `angle`, the angle
// between the camera axis and the direction. `front` is false when it is behind the phone.
// `screenAngle` is screen.orientation.angle (0 portrait, 90 landscape after turning the phone left).
export function project(m, dir, screenAngle = 0) {
  const dx = dot(dir, col(m, 0)), dy = dot(dir, col(m, 1)), dz = -dot(dir, col(m, 2));
  const angle = Math.acos(Math.max(-1, Math.min(1, dz))) / RAD;
  const t = screenAngle * RAD;
  const sx = dx * Math.cos(t) - dy * Math.sin(t), sy = dx * Math.sin(t) + dy * Math.cos(t);
  if (dz <= 1e-6) return { front: false, x: sx, y: sy, angle };
  return { front: true, x: sx / dz, y: sy / dz, angle };
}

// Angle between two unit vectors (degrees).
export const angleBetween = (a, b) => Math.acos(Math.max(-1, Math.min(1, dot(a, b)))) / RAD;

// Manual compass correction ("Zarovnat"): turn the frame about the vertical so every heading grows by `deg`.
export function rotateHeading(m, deg) {
  if (!deg) return m;
  const c = Math.cos(-deg * RAD), s = Math.sin(-deg * RAD);
  return [m[0].map((v, i) => c * v - s * m[1][i]), m[0].map((v, i) => s * v + c * m[1][i]), m[2]];
}

const MAX_ALT_M = 13000;

// When does the plane disappear? Dead-reckons along its track at constant ground speed (and vertical rate,
// clamped to 0–13 km) until its elevation drops below `minElevation` or it flies beyond `maxDistM`.
// Returns { seconds, why: "horizon" | "range" } (seconds 0 = already gone), { seconds: Infinity } when it
// stays longer than `limitS`, or null without the data to tell. A straight-line guess: planes turn.
export function timeToSet(obs, a, { minElevation = 2, maxDistM = Infinity, stepS = 20, limitS = 3600 } = {}) {
  const alt0 = altitudeM(a);
  if (alt0 == null || a.lat == null) return null;
  const vz = typeof a.baro_rate === "number" ? (a.baro_rate * FT) / 60 : 0;
  const gone = (t) => {
    const p = extrapolate(a, t);
    if (groundDistance(obs, p) > maxDistM) return "range";
    const alt = Math.max(0, Math.min(MAX_ALT_M, alt0 + vz * t));
    return lookAngles(obs, { lat: p.lat, lon: p.lon, alt }).elevation < minElevation ? "horizon" : null;
  };
  const now = gone(0);
  if (now) return { seconds: 0, why: now };
  if (!(a.gs > 0) || a.track == null) return null;
  let lo = 0;
  for (let t = stepS; t <= limitS; t += stepS) {
    if (!gone(t)) {
      lo = t;
      continue;
    }
    let hi = t;
    while (hi - lo > 1) {
      const mid = (lo + hi) / 2;
      if (gone(mid)) hi = mid;
      else lo = mid;
    }
    return { seconds: Math.round(hi), why: gone(hi) };
  }
  return { seconds: Infinity, why: null };
}
