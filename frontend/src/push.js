// Web Push helpers for a settings toggle (backend: backend/push.py, handlers: public/sw.js).
//
//   const s = isPushSupported();       // sync: { supported, reason, message }
//   if (!s.supported) show(s.message); // Czech text explaining why, ready for the UI
//   await getPushState();              // "on" | "off" | "denied" | "unsupported"
//   await enablePush();                // asks permission, subscribes, registers with the backend
//   await disablePush();               // unsubscribes here and on the backend
//   await sendTestPush();              // test notification to this device only
//
// enablePush/disablePush/sendTestPush throw Error with a Czech `message` the UI can show as is.
// The service worker is registered only in production builds (main.jsx), so push is
// reported unsupported under `npm run dev`; test with `npm run build && npm run preview`.

const isIOS = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPadOS reports as a Mac

const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;

/**
 * Can this browser receive Web Push here and now?
 * reason: null | "dev" | "ios-not-installed" | "ios-too-old" | "unsupported"
 * iOS/iPadOS supports Web Push only in a PWA added to the home screen, on iOS 16.4 and newer.
 */
export function isPushSupported() {
  const ok = (reason, message) => ({ supported: !reason, reason, message });
  if (!import.meta.env.PROD) return ok("dev", "Upozornění fungují jen v produkčním sestavení aplikace.");
  if (isIOS() && !isStandalone())
    return ok(
      "ios-not-installed",
      "Na iPhonu a iPadu fungují upozornění jen v aplikaci přidané na plochu: v Safari klepni na Sdílet → Přidat na plochu a otevři Skywatch odtud.",
    );
  const api = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (!api && isIOS()) return ok("ios-too-old", "Upozornění vyžadují iOS 16.4 nebo novější.");
  if (!api || !window.isSecureContext) return ok("unsupported", "Tento prohlížeč upozornění nepodporuje.");
  return ok(null, "");
}

async function currentSubscription() {
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => null);
    throw new Error(typeof detail === "string" ? detail : "Server upozornění nepřijal, zkus to znovu.");
  }
  return res.json();
}

/** "on" | "off" | "denied" (blocked in browser settings) | "unsupported" */
export async function getPushState() {
  if (!isPushSupported().supported) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return (await currentSubscription()) ? "on" : "off";
}

// VAPID public key: base64url -> bytes for applicationServerKey.
function keyBytes(b64url) {
  const b64 = (b64url + "=".repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

/** Must be called from a user gesture (click), otherwise browsers refuse the permission prompt. */
export async function enablePush() {
  const support = isPushSupported();
  if (!support.supported) throw new Error(support.message);
  const permission = await Notification.requestPermission();
  if (permission !== "granted")
    throw new Error("Upozornění jsou v prohlížeči zakázaná. Povol je v nastavení webu.");

  const res = await fetch("/api/push/key");
  if (!res.ok) throw new Error("Upozornění nejsou na serveru nastavená.");
  const { key } = await res.json();

  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  // A subscription made with a different (rotated) server key would be rejected: replace it.
  const sameKey = sub && sub.options.applicationServerKey &&
    new Uint8Array(sub.options.applicationServerKey).toString() === keyBytes(key).toString();
  if (sub && !sameKey) {
    await sub.unsubscribe();
    sub = null;
  }
  sub ||= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  await post("/api/push/subscribe", sub.toJSON());
  return sub;
}

export async function disablePush() {
  if (!isPushSupported().supported) return;
  const sub = await currentSubscription();
  if (!sub) return;
  await post("/api/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {}); // best effort
  await sub.unsubscribe();
}

/** Sends a test notification to this device only. */
export async function sendTestPush() {
  const sub = isPushSupported().supported && (await currentSubscription());
  if (!sub) throw new Error("Upozornění na tomto zařízení nejsou zapnutá.");
  return post("/api/push/test", { endpoint: sub.endpoint });
}

/** This device's push endpoint, or null when push is off/unsupported (lets the backend notify only this device). */
export async function pushEndpoint() {
  try {
    if (!isPushSupported().supported || Notification.permission !== "granted") return null;
    return (await currentSubscription())?.endpoint || null;
  } catch {
    return null;
  }
}
