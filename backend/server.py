import os
import time
import uuid
import logging
import threading
from typing import Optional

import requests
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Logging configuration
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)

TRANSAK_API_KEY = os.getenv("TRANSAK_API_KEY")
TRANSAK_API_SECRET = os.getenv("TRANSAK_API_SECRET")
TREASURY_WALLET = os.getenv(
    "TREASURY_WALLET",
    "0x57f333c398c9625D84432aBD00871E2d8049cAaC"
)

REFERRER_DOMAIN = os.getenv(
    "REFERRER_DOMAIN",
    "https://frontemeridionale.github.io"
)

TRANSAK_REFRESH_TOKEN_URL = os.getenv("TRANSAK_REFRESH_TOKEN_URL", "")
TRANSAK_CREATE_WIDGET_URL = os.getenv("TRANSAK_CREATE_WIDGET_URL", "")

# Configuration
BACKEND_REQUEST_TIMEOUT = int(os.getenv("BACKEND_REQUEST_TIMEOUT", "60"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
TOKEN_CACHE_TTL_HOURS = int(os.getenv("TOKEN_CACHE_TTL_HOURS", "24"))
CORS_ALLOWED_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "https://frontemeridionale.github.io"
)

# CORS configuration
CORS(app, resources={r"/*": {"origins": CORS_ALLOWED_ORIGINS.split(",")}})

# Rate limiter (in-memory, suitable for single-process; use Redis for multi-worker)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
)

_partner_token_cache = {
    "token": None,
    "expires_at": 0,
}
_token_lock = threading.Lock()


def get_partner_access_token(force_refresh: bool = False) -> str:
    """Ottiene il token di accesso a Transak con caching thread-safe."""
    now = time.time()

    with _token_lock:
        if (
            not force_refresh
            and _partner_token_cache["token"]
            and now < _partner_token_cache["expires_at"]
        ):
            logger.debug("Cache HIT: using cached Transak token")
            return _partner_token_cache["token"]

        logger.info("Cache MISS: requesting new Transak access token")

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-secret": TRANSAK_API_SECRET,
        }

        payload = {
            "apiKey": TRANSAK_API_KEY,
        }

        try:
            response = requests.post(
                TRANSAK_REFRESH_TOKEN_URL,
                headers=headers,
                json=payload,
                timeout=BACKEND_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error refreshing Transak token: {e}")
            raise

        data = response.json()

        access_token = (
            data.get("accessToken")
            or data.get("token")
            or data.get("jwt")
            or data.get("data", {}).get("accessToken")
        )

        if not access_token:
            error_msg = f"Access token non trovato nella risposta: {data}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        _partner_token_cache["token"] = access_token
        _partner_token_cache["expires_at"] = now + (TOKEN_CACHE_TTL_HOURS * 60 * 60)

        logger.info(f"Transak token refreshed successfully (TTL={TOKEN_CACHE_TTL_HOURS}h)")

        return access_token


def build_widget_payload(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str],
) -> dict:
    """Costruisce il payload del widget Transak."""

    widget_params = {
        "apiKey": TRANSAK_API_KEY,
        "referrerDomain": REFERRER_DOMAIN,
        "productsAvailed": "BUY",
        "cryptoCurrencyCode": "MATIC",
        "network": "polygon",
        "walletAddress": TREASURY_WALLET,
        "disableWalletAddressForm": True,
        "sessionId": str(uuid.uuid4()),
    }

    if fiat_amount:
        widget_params["fiatAmount"] = str(fiat_amount)
        widget_params["fiatCurrency"] = fiat_currency

    if partner_customer_id:
        widget_params["partnerCustomerId"] = partner_customer_id

    if partner_order_id:
        widget_params["partnerOrderId"] = partner_order_id

    return {"widgetParams": widget_params}


