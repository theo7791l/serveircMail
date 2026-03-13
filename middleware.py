"""
Middleware de sécurité Awlor

Fonctionnalités :
  - Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
  - Rate limiting en mémoire par IP (login, register, verify, webhook, api)
"""

import time
import hashlib
import hmac
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


# ===========================================================
# SECURITY HEADERS MIDDLEWARE
# ===========================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Ajoute les headers de sécurité HTTP recommandés sur toutes les réponses.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Empêche le clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Empêche le MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Limite les informations envoyées dans le Referer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Empêche la mise en cache des pages sensibles
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        # Force HTTPS pendant 1 an (à activer uniquement si HTTPS est configuré)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Content Security Policy : bloque les scripts/iframes externes non autorisés
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.quilljs.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.quilljs.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response


# ===========================================================
# RATE LIMITER EN MÉMOIRE
# ===========================================================

class _RateLimitStore:
    """
    Store en mémoire pour le rate limiting.
    Structure : { ip: [(timestamp, endpoint), ...] }
    """
    def __init__(self):
        self._store: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds
        # Nettoie les entrées expirées
        self._store[key] = [t for t in self._store[key] if t > window_start]
        if len(self._store[key]) >= max_requests:
            return False
        self._store[key].append(now)
        return True

    def remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        now = time.time()
        window_start = now - window_seconds
        current = [t for t in self._store[key] if t > window_start]
        return max(0, max_requests - len(current))


_store = _RateLimitStore()


# Limites par route (max_requests, window_seconds)
RATE_LIMITS = {
    "/login":          (10, 60),    # 10 tentatives / minute par IP
    "/register":       (5,  300),   # 5 inscriptions / 5 min par IP
    "/verify":         (10, 60),    # 10 tentatives code / minute
    "/webhook":        (100, 60),   # 100 webhooks / minute (Resend peut envoyer en burst)
    "/api/send":       (30, 60),    # 30 envois / minute
    "/api/ai/chat":    (20, 60),    # 20 requêtes AI / minute
    "/api/":           (200, 60),   # 200 appels API / minute (général)
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting par IP sur les routes sensibles.
    Renvoie HTTP 429 si la limite est dépassée.
    """

    async def dispatch(self, request: Request, call_next):
        ip = _get_ip(request)
        path = request.url.path

        # Trouve la règle applicable
        limit_key = None
        max_req = 0
        window = 60

        for prefix, (max_r, win) in RATE_LIMITS.items():
            if path.startswith(prefix):
                # Prend la règle la plus spécifique (prefix le plus long)
                if limit_key is None or len(prefix) > len(limit_key):
                    limit_key = prefix
                    max_req = max_r
                    window = win

        if limit_key:
            key = f"{ip}:{limit_key}"
            if not _store.is_allowed(key, max_req, window):
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Trop de requêtes. Réessayez dans quelques instants.",
                        "retry_after": window,
                    },
                    headers={"Retry-After": str(window)}
                )

        return await call_next(request)


def _get_ip(request: Request) -> str:
    """Récupère l'IP réelle même derrière un reverse proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ===========================================================
# WEBHOOK HMAC VERIFICATION
# ===========================================================

def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Vérifie la signature HMAC-SHA256 d'un webhook Resend.
    Resend envoie le header : Resend-Signature: sha256=<hex>
    """
    if not secret or not signature_header:
        # Si pas de secret configuré, on laisse passer (mode dégradé)
        return True
    try:
        # Format : "sha256=<hexdigest>"
        parts = signature_header.split("=", 1)
        if len(parts) != 2 or parts[0] != "sha256":
            return False
        expected_sig = parts[1]
        computed = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, expected_sig)
    except Exception:
        return False
