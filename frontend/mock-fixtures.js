// TEMPORARY dev-only mock: serves recorded fixtures as /api/*. Remove before finishing.
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const FIELDS = ["hex", "flight", "r", "t", "lat", "lon", "alt_baro", "gs", "track",
  "baro_rate", "squawk", "category", "dbFlags"];

export default function mockFixtures() {
  const dir = path.resolve(__dirname, "../fixtures");
  const file = fs.readdirSync(dir).filter((f) => f.endsWith(".jsonl.gz")).sort().pop();
  const raw = zlib.gunzipSync(fs.readFileSync(path.join(dir, file)), {
    finishFlush: zlib.constants.Z_SYNC_FLUSH,
  }).toString();
  const snaps = raw.split("\n").filter((l) => l.endsWith("}")).map((l) => JSON.parse(l));
  const t0 = Date.now();
  const current = () => snaps[Math.floor((Date.now() - t0) / 10000) % snaps.length];

  return {
    name: "mock-fixtures",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const s = current();
        const ac = s.ac.filter((a) => a.lat != null);
        let body;
        if (req.url.startsWith("/api/aircraft")) {
          body = { now: s.now, aircraft: ac.map((a) => Object.fromEntries(FIELDS.filter((k) => k in a).map((k) => [k, a[k]]))) };
        } else if (req.url.startsWith("/api/health")) {
          body = { ok: true, snapshot_ms: s.now, aircraft: ac.length, tracks: ac.length };
        } else return next();
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(body));
      });
    },
  };
}
