# How I built Skywatch CZ

Flightradar24 shows you *everything*: thousands of dots, all equally loud. I wanted the opposite. I wanted an
app that watches the sky over Czechia for me and only speaks up when something is worth a look: an emergency
squawk over Brno, an airliner going around at Prague, a rescue helicopter circling over my district, Taylor
Swift's jet crossing the country. When it speaks up, it should explain what happened in plain Czech, honestly.

This is how it came together, what was harder than expected, and what I'd do differently.

## The shape of it

```
adsb.lol ──► Poller ──► detectors ──► SQLite ──► FastAPI (REST + SSE) ──► React PWA
                 └─► listeners: alerts, push, flight tracking, visit history
```

One Python process polls [adsb.lol](https://adsb.lol) every 10 seconds for all aircraft within 160 nautical
miles of the centre of Czechia (about 170 aircraft at a time). Each snapshot goes through:

1. **Ingest**: drop anything that isn't an aircraft (ADS-B also comes from towers, ground vehicles and
   obstacles) and append positions to an in-memory track per aircraft.
2. **Detectors**: pure functions `(track, ctx) -> event | None`.
3. **Deduplication**: one event per aircraft and type within a window. The window is restored from the
   database on startup. Otherwise every restart re-detected and re-explained everything from the last 30
   minutes, which I only noticed when one helicopter produced 21 identical events.
4. **Listeners**: alerts, push notifications, flight tracking and visit history all register as callbacks
   instead of editing the ingest loop. That kept the core small while the feature list grew.

The frontend is React 18 with plain Leaflet: no map wrapper library. Markers are created once per aircraft and
updated in place, and CSS transitions make them glide between the 10-second snapshots.

## Detectors as pure functions

This was the best decision of the project. Every detector takes a track (a list of readsb samples) and a
context (thresholds from YAML, known airports, the watchlist) and returns an event or nothing. No I/O, no
clock, no globals. That means:

- **Synthetic tracks** for the obvious cases: "descending toward an airport, then a sustained climb without
  touching down" is a go-around.
- **Recorded traffic** for the non-obvious ones. `record.py` saves 30 minutes of real snapshots and
  `replay.py` runs them through every detector. That is how I tuned holding detection: real holding patterns
  are much messier than the textbook racetrack.
- **Thresholds live in config**, so tuning a false positive is a YAML change plus a regression test, not a
  code change.

The detectors that ship: emergency squawk, rapid descent, go-around, holding, return or diversion, helicopter
orbit, interesting or rare type, and watched aircraft.

## Making an LLM honest

Each new event gets a short Czech explanation from Claude Haiku. The danger is obvious: an LLM asked "why is
this plane descending fast?" will happily invent a pressurisation failure. So:

- The prompt contains **only measured data** (altitudes, rates, distances, the detector's reason) and an
  explicit rule: if the cause isn't clear from the data, say so. The UI labels every explanation
  "Vysvětlení od AI, neověřeno" ("AI explanation, unverified").
- **Units** are converted before the model sees them. The data is in feet and knots internally, but the
  model must never output either: Czech readers think in metres and km/h.
- **Every call type has a hard cap** (explanations, chat and summaries per hour or day). Above the cap the
  app keeps working, just without the AI text.

The same model turns alerts typed in plain language ("tell me when a military plane flies low over Brno")
into a structured rule. The rule, not the model, decides what matches, so matching stays deterministic and
testable.

## Being a good API citizen

adsb.lol is free and community-run, so the app makes at most one request every 10 seconds, with exponential
backoff on HTTP 429. That budget caused the most interesting constraint later on. Flight tracking ("tell me
when OK 640 lands") needs aircraft *outside* our area, which takes a different endpoint. Instead of adding
requests, a lookup for a tracked flight **takes the slot of one area snapshot**, at most once a minute and
only while someone tracks a flight that is out of range. The map skips one frame a minute and nobody notices.

## Privacy

Some aircraft owners ask the FAA not to be tracked (LADD and PIA programmes). The data marks them, and the app
never highlights, alerts on, follows or records visits of those aircraft. The celebrity watchlist only accepts
public figures with a public source, and it is honest that ownership data goes stale.

## Mobile first, for real

Most use is on a phone, outdoors, sometimes on bad signal:

- **PWA** with a hand-written service worker. The app shell works offline; live data never comes from a
  cache.
- **Labels without clutter.** At country zoom, about 170 labels overlap into noise. The map places them
  greedily by priority (selected, emergency, military, heavy, then altitude) and hides the losers. Labels
  already on screen get a small bonus, so they don't flicker between snapshots.
- **Bundle size.** Rarely used tabs load on demand, and React and Leaflet sit in a separate long-cached chunk,
  so an update downloads about 33 kB of gzipped app code.
- **Battery saver** slows every poll, and the AR camera view only runs while it's open.

## Running it for free

Production runs on a Google Cloud e2-micro (1 GB RAM, free tier) with Docker Compose and Caddy. Caddy handles
HTTPS automatically and a token login with an HttpOnly cookie. Lessons:

- **1 GB is not enough to run `npm install`** next to the app, so the frontend is built on my laptop and only
  `dist/` is uploaded.
- **A one-character Caddy bug cost an evening.** `redir / 303` treats `/` as a path matcher, so the login
  redirect never fired and phones showed a blank page. `redir * / 303` fixed it.
- **Server-Sent Events kept uvicorn's `--reload` hanging forever**, which `--timeout-graceful-shutdown 2`
  fixed.
- **A budget alert at 25 CZK** means a surprise bill would be noticed on day one.

## How I worked

I built this with an AI coding assistant (Claude Code) as a pair programmer. I set the direction, the
constraints (metric units, honest AI text, request budget, privacy rules) and the priorities. I tested on my
phone and decided what was good enough, while the assistant wrote much of the code and the tests. What made
it work:

- a short `CLAUDE.md` with non-negotiable rules,
- a phased plan (`PLAN.md`), stopping after each phase to verify,
- tests for everything that has logic in it.

## What I'd do next

- Viewport-based fetching, to look at traffic anywhere and not only over Czechia, without blowing the free
  egress budget.
- A small own ADS-B receiver (RTL-SDR on a Raspberry Pi), for independence from public feeds and maybe live
  tower audio.
- Per-person accounts instead of one shared token.
