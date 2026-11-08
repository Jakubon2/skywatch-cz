"""Phone notifications: ntfy.sh (install the ntfy app and subscribe to NTFY_TOPIC) and Web Push (push.py)."""

import asyncio
import logging
import os

import httpx

import config  # noqa: F401  (loads .env)

log = logging.getLogger("notify")

NTFY_SERVER = "https://ntfy.sh"


async def send_ntfy(
    title: str,
    message: str,
    *,
    tags: list[str] | None = None,
    click: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Publish one notification. Returns True when sent; never raises on network errors."""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        log.info("NTFY_TOPIC not set, skipping notification: %s", title)
        return False

    # JSON publishing keeps UTF-8 titles intact (HTTP headers would mangle Czech diacritics).
    payload = {"topic": topic, "title": title, "message": message}
    if tags:
        payload["tags"] = tags
    if click:
        payload["click"] = click

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(NTFY_SERVER, json=payload)
        else:
            r = await client.post(NTFY_SERVER, json=payload)
        r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("ntfy failed: %s", e)
        return False


async def notify(
    title: str,
    message: str,
    *,
    tags: list[str] | None = None,
    url: str | None = None,
    tag: str | None = None,
) -> None:
    """Send to every channel: ntfy (fallback app) and Web Push (installed PWA). Never raises."""
    import push  # local import: push pulls in pywebpush, notify stays light for scripts

    click = url if url and url.startswith("http") else None  # ntfy needs an absolute URL
    await asyncio.gather(
        send_ntfy(title, message, tags=tags, click=click),
        push.send_push(title, message, url=url, tag=tag),
        return_exceptions=True,
    )