def create_widget_url(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str],
) -> str:
    """Crea l'URL del widget Transak con retry su 401."""

    token = get_partner_access_token()

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "access-token": token,
    }

    payload = build_widget_payload(
        fiat_amount=fiat_amount,
        fiat_currency=fiat_currency,
        partner_customer_id=partner_customer_id,
        partner_order_id=partner_order_id,
    )

    logger.info(f"Creating widget URL for amount={fiat_amount}, currency={fiat_currency}")

    try:
        response = requests.post(
            TRANSAK_CREATE_WIDGET_URL,
            headers=headers,
            json=payload,
            timeout=BACKEND_REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.error(f"Error creating widget URL: {e}")
        raise

    if response.status_code == 401:
        logger.warning("Got 401 from Transak, refreshing token and retrying")
        token = get_partner_access_token(force_refresh=True)
        headers["access-token"] = token

        try:
            response = requests.post(
                TRANSAK_CREATE_WIDGET_URL,
                headers=headers,
                json=payload,
                timeout=BACKEND_REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.error(f"Error creating widget URL (after token refresh): {e}")
            raise

    response.raise_for_status()

    data = response.json()

    widget_url = (
        data.get("widgetUrl")
        or data.get("data", {}).get("widgetUrl")
    )

    if not widget_url:
        error_msg = f"widgetUrl non trovata nella risposta: {data}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(f"Widget URL created successfully")

    return widget_url


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    logger.debug("Health check requested")
    return jsonify({"ok": True})


@app.route("/transak/widget-url", methods=["POST"])
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE} per minute")
def transak_widget_url():
    """Endpoint per generare widget URL Transak."""
    start_time = time.time()
    try:
        body = request.get_json(silent=True) or {}

        fiat_amount = body.get("fiatAmount")
        fiat_currency = str(body.get("fiatCurrency", "EUR")).upper()
        partner_customer_id = body.get("partnerCustomerId")
        partner_order_id = body.get("partnerOrderId")

        logger.info(
            f"Widget URL request: amount={fiat_amount}, "
            f"currency={fiat_currency}, customer_id={partner_customer_id}"
        )

        widget_url = create_widget_url(
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            partner_customer_id=partner_customer_id,
            partner_order_id=partner_order_id,
        )

        elapsed = time.time() - start_time
        response_data = {
            "success": True,
            "widgetUrl": widget_url,
            "walletAddress": TREASURY_WALLET,
            "network": "polygon",
            "cryptoCurrencyCode": "MATIC",
        }

        logger.info(f"Widget URL response: success=True, elapsed={elapsed:.2f}s")
        return jsonify(response_data)

    except requests.HTTPError as e:
        elapsed = time.time() - start_time
        details = ""
        try:
            details = e.response.text
        except Exception:
            details = str(e)

        logger.error(f"HTTP error creating widget URL: {details}, elapsed={elapsed:.2f}s")
        
        return jsonify({
            "success": False,
            "error": "HTTP_ERROR",
            "details": details,
        }), 502

    except requests.Timeout as e:
        elapsed = time.time() - start_time
        logger.error(f"Timeout creating widget URL: {e}, elapsed={elapsed:.2f}s")
        return jsonify({
            "success": False,
            "error": "TIMEOUT_ERROR",
            "details": "Request timed out",
        }), 504

    except requests.RequestException as e:
        elapsed = time.time() - start_time
        logger.error(f"Request error creating widget URL: {e}, elapsed={elapsed:.2f}s")
        return jsonify({
            "success": False,
            "error": "REQUEST_ERROR",
            "details": str(e),
        }), 502

    except Exception as e:
        elapsed = time.time() - start_time
        logger.exception(f"Unexpected error creating widget URL: {e}, elapsed={elapsed:.2f}s")
        return jsonify({
            "success": False,
            "error": "INTERNAL_ERROR",
            "details": str(e),
        }), 500


@app.errorhandler(429)
def ratelimit_handler(e):
    """Risponde con messaggio amichevole quando il rate limit è superato."""
    logger.warning(f"Rate limit exceeded from {get_remote_address()}: {e.description}")
    return jsonify({
        "success": False,
        "error": "RATE_LIMIT_EXCEEDED",
        "details": "Troppe richieste. Riprova tra qualche secondo.",
    }), 429


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"Starting backend server on port {port}")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )