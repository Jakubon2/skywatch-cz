// Sharing an event: a link (Web Share API, else clipboard) or a client-rendered PNG card.
import { eventCallsign, eventDetail, eventLabel, eventType, fullTime, HIJACK_NOTE, isHijackSquawk } from "./events.js";

export const eventUrl = (e) => `${location.origin}/?event=${e.id}`;

const shareTitle = (e) => `${eventLabel(e)}: ${eventCallsign(e)}`;
const aborted = (err) => err?.name === "AbortError";

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    window.prompt("Zkopíruj si odkaz:", text); // insecure context or clipboard blocked
  }
}

// Returns "shared" | "copied" | null (user cancelled).
export async function shareLink(e) {
  const url = eventUrl(e);
  if (navigator.share) {
    try {
      await navigator.share({ title: shareTitle(e), text: `${shareTitle(e)} nad Českem`, url });
      return "shared";
    } catch (err) {
      if (aborted(err)) return null;
    }
  }
  await copy(url);
  return "copied";
}

// Returns "shared" | "saved" | null.
export async function shareImage(e) {
  const blob = await renderCard(e);
  const file = new File([blob], `skywatch-udalost-${e.id}.png`, { type: "image/png" });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: shareTitle(e), text: eventUrl(e) });
      return "shared";
    } catch (err) {
      if (aborted(err)) return null;
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = file.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  return "saved";
}

// ---------- Share image: a map-free 1080x1350 card, always dark so it looks the same everywhere ----------

const W = 1080, H = 1350, M = 88;
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

function wrap(ctx, text, maxWidth, maxLines) {
  const words = text.split(/\s+/);
  const lines = [];
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (ctx.measureText(next).width <= maxWidth || !line) line = next;
    else {
      lines.push(line);
      line = w;
    }
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    let last = lines[maxLines - 1];
    while (ctx.measureText(last + "…").width > maxWidth) last = last.slice(0, -1);
    lines[maxLines - 1] = last.trimEnd() + "…";
  }
  return lines;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  ctx.fill();
}

function renderCard(e) {
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d");
  const { hue, icon } = eventType(e);
  const color = e.type === "emergency" ? "#f87171" : `hsl(${hue} 75% 70%)`;

  const bg = ctx.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, "#0b1220");
  bg.addColorStop(1, "#14223d");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  const glow = ctx.createRadialGradient(W - 120, 140, 0, W - 120, 140, 700);
  glow.addColorStop(0, `hsl(${hue} 80% 55% / 0.28)`);
  glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);

  // Brand
  ctx.fillStyle = "#e2e8f0";
  ctx.font = `600 38px ${FONT}`;
  ctx.textBaseline = "middle";
  ctx.fillText("Skywatch", M, M + 20);
  const bw = ctx.measureText("Skywatch ").width;
  ctx.fillStyle = "#5eead4";
  ctx.font = `800 38px ${FONT}`;
  ctx.fillText("CZ", M + bw, M + 20);

  // Type pill with icon
  let y = 250;
  ctx.font = `650 34px ${FONT}`;
  const label = eventLabel(e);
  const labelW = Math.min(ctx.measureText(label).width, W - 2 * M - 110);
  ctx.fillStyle = `hsl(${hue} 80% 60% / 0.16)`;
  roundRect(ctx, M, y - 38, labelW + 112, 76, 38);
  ctx.save();
  ctx.translate(M + 22, y - 18);
  ctx.scale(36 / 24, 36 / 24);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke(new Path2D(icon));
  ctx.restore();
  ctx.fillStyle = color;
  ctx.fillText(label, M + 78, y + 1, labelW);

  // Callsign, aircraft, time
  y += 150;
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#f8fafc";
  ctx.font = `800 120px ${FONT}`;
  ctx.fillText(eventCallsign(e), M, y, W - 2 * M);
  y += 72;
  ctx.fillStyle = "#94a3b8";
  ctx.font = `500 40px ${FONT}`;
  const sub = [e.data?.type_name || e.aircraft_type, e.data?.registration].filter(Boolean).join(" · ");
  if (sub) {
    ctx.fillText(sub, M, y, W - 2 * M);
    y += 60;
  }
  ctx.fillText(fullTime(e.started_at), M, y, W - 2 * M);

  const detail = [eventDetail(e), isHijackSquawk(e) ? HIJACK_NOTE : null].filter(Boolean).join(" ");
  if (detail) {
    y += 80;
    ctx.fillStyle = "#e2e8f0";
    ctx.font = `600 40px ${FONT}`;
    for (const l of wrap(ctx, detail, W - 2 * M, 2)) {
      ctx.fillText(l, M, y);
      y += 54;
    }
    y -= 54;
  }

  // Explanation
  if (e.explanation) {
    y += 70;
    const lines = (() => {
      ctx.font = `400 38px ${FONT}`;
      return wrap(ctx, e.explanation, W - 2 * M - 72, Math.max(2, Math.floor((H - 190 - y - 90) / 56)));
    })();
    const boxH = 90 + lines.length * 56 + 20;
    ctx.fillStyle = "rgba(148, 163, 184, 0.1)";
    roundRect(ctx, M, y, W - 2 * M, boxH, 32);
    ctx.fillStyle = "#94a3b8";
    ctx.font = `600 28px ${FONT}`;
    ctx.fillText("VYSVĚTLENÍ OD AI, NEOVĚŘENO", M + 36, y + 62);
    ctx.fillStyle = "#e2e8f0";
    ctx.font = `400 38px ${FONT}`;
    lines.forEach((l, i) => ctx.fillText(l, M + 36, y + 124 + i * 56));
  }

  // Attribution
  ctx.fillStyle = "#64748b";
  ctx.font = `500 30px ${FONT}`;
  ctx.fillText("Data: adsb.lol (ODbL)", M, H - M + 10);
  ctx.textAlign = "right";
  ctx.fillText(location.host, W - M, H - M + 10);

  return new Promise((resolve) => c.toBlob(resolve, "image/png"));
}
