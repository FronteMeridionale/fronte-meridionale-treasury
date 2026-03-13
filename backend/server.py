import os
import time
import uuid
import logging
import threading
from typing import Optional, Dict, Tuple

import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

# Logging configuration
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format=log_format)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
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

# Resilience configuration
BACKEND_REQUEST_TIMEOUT = int(os.getenv("BACKEND_REQUEST_TIMEOUT", "60"))
WIDGET_URL_RATE_LIMIT_PER_MINUTE = int(os.getenv("WIDGET_URL_RATE_LIMIT_PER_MINUTE", "10"))
WIDGET_URL_CACHE_TTL_SECONDS = int(os.getenv("WIDGET_URL_CACHE_TTL_SECONDS", "300"))
TRANSAK_RETRY_ON_429_ATTEMPTS = int(os.getenv("TRANSAK_RETRY_ON_429_ATTEMPTS", "2"))
TRANSAK_RETRY_ON_429_BASE_WAIT = float(os.getenv("TRANSAK_RETRY_ON_429_BASE_WAIT", "1.0"))
TRANSAK_RETRY_ON_429_MAX_WAIT = int(os.getenv("TRANSAK_RETRY_ON_429_MAX_WAIT", "30"))
TOKEN_CACHE_DEFAULT_TTL = int(os.getenv("TOKEN_CACHE_DEFAULT_TTL", "518400"))
RATE_LIMIT_TRACKER_MAX_ENTRIES = 10000
WIDGET_CACHE_MAX_ENTRIES = 1000

# ============================================================================
# GLOBAL STATE: Token Cache
# ============================================================================
_partner_token_cache = {
    "token": None,
    "expires_at": 0,
}
_token_cache_lock = threading.Lock()

# ============================================================================
# GLOBAL STATE: Rate Limiting
# ============================================================================
_rate_limit_tracker: Dict[str, list] = {}
_rate_limit_lock = threading.Lock()

# ============================================================================
# GLOBAL STATE: Widget URL Cache
# ============================================================================
_widget_url_cache: Dict[str, Tuple[str, float]] = {}
_widget_cache_lock = threading.Lock()

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================
class UpstreamRateLimitedError(Exception):
    """Segnala che Transak ha restituito 429."""
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


