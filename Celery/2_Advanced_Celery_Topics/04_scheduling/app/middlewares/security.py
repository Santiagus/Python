"""Security headers middleware injecting defense-in-depth HTTP headers."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects defensive HTTP headers into outbound responses (OWASP recommendations)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add HSTS, CSP, nosniff, and frame options headers."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
