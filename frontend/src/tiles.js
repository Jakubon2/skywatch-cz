// Muted map tiles (the tile server must send CORS headers; OSM does) with the colour change baked into the pixels once per tile.
// A CSS filter on every tile is re-applied by the GPU on each frame of a pan or zoom, which made the map
// stutter on phones. The filters below are the same CSS filter functions, composed into one affine colour
// matrix (Filter Effects spec), so the look matches the old `.leaflet-tile { filter: ... }`.
import L from "leaflet";

// Affine colour transform: v' = m·v + o, with v in 0..1.
const affine = (m, o = [0, 0, 0]) => ({ m, o });
const scale = (k, o = 0) => affine([[k, 0, 0], [0, k, 0], [0, 0, k]], [o, o, o]);
const brightness = (b) => scale(b);
const contrast = (c) => scale(c, 0.5 - 0.5 * c);
const invert = () => scale(-1, 1);
function grayscale(a) {
  const k = 1 - a;
  return affine([
    [0.2126 + 0.7874 * k, 0.7152 - 0.7152 * k, 0.0722 - 0.0722 * k],
    [0.2126 - 0.2126 * k, 0.7152 + 0.2848 * k, 0.0722 - 0.0722 * k],
    [0.2126 - 0.2126 * k, 0.7152 - 0.7152 * k, 0.0722 + 0.9278 * k],
  ]);
}
function hueRotate(deg) {
  const c = Math.cos((deg * Math.PI) / 180), s = Math.sin((deg * Math.PI) / 180);
  return affine([
    [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928],
    [0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.14, 0.072 - c * 0.072 - s * 0.283],
    [0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072],
  ]);
}

// Apply `fs` left to right, like a CSS filter list.
export function compose(...fs) {
  return fs.reduce((f, g) => ({
    m: g.m.map((row) => [0, 1, 2].map((j) => row[0] * f.m[0][j] + row[1] * f.m[1][j] + row[2] * f.m[2][j])),
    o: g.m.map((row, i) => row[0] * f.o[0] + row[1] * f.o[1] + row[2] * f.o[2] + g.o[i]),
  }));
}

export const LOOKS = {
  light: compose(grayscale(0.85), contrast(0.92), brightness(1.04)),
  dark: compose(invert(), hueRotate(180), grayscale(0.7), brightness(0.82), contrast(0.95)),
};

export function recolor(data, { m, o }) {
  const [[a, b, c], [d, e, f], [g, h, i]] = m;
  const [p, q, r] = o.map((x) => x * 255);
  for (let k = 0; k < data.length; k += 4) {
    const R = data[k], G = data[k + 1], B = data[k + 2];
    data[k] = a * R + b * G + c * B + p; // Uint8ClampedArray clamps and rounds
    data[k + 1] = d * R + e * G + f * B + q;
    data[k + 2] = g * R + h * G + i * B + r;
  }
}

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

/** L.tileLayer whose tiles are canvases recoloured once on load; follows the light/dark theme. */
export const MutedTileLayer = L.TileLayer.extend({
  onAdd(map) {
    this._onTheme = () => this.redraw();
    darkQuery.addEventListener("change", this._onTheme);
    L.TileLayer.prototype.onAdd.call(this, map);
  },
  onRemove(map) {
    darkQuery.removeEventListener("change", this._onTheme);
    L.TileLayer.prototype.onRemove.call(this, map);
  },
  createTile(coords, done) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = this.getTileSize().x;
    canvas.complete = false; // TileLayer._abortLoading drops tiles that aren't complete
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      try {
        const px = ctx.getImageData(0, 0, canvas.width, canvas.height);
        recolor(px.data, LOOKS[darkQuery.matches ? "dark" : "light"]);
        ctx.putImageData(px, 0, 0);
      } catch {
        /* canvas tainted: show the tile unmuted rather than not at all */
      }
      canvas.complete = true;
      done(null, canvas);
    };
    img.onerror = (e) => done(e, canvas);
    img.src = this.getTileUrl(coords);
    return canvas;
  },
});
