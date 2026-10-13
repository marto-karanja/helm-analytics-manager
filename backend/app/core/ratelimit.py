"""A small in-memory sliding-window limiter for the unauthenticated auth endpoints.

One process, one container: the state is not shared across restarts or replicas, which is fine for a single-owner tool.
It slows password guessing and demo-token minting; it is not a substitute for a firewall rule at the edge."""

import time
from collections import defaultdict, deque

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

# (method, path) -> attempts allowed per window. Counts every attempt, not only failures.
LIMITED = {
    ("POST", "/api/auth/login"): lambda: settings.login_rate_limit,
    ("POST", "/api/auth/demo-login"): lambda: settings.demo_login_rate_limit,
}
_MAX_KEYS = 10_000

_hits: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """The caller's address. Behind the Cloudflare tunnel the TCP peer is the proxy, so prefer the header
    Cloudflare sets (and overwrites on the way in); the origin is only reachable through the tunnel."""
    return (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else "unknown")
    ).strip()


def reset() -> None:
    _hits.clear()


def check(method: str, path: str, ip: str, now: float | None = None) -> int | None:
    """None if the request may proceed, else the seconds until it may."""
    limit_for = LIMITED.get((method, path))
    if limit_for is None:
        return None
    limit, window = limit_for(), settings.auth_rate_window_seconds
    now = time.monotonic() if now is None else now
    if len(_hits) > _MAX_KEYS:  # drop idle keys instead of growing without bound
        for key in [k for k, q in _hits.items() if not q or now - q[-1] > window]:
            del _hits[key]
    hits = _hits[(method, path, ip)]
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        return max(1, int(window - (now - hits[0])) + 1)
    hits.append(now)
    return None


async def rate_limit_middleware(request: Request, call_next):
    retry_after = check(request.method, request.url.path, client_ip(request))
    if retry_after is not None:
        return JSONResponse(
            {"detail": f"Too many attempts. Try again in {retry_after} seconds."},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)
