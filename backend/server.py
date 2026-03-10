"""
Flask backend gateway for the Fronte Meridionale Transak integration.

Exposes a single endpoint:

    POST /transak/widget-url
        Generates a Transak widget URL that pre-fills the treasury wallet
        address so users cannot redirect funds to an arbitrary address.

    GET /health
        Simple liveness probe.
"""

import time
import traceback
import uuid
from typing import Optional

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pydantic import ValidationError

import backend.config as cfg
from backend.logger import logger
from backend.models import ErrorResponse, WidgetUrlRequest, WidgetUrlResponse

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

CORS(app, origins=cfg.CORS_ALLOWED_ORIGINS)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ── Token cache ───────────────────────────────────────────────────────────────

_partner_token_cache: dict = {
    "token": None,
    "expires_at": 0.0,
}

# ── Service functions ─────────────────────────────────────────────────────────


def get_partner_access_token(force_refresh: bool = False) -> str:
    """Obtain a Transak partner access token, using a local cache.

    The token is refreshed automatically when it is about to expire or when
    *force_refresh* is ``True`` (e.g. after a 401 response).

    Args:
        force_refresh: When ``True``, bypass the cache and always request a
            fresh token from Transak.

    Returns:
        A valid partner access token string.

    Raises:
        requests.HTTPError: If the Transak auth endpoint returns a non-2xx
            status code.
        RuntimeError: If the response body does not contain a token.
    """
    now = time.time()

    if (
        not force_refresh
        and _partner_token_cache["token"]
        and now < _partner_token_cache["expires_at"]
    ):
        logger.debug("Using cached partner access token")
        return _partner_token_cache["token"]

    logger.info("Requesting new partner access token from Transak")

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-secret": cfg.TRANSAK_API_SECRET,
    }

    payload = {"apiKey": cfg.TRANSAK_API_KEY}

    response = requests.post(
        cfg.TRANSAK_REFRESH_TOKEN_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    access_token = (
        data.get("accessToken")
        or data.get("token")
        or data.get("jwt")
        or data.get("data", {}).get("accessToken")
    )

    if not access_token:
        raise RuntimeError(f"Access token not found in Transak response: {data}")

    _partner_token_cache["token"] = access_token
    _partner_token_cache["expires_at"] = now + cfg.TOKEN_CACHE_TTL_SECONDS

    logger.info("Partner access token obtained and cached")
    return access_token


def build_widget_payload(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str],
) -> dict:
    """Build the JSON payload for the Transak widget-url API call.

    Args:
        fiat_amount: Optional fiat amount to pre-fill in the widget.
        fiat_currency: ISO 4217 currency code (e.g. ``"EUR"``).
        partner_customer_id: Optional partner customer identifier.
        partner_order_id: Optional partner order identifier.

    Returns:
        A dict with a ``widgetParams`` key ready to be sent to Transak.
    """
    widget_params: dict = {
        "apiKey": cfg.TRANSAK_API_KEY,
        "referrerDomain": cfg.REFERRER_DOMAIN,
        "productsAvailed": "BUY",
        "cryptoCurrencyCode": "MATIC",
        "network": "polygon",
        "walletAddress": cfg.TREASURY_WALLET,
        "disableWalletAddressForm": True,
        "sessionId": str(uuid.uuid4()),
    }

    if fiat_amount:
        widget_params["fiatAmount"] = fiat_amount
        widget_params["fiatCurrency"] = fiat_currency

    if partner_customer_id:
        widget_params["partnerCustomerId"] = partner_customer_id

    if partner_order_id:
        widget_params["partnerOrderId"] = partner_order_id

    logger.debug("Widget payload built: %s", widget_params)
    return {"widgetParams": widget_params}


