// Event display helpers shared by the feed, toasts and the share image.

const num = (n) => Math.round(n).toLocaleString("cs-CZ");

// hue: colour of the type icon; label: Czech type name; icon: 24x24 stroke path.
export const EVENT_TYPES = {
  emergency: { hue: 0, label: "Nouzová situace", icon: "M12 3.5 2.5 20h19zM12 10v4.5M12 17.5h.01" },
  holding: { hue: 205, label: "Krouží v holdingu", icon: "M7.5 7.5h9a4.5 4.5 0 0 1 0 9h-9a4.5 4.5 0 0 1 0-9zM14 5l2.5 2.5L14 10" },
  go_around: { hue: 35, label: "Pravděpodobné nepovedené přistání", icon: "M3.5 19.5c5 0 7-2.5 9-7s4-7 8-7M15.5 5.5h5v5" },
  interesting: { hue: 255, label: "Zajímavé letadlo", icon: "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" },
  rapid_descent: { hue: 18, label: "Rychlé klesání", icon: "M12 4v15M6 13l6 6 6-6" },
  return_or_diversion: { hue: 285, label: "Pravděpodobně se vrací nebo odklání", icon: "M9 13.5 4.5 9 9 4.5M4.5 9h10a5.5 5.5 0 0 1 0 11H11" },
  heli_orbit: { hue: 150, label: "Vrtulník krouží nad místem", icon: "M20 12a8 8 0 1 1-2.6-5.9M20 4v4.5h-4.5M12 12h.01" },
  watched: { hue: 325, label: "Sledované letadlo", icon: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z" },
};
const FALLBACK = { hue: 200, label: "Událost", icon: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 8v4.5M12 16h.01" };

// Chips in the search; order = order on screen.
export const FILTER_TYPES = [
  ["emergency", "Nouze"],
  ["interesting", "Zajímavé"],
  ["go_around", "Nepovedená přistání"],
  ["holding", "Holding"],
  ["rapid_descent", "Klesání"],
  ["return_or_diversion", "Návraty"],
  ["heli_orbit", "Vrtulníky"],
  ["watched", "Sledovaná"],
];

const SQUAWKS = { 7700: "Squawk 7700: obecná nouze", 7600: "Squawk 7600: ztráta rádiového spojení", 7500: "Squawk 7500: únos" };
const EMERGENCY_KINDS = {
  general: "Hlášena obecná nouze",
  minfuel: "Hlášen nedostatek paliva",
  nordo: "Hlášena ztráta rádiového spojení",
  unlawful: "Hlášeno protiprávní jednání na palubě",
  downed: "Hlášena havárie",
  lifeguard: "Zdravotnický let s prioritou",
};

export const eventType = (e) => EVENT_TYPES[e.type] || FALLBACK;

export function eventLabel(e) {
  if (e.type === "watched") return e.data?.label || e.data?.name || EVENT_TYPES.watched.label;
  return eventType(e).label;
}

export const eventCallsign = (e) => (e.callsign || "").trim() || e.data?.registration || e.hex.toUpperCase();

// One short line with the key facts, or null.
export function eventDetail(e) {
  const d = e.data || {};
  switch (e.type) {
    case "emergency":
      return SQUAWKS[d.squawk] || EMERGENCY_KINDS[d.emergency] || (d.squawk ? `Squawk ${d.squawk}` : null);
    case "holding":
      return d.window_min ? `Krouží ${String(d.window_min).replace(".", ",")} min nad jedním místem` : null;
    case "go_around":
    case "return_or_diversion":
      return d.airport_name || d.airport || null;
    case "interesting":
      return d.type_name || null;
    case "rapid_descent":
      return d.loss_ft
        ? `−${num(d.loss_ft * 0.3048)} m, ${(Math.abs(d.rate_fpm || 0) * 0.3048 / 60).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} m/s`
        : null;
    case "heli_orbit":
      return d.turned_deg ? `${num(d.turned_deg / 360)}× dokola za ${num(d.window_min || 0)} min` : null;
    case "watched":
      return d.reason || d.note || null;
    default:
      return null;
  }
}

// Squawk 7500 is very often a mistake or a test: always say so.
export const isHijackSquawk = (e) =>
  e.type === "emergency" && (e.data?.squawk === "7500" || e.data?.emergency === "unlawful" || e.data?.unverified);
export const HIJACK_NOTE = "Často jde o chybu nebo test, neověřeno.";

export function timeAgo(iso, now = Date.now()) {
  const t = Date.parse(iso);
  const min = Math.floor((now - t) / 60000);
  if (min < 1) return "právě teď";
  if (min < 60) return `před ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `před ${h} h`;
  return new Date(t).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const fullTime = (iso) =>
  new Date(iso).toLocaleString("cs-CZ", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });

// The explanation usually arrives within seconds; after this long we stop waiting for it.
export const isExplanationPending = (e, now = Date.now()) => !e.explanation && now - Date.parse(e.started_at) < 3 * 60_000;
