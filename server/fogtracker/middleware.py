"""
HTTP rate limiting middleware.
"""

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Default: 60 requests per minute
DEFAULT_RATE_LIMIT = 60
DEFAULT_WINDOW_SECONDS = 60

# Stricter limits for expensive endpoints
STRICT_ENDPOINTS = {
    "/api/spoiler/parse": (10, 60),  # 10 requests/minute
}

# Paths to skip rate limiting (static files, websocket upgrades)
SKIP_PREFIXES = ("/js/", "/styles/", "/data/", "/assets/", "/help/", "/favicon")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Lightweight in-memory rate limiter per client IP."""

    def __init__(self, app):
        super().__init__(app)
        self._timestamps: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, respecting X-Forwarded-For from trusted proxy."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_rate_limited(self, key: str, max_requests: int, window: int) -> bool:
        """Check if key has exceeded rate limit. Returns True if blocked."""
        now = time.time()
        cutoff = now - window

        # Clean old timestamps
        timestamps = self._timestamps[key]
        self._timestamps[key] = [t for t in timestamps if t > cutoff]

        if len(self._timestamps[key]) >= max_requests:
            return True

        self._timestamps[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next):
        # Skip if rate limiting is disabled (e.g., during testing)
        if getattr(request.app.state, "disable_rate_limiting", False):
            return await call_next(request)

        path = request.url.path

        # Skip static files and WebSocket upgrades
        if any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        ip = self._get_client_ip(request)

        # Check strict endpoint limits first
        for endpoint, (max_req, window) in STRICT_ENDPOINTS.items():
            if path == endpoint:
                key = f"strict:{ip}:{endpoint}"
                if self._is_rate_limited(key, max_req, window):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many requests. Please try again later."},
                    )
                break

        # Check default rate limit for all API/auth endpoints
        if path.startswith("/api/") or path.startswith("/auth/"):
            key = f"default:{ip}"
            if self._is_rate_limited(key, DEFAULT_RATE_LIMIT, DEFAULT_WINDOW_SECONDS):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                )

        return await call_next(request)