# ============================================================================
# UTILITY: Rate Limiting
# ============================================================================
def _get_client_ip() -> str:
    """Estrae l'IP del client dalla request, considerando X-Forwarded-For."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or "unknown"


def _check_rate_limit(client_ip: str) -> Tuple[bool, Optional[int]]:
    """
    Verifica se il client ha superato il limite di richieste.

    Returns:
        (allowed, retry_after_seconds)
        - allowed=True se la richiesta è permessa
        - retry_after_seconds=secondi da attendere se denied
    """
    now = time.time()
    window_start = now - 60

    with _rate_limit_lock:
        if client_ip not in _rate_limit_tracker:
            _rate_limit_tracker[client_ip] = []

        _rate_limit_tracker[client_ip] = [
            ts for ts in _rate_limit_tracker[client_ip]
            if ts > window_start
        ]

        if len(_rate_limit_tracker[client_ip]) >= WIDGET_URL_RATE_LIMIT_PER_MINUTE:
            oldest_request = _rate_limit_tracker[client_ip][0]
            retry_after = int(60 - (now - oldest_request)) + 1
            logger.warning(
                f"RATE_LIMIT_EXCEEDED: client_ip={client_ip}, "
                f"requests_in_window={len(_rate_limit_tracker[client_ip])}, "
                f"retry_after={retry_after}s"
            )
            return False, retry_after

        _rate_limit_tracker[client_ip].append(now)

        if len(_rate_limit_tracker) > RATE_LIMIT_TRACKER_MAX_ENTRIES:
            oldest_ip = min(
                _rate_limit_tracker.keys(),
                key=lambda ip: min(_rate_limit_tracker[ip]) if _rate_limit_tracker[ip] else now
            )
            del _rate_limit_tracker[oldest_ip]
            logger.debug(f"RATE_LIMIT_CLEANUP: removed ip={oldest_ip}")

    return True, None


# ============================================================================
# UTILITY: Widget URL Cache
# ============================================================================
def _make_cache_key(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str]
) -> str:
    """Genera cache key per widget URL."""
    return f"{fiat_amount}:{fiat_currency}:{partner_customer_id}:{partner_order_id}"


def _get_cached_widget_url(cache_key: str) -> Optional[str]:
    """Ottiene widget URL dalla cache se valido."""
    with _widget_cache_lock:
        if cache_key in _widget_url_cache:
            url, expires_at = _widget_url_cache[cache_key]
            if time.time() < expires_at:
                logger.debug(f"WIDGET_CACHE_HIT: cache_key={cache_key}")
                return url
            del _widget_url_cache[cache_key]
            logger.debug(f"WIDGET_CACHE_EXPIRED: cache_key={cache_key}")
    return None


def _set_cached_widget_url(cache_key: str, url: str):
    """Salva widget URL in cache con TTL."""
    expires_at = time.time() + WIDGET_URL_CACHE_TTL_SECONDS

    with _widget_cache_lock:
        _widget_url_cache[cache_key] = (url, expires_at)

        if len(_widget_url_cache) > WIDGET_CACHE_MAX_ENTRIES:
            oldest_key = min(
                _widget_url_cache.keys(),
                key=lambda k: _widget_url_cache[k][1]
            )
            del _widget_url_cache[oldest_key]
            logger.debug(f"WIDGET_CACHE_CLEANUP: removed key={oldest_key}")

    logger.debug(
        f"WIDGET_CACHE_SET: cache_key={cache_key}, ttl={WIDGET_URL_CACHE_TTL_SECONDS}s"
    )


# ============================================================================
# UTILITY: Input Validation
# ============================================================================
def _validate_input(fiat_amount: Optional[str], fiat_currency: str) -> Optional[str]:
    """
    Valida input per widget URL request.

    Returns:
        Error message se validazione fallisce, None se OK
    """
    if not fiat_currency or len(fiat_currency) != 3:
        return "fiatCurrency must be a 3-letter code (e.g., 'EUR')"

    if fiat_amount is not None:
        try:
            amount_float = float(fiat_amount)
            if amount_float <= 0:
                return "fiatAmount must be positive"
        except (ValueError, TypeError):
            return "fiatAmount must be a valid number"

    return None


# ============================================================================
# TOKEN MANAGEMENT: Caching with Thread-Safety
# ============================================================================
def get_partner_access_token(force_refresh: bool = False) -> str:
    """Ottiene il token di accesso a Transak con caching e thread-safety."""
    now = time.time()

    with _token_cache_lock:
        if (
            not force_refresh
            and _partner_token_cache["token"]
            and now < _partner_token_cache["expires_at"]
        ):
            logger.debug("TOKEN_CACHED: using cached Transak token")
            return _partner_token_cache["token"]

    logger.info("TOKEN_REFRESH: requesting new Transak access token")

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
    except requests.Timeout:
        logger.error("TOKEN_ERROR: timeout while refreshing Transak token")
        raise
    except requests.ConnectionError as e:
        logger.error(f"TOKEN_ERROR: connection error while refreshing token: {e}")
        raise
    except requests.RequestException as e:
        logger.error(f"TOKEN_ERROR: failed to refresh Transak token: {e}")
        raise

    try:
        data = response.json()
    except Exception as e:
        logger.error(f"TOKEN_ERROR: invalid JSON in token response: {e}")
        raise RuntimeError("Invalid JSON response from Transak token endpoint")

    access_token = (
        data.get("accessToken")
        or data.get("token")
        or data.get("jwt")
        or data.get("data", {}).get("accessToken")
    )

    if not access_token:
        error_msg = f"Access token not found in response: {data}"
        logger.error(f"TOKEN_ERROR: {error_msg}")
        raise RuntimeError(error_msg)

    expires_in = (
        data.get("expiresIn")
        or data.get("expires_in")
        or data.get("data", {}).get("expiresIn")
        or data.get("data", {}).get("expires_in")
    )

    if expires_in:
        try:
            ttl = int(expires_in)
        except (ValueError, TypeError):
            ttl = TOKEN_CACHE_DEFAULT_TTL
    else:
        ttl = TOKEN_CACHE_DEFAULT_TTL

    with _token_cache_lock:
        _partner_token_cache["token"] = access_token
        _partner_token_cache["expires_at"] = now + ttl

    logger.info(f"TOKEN_REFRESHED: Transak token refreshed successfully, ttl={ttl}s")

    return access_token


# ============================================================================
# WIDGET PAYLOAD BUILDER
# ============================================================================
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


# ============================================================================
# TRANSAK WIDGET URL CREATION
# ============================================================================
def _refresh_token_on_401(token: str, headers: dict) -> str:
    """Refresh token se necessario e ritorna nuovo token."""
    logger.warning("UPSTREAM_AUTH_ERROR: token unauthorized, refreshing")
    new_token = get_partner_access_token(force_refresh=True)
    headers["access-token"] = new_token
    return new_token


def _handle_429_retry(attempt: int, response: requests.Response) -> Tuple[Optional[float], int]:
    """
    Gestisce retry su 429 con exponential backoff.

    Returns:
        (wait_time in secondi se deve ritentare, retry_after_value)
        - wait_time=None se deve abbandonare

    Raises:
        UpstreamRateLimitedError se max retries raggiunto
    """
    if attempt >= TRANSAK_RETRY_ON_429_ATTEMPTS - 1:
        retry_after_header = response.headers.get('Retry-After')
        retry_after_value = 30

        if retry_after_header:
            try:
                retry_after_value = int(retry_after_header)
            except ValueError:
                retry_after_value = 30
        else:
            retry_after_value = max(int(TRANSAK_RETRY_ON_429_BASE_WAIT), 30)

        logger.error(
            f"UPSTREAM_RATE_LIMITED: max retries exceeded, retry_after={retry_after_value}s"
        )
        raise UpstreamRateLimitedError(
            "Transak rate limited, max retries exceeded",
            retry_after=retry_after_value
        )

    wait_time = min(
        TRANSAK_RETRY_ON_429_BASE_WAIT * (2 ** attempt),
        TRANSAK_RETRY_ON_429_MAX_WAIT
    )

    retry_after_header = response.headers.get('Retry-After')
    if retry_after_header:
        try:
            wait_time = min(int(retry_after_header), TRANSAK_RETRY_ON_429_MAX_WAIT)
        except ValueError:
            pass

    retry_after_value = int(wait_time)

    logger.warning(
        f"UPSTREAM_RATE_LIMITED: attempt={attempt+1}, "
        f"waiting {wait_time}s before retry"
    )
    return wait_time, retry_after_value


def create_widget_url(
    fiat_amount: Optional[str],
    fiat_currency: str,
    partner_customer_id: Optional[str],
    partner_order_id: Optional[str],
) -> str:
    """
    Crea l'URL del widget Transak con retry su 401 e 429.

    Presuppone che input sia già validato.

    Raises:
        UpstreamRateLimitedError: se Transak restituisce 429
        requests.Timeout: se timeout
        requests.ConnectionError: se connessione fallisce
        requests.HTTPError: se HTTP error
        RuntimeError: se risposta invalida
    """
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

    logger.info(f"REQUEST_WIDGET_URL: amount={fiat_amount}, currency={fiat_currency}")

    for attempt in range(TRANSAK_RETRY_ON_429_ATTEMPTS):
        try:
            response = requests.post(
                TRANSAK_CREATE_WIDGET_URL,
                headers=headers,
                json=payload,
                timeout=BACKEND_REQUEST_TIMEOUT,
            )
        except requests.Timeout:
            logger.error(f"UPSTREAM_TIMEOUT: attempt={attempt+1}")
            raise
        except requests.ConnectionError as e:
            logger.error(f"UPSTREAM_CONNECTION_ERROR: attempt={attempt+1}, error={e}")
            raise
        except requests.RequestException as e:
            logger.error(f"UPSTREAM_CONNECTION_ERROR: attempt={attempt+1}, error={e}")
            raise

        if response.status_code == 401:
            token = _refresh_token_on_401(token, headers)
            continue

        if response.status_code == 429:
            wait_time, retry_after = _handle_429_retry(attempt, response)
            if wait_time is not None:
                time.sleep(wait_time)
                continue

        if response.status_code >= 400:
            try:
                error_details = response.text
            except Exception:
                error_details = f"HTTP {response.status_code}"
            logger.error(
                f"UPSTREAM_HTTP_ERROR: status={response.status_code}, details={error_details}"
            )
            raise requests.HTTPError(f"HTTP {response.status_code}")

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"UPSTREAM_INVALID_RESPONSE: invalid JSON: {e}")
            raise RuntimeError("Invalid JSON response from Transak")

        widget_url = (
            data.get("widgetUrl")
            or data.get("data", {}).get("widgetUrl")
        )

        if not widget_url:
            error_msg = f"widgetUrl not found in response: {data}"
            logger.error(f"UPSTREAM_INVALID_RESPONSE: {error_msg}")
            raise RuntimeError(error_msg)

        logger.info("TRANSAK_RESPONSE_SUCCESS: widget_url created")
        return widget_url

    raise RuntimeError("Failed to create widget URL after all retries")


# ============================================================================
# FLASK ROUTES
# ============================================================================
@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    logger.debug("HEALTH_CHECK: requested")
    return jsonify({"ok": True})


@app.route("/transak/widget-url", methods=["POST"])
def transak_widget_url():
    """
    Endpoint per generare widget URL Transak.

    Request body:
        - fiatAmount (optional): importo in fiat (numero)
        - fiatCurrency (optional): valuta (EUR, USD, etc.)
        - partnerCustomerId (optional): ID cliente Transak
        - partnerOrderId (optional): ID ordine Transak

    Response (success):
        {
            "success": true,
            "widgetUrl": "https://...",
            "walletAddress": "0x...",
            "network": "polygon",
            "cryptoCurrencyCode": "MATIC"
        }

    Response (error):
        {
            "success": false,
            "error": "ERROR_CODE",
            "details": "error message",
            "retry_after": 30
        }
    """
    try:
        body = request.get_json(silent=True) or {}

        fiat_amount = body.get("fiatAmount")
        fiat_currency = str(body.get("fiatCurrency", "EUR")).upper()
        partner_customer_id = body.get("partnerCustomerId")
        partner_order_id = body.get("partnerOrderId")

        logger.info(
            f"REQUEST_WIDGET_URL: amount={fiat_amount}, "
            f"currency={fiat_currency}, customer_id={partner_customer_id}"
        )

        error_msg = _validate_input(fiat_amount, fiat_currency)
        if error_msg:
            logger.warning(f"INVALID_REQUEST: {error_msg}")
            return jsonify({
                "success": False,
                "error": "INVALID_REQUEST",
                "details": error_msg,
            }), 400

        cache_key = None
        if fiat_amount is not None:
            cache_key = _make_cache_key(
                fiat_amount,
                fiat_currency,
                partner_customer_id,
                partner_order_id
            )
            cached_url = _get_cached_widget_url(cache_key)
            if cached_url:
                logger.info("RESPONSE_SUCCESS: widget URL from cache")
                return jsonify({
                    "success": True,
                    "widgetUrl": cached_url,
                    "walletAddress": TREASURY_WALLET,
                    "network": "polygon",
                    "cryptoCurrencyCode": "MATIC",
                })

        client_ip = _get_client_ip()
        allowed, retry_after = _check_rate_limit(client_ip)
        if not allowed:
            logger.warning(f"RATE_LIMITED: client_ip={client_ip}, retry_after={retry_after}s")
            return jsonify({
                "success": False,
                "error": "RATE_LIMITED",
                "details": f"Too many requests. Wait {retry_after} seconds.",
                "retry_after": retry_after,
            }), 429

        widget_url = create_widget_url(
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            partner_customer_id=partner_customer_id,
            partner_order_id=partner_order_id,
        )

        if cache_key is not None:
            _set_cached_widget_url(cache_key, widget_url)

        response_data = {
            "success": True,
            "widgetUrl": widget_url,
            "walletAddress": TREASURY_WALLET,
            "network": "polygon",
            "cryptoCurrencyCode": "MATIC",
        }

        logger.info("RESPONSE_SUCCESS: widget URL returned")
        return jsonify(response_data)

    except ValueError as e:
        logger.error(f"INVALID_REQUEST: {e}")
        return jsonify({
            "success": False,
            "error": "INVALID_REQUEST",
            "details": str(e),
        }), 400

    except UpstreamRateLimitedError as e:
        logger.error(f"UPSTREAM_RATE_LIMITED: {e}")
        response_data = {
            "success": False,
            "error": "UPSTREAM_RATE_LIMITED",
            "details": "Transak service is rate limited",
        }
        if e.retry_after is not None and e.retry_after > 0:
            response_data["retry_after"] = e.retry_after
        return jsonify(response_data), 429

    except requests.Timeout as e:
        logger.error(f"UPSTREAM_TIMEOUT: {e}")
        return jsonify({
            "success": False,
            "error": "UPSTREAM_TIMEOUT",
            "details": "Transak service did not respond in time",
        }), 504

    except requests.ConnectionError as e:
        logger.error(f"UPSTREAM_CONNECTION_ERROR: {e}")
        return jsonify({
            "success": False,
            "error": "UPSTREAM_CONNECTION_ERROR",
            "details": "Cannot connect to Transak service",
        }), 502

    except requests.HTTPError as e:
        logger.error(f"UPSTREAM_HTTP_ERROR: {e}")
        return jsonify({
            "success": False,
            "error": "UPSTREAM_HTTP_ERROR",
            "details": str(e),
        }), 502

    except RuntimeError as e:
        logger.error(f"UPSTREAM_INVALID_RESPONSE: {e}")
        return jsonify({
            "success": False,
            "error": "UPSTREAM_INVALID_RESPONSE",
            "details": str(e),
        }), 502

    except Exception as e:
        logger.exception(f"INTERNAL_ERROR: {e}")
        return jsonify({
            "success": False,
            "error": "INTERNAL_ERROR",
            "details": str(e),
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"STARTUP: starting backend server on port {port}")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
