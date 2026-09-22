"""Security headers and HTTP defense middleware.

Injects enterprise-grade defensive HTTP headers (HSTS, CSP, X-Frame-Options,
nosniff) and provides configuration hooks for CORS and trusted host validation.
"""

from __future__ import annotations

import logging
from typing import Mapping

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Standard enterprise security headers baseline
DEFAULT_SECURITY_HEADERS: Mapping[str, str] = {
    # 1. Prevent MIME-type sniffing (forces browser to respect Content-Type)
    "X-Content-Type-Options": "nosniff",
    # 2. Clickjacking protection: disallow iframe embedding
    "X-Frame-Options": "DENY",
    # 3. Enforce TLS/HTTPS for 1 year including subdomains
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    # 4. Content Security Policy: restrict script and object execution sources
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none';",
    # 5. Referrer policy: limit sensitive URL leakage in Referer header
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # 6. Modern XSS protection: disable legacy buggy XSS auditor
    "X-XSS-Protection": "0",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces hardened security headers on all outgoing HTTP responses."""

    def __init__(self, app, custom_headers: Mapping[str, str] | None = None):
        super().__init__(app)
        self.headers = {**DEFAULT_SECURITY_HEADERS, **(custom_headers or {})}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Inject security headers into every outbound response.

        =========================================================================
        CORS & HOST VALIDATION EXTENSION HOOK (PLACEHOLDER)
        =========================================================================
        For browser-facing APIs, CORS (Cross-Origin Resource Sharing) and Allowed
        Hosts should be validated here or configured via Starlette's CORSMiddleware.
        For internal microservices and task engines, strict origin filtering protects
        against cross-site request forgery and unauthorized domain interaction.
        =========================================================================
        """
        response: Response = await call_next(request)

        # Inject defensive headers
        for header_name, header_value in self.headers.items():
            # Do not overwrite if already explicitly set by endpoint
            if header_name not in response.headers:
                response.headers[header_name] = header_value

        return response

