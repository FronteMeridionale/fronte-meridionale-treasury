"""
Centralized configuration for the Fronte Meridionale Transak backend.

Supports multiple environments (staging, production) with sensible defaults.
Configuration is loaded from environment variables via python-dotenv.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Environment ──────────────────────────────────────────────────────────────

ENVIRONMENT: str = os.getenv("ENVIRONMENT", "staging")
IS_PRODUCTION: bool = ENVIRONMENT == "production"
DEBUG: bool = not IS_PRODUCTION

# ── Transak credentials ───────────────────────────────────────────────────────

TRANSAK_API_KEY: str = os.getenv("TRANSAK_API_KEY", "")
TRANSAK_API_SECRET: str = os.getenv("TRANSAK_API_SECRET", "")

# Transak API endpoints – differ between staging and production
_STAGING_REFRESH_TOKEN_URL = (
    "https://staging-api.transak.com/api/v2/partners/auth/refresh-token"
)
_PRODUCTION_REFRESH_TOKEN_URL = (
    "https://api.transak.com/api/v2/partners/auth/refresh-token"
)

_STAGING_CREATE_WIDGET_URL = (
    "https://staging-api.transak.com/api/v2/partners/widget-url"
)
_PRODUCTION_CREATE_WIDGET_URL = (
    "https://api.transak.com/api/v2/partners/widget-url"
)

TRANSAK_REFRESH_TOKEN_URL: str = os.getenv(
    "TRANSAK_REFRESH_TOKEN_URL",
    _PRODUCTION_REFRESH_TOKEN_URL if IS_PRODUCTION else _STAGING_REFRESH_TOKEN_URL,
)

TRANSAK_CREATE_WIDGET_URL: str = os.getenv(
    "TRANSAK_CREATE_WIDGET_URL",
    _PRODUCTION_CREATE_WIDGET_URL if IS_PRODUCTION else _STAGING_CREATE_WIDGET_URL,
)

# ── Treasury wallet ───────────────────────────────────────────────────────────

TREASURY_WALLET: str = os.getenv(
    "TREASURY_WALLET",
    "0x57f333c398c9625D84432aBD00871E2d8049cAaC",
)

REFERRER_DOMAIN: str = os.getenv(
    "REFERRER_DOMAIN",
    "https://frontemeridionale.github.io",
)

# ── Token cache ───────────────────────────────────────────────────────────────

# Partner access token TTL in seconds (default: 6 days = 518 400 s)
_TOKEN_CACHE_TTL_DEFAULT = 518_400
TOKEN_CACHE_TTL_SECONDS: int = int(os.getenv("TOKEN_CACHE_TTL_SECONDS", str(_TOKEN_CACHE_TTL_DEFAULT)))

# ── Rate limiting ─────────────────────────────────────────────────────────────

RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

# ── CORS ──────────────────────────────────────────────────────────────────────

# Comma-separated list of allowed origins; defaults to the public website
_default_origins = "https://frontemeridionale.github.io,http://localhost:3000"
CORS_ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

# ── Server ────────────────────────────────────────────────────────────────────

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "5000"))
