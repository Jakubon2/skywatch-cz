// Hand-checked cases for skymath.js. Run: node frontend/src/skymath.test.js
import assert from "node:assert/strict";
import {
  altitudeM, angleDiff, compassHeadingFor, destination, dirFromAngles, extrapolate, groundDistance,
  lookAngles, pointing, project, rotateHeading, rotationMatrix, smoothRotation, timeToSet,
} from "./skymath.js";

let failed = 0;
const near = (got, want, tol, msg) => assert.ok(Math.abs(got - want) <= tol, `${msg}: got ${got}, want ${want} ±${tol}`);
const azNear = (got, want, tol, msg) => near(Math.abs(angleDiff(got, want)), 0, tol, msg);
function test(name, fn) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${name}\n     ${e.message}`);
  }
}

const obs = { lat: 50.0755, lon: 14.4378, alt: 0 }; // Prague, sea level for easy numbers
const at = (bearing, km, altM) => ({ ...destination(obs.lat, obs.lon, bearing, km * 1000), alt: altM });

test("due north, 10 km away, 10 000 m up -> az 0°, el ≈45°", () => {
  const r = lookAngles(obs, at(0, 10, 10000));
  azNear(r.azimuth, 0, 0.05, "azimuth");
  near(r.elevation, 45, 0.1, "elevation"); // curvature drop at 10 km is only ~8 m
  near(r.range, Math.hypot(10000, 10000), 30, "range");
});

test("due east -> az 90°, south-west -> az 225°", () => {
  azNear(lookAngles(obs, at(90, 20, 3000)).azimuth, 90, 0.05, "east");
  azNear(lookAngles(obs, at(225, 20, 3000)).azimuth, 225, 0.1, "south-west");
});

test("straight overhead -> el 90°", () => {
  near(lookAngles(obs, { lat: obs.lat, lon: obs.lon, alt: 11000 }).elevation, 90, 0.01, "elevation");
});

test("curvature: 300 km away at 10 km -> el ≈0.56° (flat earth would say 1.9°)", () => {
  // atan(10/300) - 300/(2·6371) rad = 1.909° - 1.349°
  near(lookAngles(obs, at(0, 300, 10000)).elevation, 0.56, 0.08, "elevation");
});

test("same height, 50 km away -> below the horizon", () => {
  assert.ok(lookAngles(obs, at(180, 50, 0)).elevation < 0);
});

test("ground distance (Prague -> Brno ≈ 185 km)", () => {
  near(groundDistance(obs, { lat: 49.1951, lon: 16.6068 }) / 1000, 185, 3, "km");
});

test("alt_baro ft -> m, ground -> fallback", () => {
  near(altitudeM({ alt_baro: 10000 }), 3048, 0.01, "m");
  assert.equal(altitudeM({ alt_baro: "ground" }, 250), 250);
  assert.equal(altitudeM({}), null);
});

test("dead reckoning: 480 kt east for 10 s ≈ 2.47 km", () => {
  const a = { lat: obs.lat, lon: obs.lon, gs: 480, track: 90, alt_baro: 35000 };
  near(groundDistance(a, extrapolate(a, 10)), 2469, 5, "m");
});

test("phone flat, top to north -> camera points down", () => {
  const m = rotationMatrix(0, 0, 0);
  near(pointing(m).elevation, -90, 0.01, "elevation");
  azNear(compassHeadingFor(m), 0, 0.01, "iOS-style heading (top edge)");
});

test("phone upright, facing north -> camera az 0°, el 0°", () => {
  const p = pointing(rotationMatrix(0, 90, 0));
  azNear(p.azimuth, 0, 0.01, "azimuth");
  near(p.elevation, 0, 0.01, "elevation");
});

test("phone upright, turned left (alpha 90) -> faces west (270°)", () => {
  const m = rotationMatrix(90, 90, 0);
  azNear(pointing(m).azimuth, 270, 0.01, "azimuth");
  azNear(compassHeadingFor(m), 270, 0.01, "iOS-style heading (camera)");
});

test("phone tilted up 45° facing north -> camera el 45°", () => {
  near(pointing(rotationMatrix(0, 135, 0)).elevation, 45, 0.01, "elevation");
});

test("projection: centre, right, up, behind", () => {
  const m = rotationMatrix(0, 90, 0); // upright, facing north
  const c = project(m, dirFromAngles(0, 0));
  assert.ok(c.front);
  near(c.x, 0, 1e-9, "centre x");
  near(c.y, 0, 1e-9, "centre y");
  const r = project(m, dirFromAngles(10, 0));
  near(r.x, Math.tan((10 * Math.PI) / 180), 1e-6, "10° right");
  near(r.angle, 10, 1e-6, "angle off-axis");
  assert.ok(project(m, dirFromAngles(0, 10)).y > 0, "10° up is above the centre");
  assert.equal(project(m, dirFromAngles(180, 0)).front, false, "behind the phone");
});

test("projection in landscape (screen turned 90°): up in the world is up on screen", () => {
  // Phone held up facing north, then turned left onto its side: right edge up, top edge west.
  // Columns = device x, y, z in ENU: x = up, y = west, z = x × y = south.
  const m = [
    [0, -1, 0],
    [0, 0, -1],
    [1, 0, 0],
  ];
  azNear(pointing(m).azimuth, 0, 0.01, "still facing north");
  const p = project(m, dirFromAngles(0, 10), 90);
  near(p.x, 0, 1e-6, "no sideways offset");
  assert.ok(p.y > 0, "above the centre");
});

test("smoothing moves part of the way and stays a rotation", () => {
  const s = smoothRotation(rotationMatrix(0, 90, 0), rotationMatrix(20, 90, 0), 0.5);
  azNear(pointing(s).azimuth, 350, 0.5, "halfway between 0° and 340°");
  for (let i = 0; i < 3; i++) near(Math.hypot(s[0][i], s[1][i], s[2][i]), 1, 1e-9, `axis ${i} unit`);
});

test("Zarovnat: rotateHeading +30° turns a north-facing view to 30°, elevation unchanged", () => {
  const m = rotateHeading(rotationMatrix(0, 120, 0), 30);
  azNear(pointing(m).azimuth, 30, 0.01, "azimuth");
  near(pointing(m).elevation, 30, 0.01, "elevation");
});

// A plane at `km` along `bearing`, flying `track` at `gs` knots, `ft` feet.
const plane = (bearing, km, ft, track, gs, extra = {}) => {
  const p = destination(obs.lat, obs.lon, bearing, km * 1000);
  return { lat: p.lat, lon: p.lon, alt_baro: ft, track, gs, ...extra };
};
const KM_S_450KT = (450 * 1.852) / 3600;

test("sets: 50 km north at 10 km, flying away north at 450 kt -> el 2° at ≈198 km, ≈11 min", () => {
  // Hand: 10 000/d − d/(2·6 371 000) = tan 2° = 0.0349 -> d ≈ 198 km; (198 − 50) km / 0.2315 km/s ≈ 640 s.
  const r = timeToSet(obs, plane(0, 50, 10000 / 0.3048, 0, 450));
  assert.equal(r.why, "horizon");
  near(r.seconds, (198 - 50) / KM_S_450KT, 20, "seconds");
});

test("sets: flying towards you first passes overhead, so it sets later than one flying away", () => {
  const away = timeToSet(obs, plane(0, 50, 32800, 0, 450)).seconds;
  const towards = timeToSet(obs, plane(0, 50, 32800, 180, 450)).seconds; // passes overhead, then 198 km south
  near(towards, (50 + 198) / KM_S_450KT, 25, "towards");
  assert.ok(towards > away);
});

test("sets: leaving the range first -> why 'range'", () => {
  const r = timeToSet(obs, plane(0, 50, 32800, 0, 450), { maxDistM: 120000 });
  assert.equal(r.why, "range");
  near(r.seconds, 70 / KM_S_450KT, 3, "seconds to 120 km");
});

test("sets: descending at 1 500 ft/min drops out sooner than level flight", () => {
  const level = timeToSet(obs, plane(90, 30, 10000, 90, 250)).seconds;
  const down = timeToSet(obs, plane(90, 30, 10000, 90, 250, { baro_rate: -1500 })).seconds;
  assert.ok(down < level, `${down} < ${level}`);
});

test("sets: already below 2° -> 0; no speed -> null; circling overhead slowly -> Infinity", () => {
  assert.equal(timeToSet(obs, plane(0, 150, 10000, 0, 450)).seconds, 0);
  assert.equal(timeToSet(obs, plane(0, 10, 10000, 0, 0)), null);
  assert.equal(timeToSet(obs, { ...obs, alt_baro: 3000, track: 0, gs: 1 }, { limitS: 600 }).seconds, Infinity);
});

if (failed) {
  console.log(`\n${failed} failed`);
  process.exit(1);
}
console.log("\nall passed");
