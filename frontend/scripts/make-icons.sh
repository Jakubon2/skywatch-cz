#!/bin/sh
# Regenerate PWA icons in public/icons/ from the favicon design.
# Uses macOS `sips` (built in), so no extra dependencies. Run from frontend/: sh scripts/make-icons.sh
set -e
cd "$(dirname "$0")/.."
out=public/icons
tmp=$(mktemp -d)
mkdir -p "$out"

# Same plane path and colours as public/favicon.svg.
plane='<path fill="#5eead4" d="M16 4l2.2 9.2L27 17v2l-8.8-2.2-.9 6.4 3.2 2.3V27L16 25.6 11.5 27v-1.5l3.2-2.3-.9-6.4L5 19v-2l8.8-3.8z"/>'

# Full-bleed square, plane shrunk around the centre by $1 (maskable / iOS crop the edges themselves).
square() {
  echo "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 32 32\"><rect width=\"32\" height=\"32\" fill=\"#0b1220\"/><g transform=\"translate(16 16) scale($1) translate(-16 -15.5)\">$plane</g></svg>"
}

square 0.72 > "$tmp/maskable.svg"
square 0.85 > "$tmp/apple.svg"

sips -s format png -z 192 192 public/favicon.svg --out "$out/icon-192.png" >/dev/null
sips -s format png -z 512 512 public/favicon.svg --out "$out/icon-512.png" >/dev/null
sips -s format png -z 512 512 "$tmp/maskable.svg" --out "$out/icon-maskable-512.png" >/dev/null
sips -s format png -z 180 180 "$tmp/apple.svg" --out "$out/apple-touch-icon.png" >/dev/null

rm -rf "$tmp"
ls -l "$out"