def create_widget_url(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str],
) -> str:
    """Generate a Transak widget URL via the Partner API.

    Retries once with a fresh token if the first request returns HTTP 401.

    Args:
        fiat_amount: Optional fiat amount to pre-fill.
        fiat_currency: ISO 4217 currency code.
        partner_customer_id: Optional partner customer identifier.
        partner_order_id: Optional partner order identifier.

    Returns:
        The Transak widget URL string.

    Raises:
        requests.HTTPError: If Transak returns a non-2xx error.
        RuntimeError: If the response does not contain a widget URL.
    """
    token = get_partner_access_token()

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
    }

    payload = build_widget_payload(
        fiat_amount=fiat_amount,
        fiat_currency=fiat_currency,
        partner_customer_id=partner_customer_id,
        partner_order_id=partner_order_id,
    )

    logger.info("Requesting widget URL from Transak (url=%s)", cfg.TRANSAK_CREATE_WIDGET_URL)

    response = requests.post(
        cfg.TRANSAK_CREATE_WIDGET_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    if response.status_code == 401:
        logger.warning("Received 401 from Transak; refreshing token and retrying")
        token = get_partner_access_token(force_refresh=True)
        headers["authorization"] = f"Bearer {token}"
        response = requests.post(
            cfg.TRANSAK_CREATE_WIDGET_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

    response.raise_for_status()
    data = response.json()

    widget_url = data.get("widgetUrl") or data.get("data", {}).get("widgetUrl")

    if not widget_url:
        raise RuntimeError(f"widgetUrl not found in Transak response: {data}")

    logger.info("Widget URL successfully generated")
    return widget_url


# ── Routes ────────────────────────────────────────────────────────────────────


@app.route("/health", methods=["GET"])
def health():
    """Liveness probe endpoint.

    Returns:
        JSON ``{"ok": true}`` with HTTP 200.
    """
    return jsonify({"ok": True})


@app.route("/transak/widget-url", methods=["POST"])
@limiter.limit(f"{cfg.RATE_LIMIT_PER_MINUTE} per minute")
def transak_widget_url():
    """Generate a Transak widget URL for a donation to the treasury wallet.

    The wallet address is pre-filled and locked; users cannot change it.

    Request body (JSON, all fields optional):
        fiatAmount (str): Amount in fiat currency (e.g. ``"50"``).
        fiatCurrency (str): ISO 4217 code, default ``"EUR"``.
        partnerCustomerId (str): Identifier for the donor.
        partnerOrderId (str): Identifier for the order.

    Returns:
        200: ``WidgetUrlResponse`` JSON on success.
        400: ``ErrorResponse`` JSON when request body fails validation.
        429: Rate limit exceeded.
        502: ``ErrorResponse`` JSON when Transak returns an HTTP error.
        500: ``ErrorResponse`` JSON for unexpected errors.
    """
    logger.info("POST /transak/widget-url — remote=%s", request.remote_addr)

    # ── Validate input ────────────────────────────────────────────────────────
    try:
        body = WidgetUrlRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        logger.warning("Input validation failed: %s", exc)
        return (
            jsonify(
                ErrorResponse(
                    error="VALIDATION_ERROR",
                    details=exc.json(),
                ).model_dump()
            ),
            400,
        )

    # ── Call Transak ──────────────────────────────────────────────────────────
    try:
        widget_url = create_widget_url(
            fiat_amount=body.fiatAmount,
            fiat_currency=body.fiatCurrency,
            partner_customer_id=body.partnerCustomerId,
            partner_order_id=body.partnerOrderId,
        )

        return jsonify(
            WidgetUrlResponse(
                widgetUrl=widget_url,
                walletAddress=cfg.TREASURY_WALLET,
            ).model_dump()
        )

    except requests.HTTPError as exc:
        details = ""
        try:
            details = exc.response.text
        except Exception:
            details = str(exc)

        logger.error("Transak HTTP error: %s | details: %s", exc, details)
        return (
            jsonify(
                ErrorResponse(error="HTTP_ERROR", details=details).model_dump()
            ),
            502,
        )

    except Exception as exc:
        logger.error(
            "Unexpected error in /transak/widget-url: %s\n%s",
            exc,
            traceback.format_exc(),
        )
        return (
            jsonify(
                ErrorResponse(
                    error="INTERNAL_ERROR",
                    details=str(exc),
                ).model_dump()
            ),
            500,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(
        "Starting Transak gateway (env=%s, host=%s, port=%s, debug=%s)",
        cfg.ENVIRONMENT,
        cfg.HOST,
        cfg.PORT,
        cfg.DEBUG,
    )
    app.run(host=cfg.HOST, port=cfg.PORT, debug=cfg.DEBUG)
