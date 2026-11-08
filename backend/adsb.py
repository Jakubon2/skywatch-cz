"""Client for readsb-compatible APIs (adsb.lol by default) with a polite polling loop."""

import asyncio
import logging
import time
from typing import Awaitable, Callable

import httpx

from config import ADSB_API_KEY, CONFIG

log = logging.getLogger("adsb")


class RateLimited(Exception):
    def __init__(self, retry_after: float | None):
        self.retry_after = retry_after


class AdsbClient:
    def __init__(self):
        src = CONFIG["source"]
        self.url = (
            f"{src['base_url'].rstrip('/')}/v2/lat/{src['center_lat']}"
            f"/lon/{src['center_lon']}/dist/{src['radius_nm']}"
        )
        headers = {"User-Agent": "skywatch-cz/0.1"}
        if ADSB_API_KEY:
            headers["api-auth"] = ADSB_API_KEY
        self.http = httpx.AsyncClient(
            headers=headers, timeout=CONFIG["poller"]["request_timeout_s"]
        )

    async def fetch(self) -> dict:
        """Return the raw snapshot: {"now": ms, "ac": [...], ...}."""
        r = await self.http.get(self.url)
        if r.status_code == 429:
            retry = r.headers.get("Retry-After")
            raise RateLimited(float(retry) if retry and retry.isdigit() else None)
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self.http.aclose()


async def poll_forever(
    client: AdsbClient,
    on_snapshot: Callable[[dict], Awaitable[None] | None],
    stop_at: float | None = None,
):
    """Fetch a snapshot every interval_s; back off exponentially on 429 or errors.

    Requests are spaced at least interval_s apart (measured start to start).
    `stop_at` is a time.monotonic() deadline, None = run forever.
    """
    interval = CONFIG["poller"]["interval_s"]
    max_backoff = CONFIG["poller"]["max_backoff_s"]
    failures = 0

    while stop_at is None or time.monotonic() < stop_at:
        started = time.monotonic()
        try:
            snapshot = await client.fetch()
            failures = 0
            result = on_snapshot(snapshot)
            if asyncio.iscoroutine(result):
                await result
            delay = interval
        except RateLimited as e:
            failures += 1
            delay = e.retry_after or min(interval * 2**failures, max_backoff)
            log.warning("HTTP 429 from source, backing off %.0f s", delay)
        except (httpx.HTTPError, ValueError) as e:
            failures += 1
            delay = min(interval * 2**failures, max_backoff)
            log.warning("fetch failed (%s), retrying in %.0f s", e, delay)

        await asyncio.sleep(max(0.0, delay - (time.monotonic() - started)))
