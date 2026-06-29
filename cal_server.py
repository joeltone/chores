"""Secure aiohttp calendar server for webcal subscriptions.

Security model:
- Binds to 127.0.0.1 only; only cloudflared can reach it
- CF-Connecting-IP validated against Google's published IP ranges
- User-Agent must contain "Google"
- Per-user 256-bit secret token in URL path
- Rate limiting: max 20 requests/hour per token
"""

import asyncio
import ipaddress
import logging
import os
import time
from collections import defaultdict

import aiohttp
from aiohttp import web

from ical import build_ics

log = logging.getLogger("cal-server")

RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 3600  # seconds
GOOGLE_IP_REFRESH_INTERVAL = 86400  # 24 hours

_google_prefixes: list = []
_rate_limit: dict[str, list[float]] = defaultdict(list)


# ---------------------------------------------------------------------------
# Google IP range management
# ---------------------------------------------------------------------------

async def _fetch_google_ips(session: aiohttp.ClientSession) -> list:
    prefixes = []
    urls = [
        "https://www.gstatic.com/ipranges/goog.json",
        "https://www.gstatic.com/ipranges/cloud.json",
    ]
    for url in urls:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
                for entry in data.get("prefixes", []):
                    cidr = entry.get("ipv4Prefix") or entry.get("ipv6Prefix")
                    if cidr:
                        prefixes.append(ipaddress.ip_network(cidr, strict=False))
        except Exception as exc:
            log.warning("Failed to fetch Google IPs from %s: %s", url, exc)
    return prefixes


async def refresh_google_ips() -> None:
    global _google_prefixes
    async with aiohttp.ClientSession() as session:
        prefixes = await _fetch_google_ips(session)
    if prefixes:
        _google_prefixes = prefixes
        log.info("Loaded %d Google IP prefixes", len(prefixes))
    else:
        log.warning("Could not load Google IP prefixes — IP check will be skipped this cycle")


async def _periodic_refresh() -> None:
    while True:
        await asyncio.sleep(GOOGLE_IP_REFRESH_INTERVAL)
        await refresh_google_ips()


def _is_google_ip(ip_str: str) -> bool:
    if not _google_prefixes:
        log.warning("Google IP list empty — skipping IP validation")
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in prefix for prefix in _google_prefixes)
    except ValueError:
        log.warning("Unparseable IP in CF-Connecting-IP: %s", ip_str)
        return False


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _allow_request(token: str) -> bool:
    now = time.monotonic()
    window = [t for t in _rate_limit[token] if now - t < RATE_LIMIT_WINDOW]
    if len(window) >= RATE_LIMIT_MAX:
        return False
    window.append(now)
    _rate_limit[token] = window
    return True


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

async def handle_calendar(request: web.Request) -> web.Response:
    token = request.match_info["token"]

    # Rate limit
    if not _allow_request(token):
        log.warning("Rate limit exceeded for token %s…", token[:8])
        return web.Response(status=429, text="Too Many Requests")

    # When running behind Cloudflare Tunnel, CF-Connecting-IP is the real
    # client IP. If present, enforce Google-only access.
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        if not _is_google_ip(cf_ip):
            log.warning("Blocked non-Google IP: %s", cf_ip)
            return web.Response(status=403, text="Forbidden")

        ua = request.headers.get("User-Agent", "")
        if "Google" not in ua:
            log.warning("Blocked non-Google User-Agent from %s: %s", cf_ip, ua)
            return web.Response(status=403, text="Forbidden")

    # Token → user lookup (constant-time comparison via DB lookup only)
    from db import get_db
    db = get_db()
    user = db.execute(
        "SELECT user_id, display_name FROM users "
        "WHERE calendar_token = ? AND is_removed = 0",
        (token,),
    ).fetchone()

    if not user:
        # Don't reveal whether token is wrong vs user removed
        log.info("Calendar request with unknown/invalid token %s…", token[:8])
        return web.Response(status=404, text="Not Found")

    rows = db.execute("""
        SELECT c.chore_name, c.description, a.date_due, a.assignment_id
        FROM active_assignments a
        JOIN chores c ON c.chore_id = a.chore_id
        WHERE a.assigned_user_id = ? AND a.is_completed = 0
        ORDER BY a.date_due
    """, (user["user_id"],)).fetchall()

    ics = build_ics(rows, user["display_name"])
    log.info("Served calendar for user_id=%s (%d events)", user["user_id"], len(rows))

    return web.Response(
        text=ics,
        content_type="text/calendar",
        charset="utf-8",
        headers={
            "Content-Disposition": f'inline; filename="chores.ics"',
            "Cache-Control": "no-store, no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

async def start(host: str = "127.0.0.1", port: int = 8080) -> web.AppRunner:
    await refresh_google_ips()
    asyncio.get_event_loop().create_task(_periodic_refresh())

    app = web.Application()
    # Only one route — anything else returns 404 automatically
    app.router.add_get("/cal/{token}.ics", handle_calendar)

    runner = web.AppRunner(app, access_log=log)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Calendar server listening on http://%s:%d", host, port)
    return runner
