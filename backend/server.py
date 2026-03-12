import logging
import os
import threading
import time
import uuid
from typing import Optional

import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
try:
    TRANSAK_REQUEST_TIMEOUT = int(os.getenv("TRANSAK_REQUEST_TIMEOUT", "30"))
except ValueError:
    raise RuntimeError("TRANSAK_REQUEST_TIMEOUT deve essere un numero intero")

_TOKEN_CACHE_TTL = 24 * 60 * 60  # 24 hours

_token_cache_lock = threading.Lock()
_partner_token_cache = {
    "token": None,
    "expires_at": 0,
}


def get_partner_access_token(force_refresh: bool = False) -> str:
    now = time.time()

    with _token_cache_lock:
        if (
            not force_refresh
            and _partner_token_cache["token"]
            and now < _partner_token_cache["expires_at"]
        ):
            return _partner_token_cache["token"]

    logger.info("Recupero partner access token (force_refresh=%s)", force_refresh)

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-secret": TRANSAK_API_SECRET,
    }

    payload = {
        "apiKey": TRANSAK_API_KEY,
    }

    response = requests.post(
        TRANSAK_REFRESH_TOKEN_URL,
        headers=headers,
        json=payload,
        timeout=TRANSAK_REQUEST_TIMEOUT,
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
        raise RuntimeError(f"Access token non trovato nella risposta: {data}")

    with _token_cache_lock:
        _partner_token_cache["token"] = access_token
        _partner_token_cache["expires_at"] = now + _TOKEN_CACHE_TTL
    logger.info("Partner access token aggiornato, scade in %dh", _TOKEN_CACHE_TTL // 3600)

    return access_token


def build_widget_payload(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str],
) -> dict:

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

    logger.info(
        "Creazione widget URL per customer_id=%s amount=%s %s",
        partner_customer_id, fiat_amount, fiat_currency
    )

    response = requests.post(
        TRANSAK_CREATE_WIDGET_URL,
        headers=headers,
        json=payload,
        timeout=TRANSAK_REQUEST_TIMEOUT,
    )

    if response.status_code == 401:
        logger.warning("Token scaduto (401), forzo il refresh e riprovo")
        token = get_partner_access_token(force_refresh=True)
        headers["access-token"] = token

        response = requests.post(
            TRANSAK_CREATE_WIDGET_URL,
            headers=headers,
            json=payload,
            timeout=TRANSAK_REQUEST_TIMEOUT,
        )

    response.raise_for_status()

    data = response.json()

    widget_url = (
        data.get("widgetUrl")
        or data.get("data", {}).get("widgetUrl")
    )

    if not widget_url:
        raise RuntimeError(f"widgetUrl non trovata nella risposta: {data}")

    logger.info("Widget URL creato con successo per customer_id=%s", partner_customer_id)
    return widget_url


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/transak/widget-url", methods=["POST"])
def transak_widget_url():
    try:
        body = request.get_json(silent=True) or {}

        fiat_amount = body.get("fiatAmount")
        fiat_currency = str(body.get("fiatCurrency", "EUR")).upper()
        partner_customer_id = body.get("partnerCustomerId")
        partner_order_id = body.get("partnerOrderId")

        widget_url = create_widget_url(
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            partner_customer_id=partner_customer_id,
            partner_order_id=partner_order_id,
        )

        return jsonify({
            "success": True,
            "widgetUrl": widget_url,
            "walletAddress": TREASURY_WALLET,
            "network": "polygon",
            "cryptoCurrencyCode": "MATIC",
        })

    except requests.HTTPError as e:
        details = ""
        try:
            details = e.response.text
        except Exception:
            details = str(e)

        logger.error("Errore HTTP da Transak: %s | dettagli: %s", e, details)
        return jsonify({
            "success": False,
            "error": "HTTP_ERROR",
            "details": details,
        }), 502

    except Exception as e:
        logger.exception("Errore interno nella creazione del widget URL")
        return jsonify({
            "success": False,
            "error": "INTERNAL_ERROR",
            "details": str(e),
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
