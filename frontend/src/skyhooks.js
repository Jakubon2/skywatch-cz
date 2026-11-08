// Browser plumbing for the "Obloha" tab: observer position, device orientation, rear camera, route lookup.
import { useEffect, useRef, useState } from "react";
import { angleDiff, compassHeadingFor, rotationMatrix } from "./skymath.js";

// Typical height of the ground in Czechia (m above sea level), used when GPS doesn't report altitude.
const DEFAULT_GROUND_M = 300;

// Observer: live GPS once the user allows it, else the saved home from "Nad hlavou".
// Starts GPS by itself only when the permission was already granted; otherwise waits for a tap (locate).
export function useObserver(home) {
  const [gps, setGps] = useState(null);
  const [geo, setGeo] = useState("idle"); // idle | locating | on | denied | error | unsupported
  const watch = useRef(null);

  const locate = () => {
    if (!navigator.geolocation) return setGeo("unsupported");
    if (watch.current != null) return;
    setGeo("locating");
    watch.current = navigator.geolocation.watchPosition(
      (p) => {
        setGeo("on");
        setGps({ lat: p.coords.latitude, lon: p.coords.longitude, alt: p.coords.altitude, accuracy: p.coords.accuracy });
      },
      (err) => {
        navigator.geolocation.clearWatch(watch.current);
        watch.current = null;
        setGeo(err.code === 1 ? "denied" : "error");
      },
      { enableHighAccuracy: true, maximumAge: 30000, timeout: 20000 },
    );
  };

  useEffect(() => {
    navigator.permissions
      ?.query({ name: "geolocation" })
      .then((s) => s.state === "granted" && locate())
      .catch(() => {});
    return () => watch.current != null && navigator.geolocation.clearWatch(watch.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // GPS altitude is above the WGS84 ellipsoid (~45 m above sea level here): close enough.
  const observer = gps
    ? { lat: gps.lat, lon: gps.lon, alt: gps.alt ?? DEFAULT_GROUND_M, source: "gps", accuracy: gps.accuracy }
    : home
      ? { lat: home.lat, lon: home.lon, alt: DEFAULT_GROUND_M, source: "home", label: home.label }
      : null;
  return { observer, geo, locate };
}

// Device orientation as an absolute rotation matrix (ENU) in `matrix.current`, updated on every sensor event.
// Android: `deviceorientationabsolute` gives alpha relative to north.
// iOS: alpha is relative to an arbitrary start, so we learn the offset to north from webkitCompassHeading
// and smooth it heavily (it's nearly constant), which also hides most compass jitter.
export function useOrientation() {
  const [status, setStatus] = useState("idle"); // idle | asking | on | denied | nodata | relative | unsupported
  const [accuracy, setAccuracy] = useState(null); // iOS only: compass accuracy in degrees, -1 = uncalibrated
  const matrix = useRef(null);
  const stopRef = useRef(null);

  const stop = () => {
    stopRef.current?.();
    stopRef.current = null;
    matrix.current = null;
  };

  const start = async () => {
    if (typeof DeviceOrientationEvent === "undefined") return setStatus("unsupported");
    setStatus("asking");
    // iOS 13+: must be called from a tap.
    if (typeof DeviceOrientationEvent.requestPermission === "function") {
      try {
        if ((await DeviceOrientationEvent.requestPermission()) !== "granted") return setStatus("denied");
      } catch {
        return setStatus("denied");
      }
    }
    stop();
    const type = "ondeviceorientationabsolute" in window ? "deviceorientationabsolute" : "deviceorientation";
    let got = false;
    let offset = null; // iOS: [cos, sin] of the alpha correction, smoothed
    let lastAcc = null;

    const onEvent = (e) => {
      if (e.alpha == null || e.beta == null || e.gamma == null) return;
      let alpha = e.alpha;
      if (e.webkitCompassHeading != null) {
        const acc = e.webkitCompassAccuracy;
        if (acc !== lastAcc && (lastAcc == null || Math.abs(acc - lastAcc) >= 2 || acc < 0)) setAccuracy((lastAcc = acc));
        const h = compassHeadingFor(rotationMatrix(e.alpha, e.beta, e.gamma));
        if (h != null && acc >= 0) {
          const d = (angleDiff(e.webkitCompassHeading, h) * Math.PI) / 180; // alpha_abs = alpha + (h - compass)
          const k = offset ? 0.04 : 1;
          offset = offset
            ? [offset[0] + (Math.cos(d) - offset[0]) * k, offset[1] + (Math.sin(d) - offset[1]) * k]
            : [Math.cos(d), Math.sin(d)];
        }
        if (!offset) return; // wait for the first usable compass reading
        alpha += (Math.atan2(offset[1], offset[0]) * 180) / Math.PI;
      } else if (type === "deviceorientation" && !e.absolute) {
        // No compass reference at all: directions would be meaningless.
        stop();
        return setStatus("relative");
      }
      matrix.current = rotationMatrix(alpha, e.beta, e.gamma);
      if (!got) {
        got = true;
        setStatus("on");
      }
    };

    window.addEventListener(type, onEvent);
    const timer = setTimeout(() => {
      if (!got) {
        stop();
        setStatus("nodata");
      }
    }, 3000);
    stopRef.current = () => {
      clearTimeout(timer);
      window.removeEventListener(type, onEvent);
    };
  };

  useEffect(() => stop, []);

  return { status, accuracy, matrix, start, stop: () => (stop(), setStatus("idle")) };
}

// Rear camera as the AR background. Starts only from a tap, stops on unmount. The picture stays in the
// <video> element: nothing is recorded or sent anywhere. Needs https (or localhost).
export function useCamera() {
  const video = useRef(null);
  const stream = useRef(null);
  const [on, setOn] = useState(false);
  const [error, setError] = useState(null);
  const [size, setSize] = useState(null); // intrinsic video size, for the field-of-view estimate

  const attach = (el) => {
    if (el && stream.current && el.srcObject !== stream.current) {
      el.srcObject = stream.current;
      el.play().catch(() => {});
    }
  };
  // Callback ref: the <video> may mount before or after the stream arrives.
  const videoRef = (el) => {
    video.current = el;
    attach(el);
  };

  const stop = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setOn(false);
  };

  const start = async () => {
    setError(null);
    if (!window.isSecureContext) return setError("Kamera potřebuje zabezpečené připojení (https).");
    if (!navigator.mediaDevices?.getUserMedia) return setError("Tenhle prohlížeč kameru nezpřístupní.");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = s;
      setOn(true);
      attach(video.current);
    } catch (e) {
      setError(e.name === "NotAllowedError" ? "Přístup ke kameře je zakázaný." : "Kameru se nepodařilo zapnout.");
    }
  };

  useEffect(() => () => stream.current?.getTracks().forEach((t) => t.stop()), []);

  const onLoaded = (e) => setSize({ w: e.target.videoWidth, h: e.target.videoHeight });
  return { videoRef, onLoaded, size, on, error, start, stop, toggle: () => (on ? stop() : start()) };
}

// Route for a callsign from GET /api/route/{callsign}. Waits a moment so sweeping the phone across the sky
// doesn't fire a lookup for every plane it passes. Results are cached for this visit.
const routeCache = new Map();
export function useRoute(callsign, delayMs = 700) {
  const [, rerender] = useState(0);
  const valid = callsign && /^[A-Z0-9]{2,8}$/.test(callsign);
  useEffect(() => {
    if (!valid || routeCache.has(callsign)) return;
    const t = setTimeout(() => {
      routeCache.set(callsign, "loading");
      rerender((n) => n + 1);
      fetch(`/api/route/${callsign}`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d) => routeCache.set(callsign, d.route || null))
        .catch(() => routeCache.delete(callsign)) // transient: try again next time
        .finally(() => rerender((n) => n + 1));
    }, delayMs);
    return () => clearTimeout(t);
  }, [callsign, valid, delayMs]);
  return valid ? routeCache.get(callsign) : undefined; // undefined | "loading" | null (unknown) | route
}
