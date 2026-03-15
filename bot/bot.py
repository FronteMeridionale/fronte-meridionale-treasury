import os
import logging
import time
import threading
from typing import Dict
import requests
import telebot
from telebot import types

# Logging configuration
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format=log_format)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "").rstrip("/")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN non impostato")

if not BACKEND_BASE_URL:
    raise RuntimeError("BACKEND_BASE_URL non impostato")

# Configuration
BACKEND_REQUEST_TIMEOUT = int(os.getenv("BACKEND_REQUEST_TIMEOUT", "30"))
DEBOUNCE_WINDOW_SECONDS = int(os.getenv("DEBOUNCE_WINDOW_SECONDS", "5"))

bot = telebot.TeleBot(TOKEN)

CHANNEL_ID = "@FRONTE_MERIDIONALE"
AUTHORIZED_USERS = {1685607625}

# Quote disponibili (20/40/60/80)
DONATION_AMOUNTS = {
    "20": "Dona 20€",
    "40": "Dona 40€",
    "60": "Dona 60€",
    "80": "Dona 80€",
}

# Metodi di pagamento
PAYMENT_METHODS = {
    "card": "💳 Carta",
    "bank": "🏦 Bonifico",
}

# Stato: traccia quale utente sta scegliendo metodo e importo
pending_payment_method: Dict[int, str] = {}

_debounce_lock = threading.Lock()
_debounce_tracker: Dict[str, float] = {}


# ============================================================================
# UTILITY: Debounce Protection
# ============================================================================
def _make_debounce_key(chat_id: int, amount: str, method: str) -> str:
    """Genera debounce key da chat_id, amount e method."""
    return f"{chat_id}:{amount}:{method}"


def _is_debounced(chat_id: int, amount: str, method: str) -> bool:
    """
    Verifica se una richiesta (chat_id, amount, method) è in debounce.

    Returns:
        True se in debounce, False altrimenti
    """
    now = time.time()
    debounce_key = _make_debounce_key(chat_id, amount, method)

    with _debounce_lock:
        if debounce_key in _debounce_tracker:
            last_request = _debounce_tracker[debounce_key]
            if now - last_request < DEBOUNCE_WINDOW_SECONDS:
                logger.debug(f"DEBOUNCE_ACTIVE: debounce_key={debounce_key}")
                return True

        _debounce_tracker[debounce_key] = now

        if len(_debounce_tracker) > 10000:
            oldest_key = min(_debounce_tracker.keys(), key=lambda k: _debounce_tracker[k])
            del _debounce_tracker[oldest_key]
            logger.debug(f"DEBOUNCE_CLEANUP: removed key={oldest_key}")

    return False


def _format_amount(amount: str) -> str:
    """Formatta importo per visualizzazione."""
    try:
        amount_float = float(amount)
        if amount_float == int(amount_float):
            return f"{int(amount_float)}"
        formatted = f"{amount_float:.10f}".rstrip("0").rstrip(".")
        return formatted
    except (ValueError, TypeError):
        return amount


def _get_error_message(error_code: str, retry_after: int = 0) -> str:
    """Genera messaggio utente in base al codice di errore backend."""
    if error_code == "RATE_LIMITED":
        return (
            f"⏱️ Troppe richieste. Attendi {retry_after}s e riprova.\n\n"
            f"Il nostro backend ha un limite di richieste per proteggere il servizio."
        )
    if error_code == "UPSTREAM_RATE_LIMITED":
        return (
            f"⏱️ Il servizio Transak è momentaneamente sovraccarico. "
            f"Attendi {retry_after}s e riprova."
        )
    if error_code == "UPSTREAM_TIMEOUT":
        return (
            "⏱️ La richiesta ha impiegato troppo tempo.\n\n"
            "Per favore riprova."
        )
    if error_code == "UPSTREAM_CONNECTION_ERROR":
        return (
            "🔌 Errore di connessione con il servizio di pagamento.\n\n"
            "Per favore riprova."
        )
    if error_code == "UPSTREAM_AUTH_ERROR":
        return (
            "❌ Errore di autenticazione con il servizio.\n\n"
            "Per favore contatta l'amministratore."
        )
    if error_code == "INVALID_REQUEST":
        return (
            "❌ Richiesta non valida.\n\n"
            "Per favore verifica i dati inseriti e riprova."
        )
    if error_code == "UPSTREAM_HTTP_ERROR":
        return (
            "❌ Il servizio di pagamento ha restituito un errore.\n\n"
            "Per favore riprova tra qualche istante."
        )
    if error_code == "UPSTREAM_INVALID_RESPONSE":
        return (
            "❌ Risposta non valida dal servizio di pagamento.\n\n"
            "Per favore riprova tra qualche istante."
        )
    if error_code == "INTERNAL_ERROR":
        return (
            "❌ Errore interno del servizio.\n\n"
            "Per favore riprova più tardi o contatta l'amministratore."
        )
    if error_code == "NOT_IMPLEMENTED":
        return (
            "⚠️ Il metodo di pagamento selezionato non è ancora disponibile.\n\n"
            "Usa il metodo Carta oppure riprova più tardi."
        )
    # UNKNOWN_ERROR e qualsiasi codice non gestito esplicitamente
    return (
        "❌ Errore nel servizio di donazione.\n\n"
        "Per favore riprova più tardi."
    )


# ============================================================================
# UI TEXT
# ============================================================================
def testo_centrale():
    return (
        "⚑ FRONTE MERIDIONALE ⚑\n\n"
        "Il Fronte Meridionale nasce con l'obiettivo di costruire "
        "un'organizzazione politica autonoma, moderna e radicata sul territorio, "
        "capace di rappresentare realmente gli interessi del Mezzogiorno.\n\n"
        "Per troppo tempo il Mezzogiorno è stato amministrato da strutture politiche "
        "nazionali che hanno limitato ogni reale alternativa di sviluppo, "
        "sottraendo risorse ai territori e alimentando sistemi decisionali "
        "poco trasparenti.\n\n"
        "Il nostro obiettivo è superare questo modello costruendo "
        "una nuova realtà politica fondata sulla partecipazione dei cittadini "
        "e sulla responsabilità nella gestione delle risorse pubbliche.\n\n"
        "TESORERIA PUBBLICA E VERIFICABILE\n\n"
        "Ogni donazione è consultabile da chiunque.\n\n"
        "SOSTIENI IL FRONTE MERIDIONALE"
    )


def tastiera_importi():
    """Tastiera con quote fisse (20/40/60/80) - Step 1."""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("Dona 20€", callback_data="amount_20"),
        types.InlineKeyboardButton("Dona 40€", callback_data="amount_40"),
        types.InlineKeyboardButton("Dona 60€", callback_data="amount_60"),
        types.InlineKeyboardButton("Dona 80€", callback_data="amount_80"),
    ]
    keyboard.add(*buttons)
    return keyboard


def tastiera_metodo_pagamento(amount: str):
    """Tastiera per scelta metodo pagamento (Carta / Bonifico) - Step 2."""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💳 Carta", callback_data=f"method_card_{amount}"),
        types.InlineKeyboardButton("🏦 Bonifico", callback_data=f"method_bank_{amount}"),
    )
    return keyboard


# ============================================================================
# BACKEND HEALTH CHECK
# ============================================================================
def verifica_backend_disponibile() -> bool:
    """Verifica se il backend è disponibile prima di fare richieste."""
    try:
        response = requests.get(f"{BACKEND_BASE_URL}/health", timeout=10)
        is_healthy = response.status_code == 200
        if is_healthy:
            logger.info("BACKEND_HEALTH: OK")
        else:
            logger.warning(f"BACKEND_HEALTH: failed with status {response.status_code}")
        return is_healthy
    except requests.RequestException as e:
        logger.warning(f"BACKEND_HEALTH: connection failed: {e}")
        return False


# ============================================================================
# BACKEND REQUEST
# ============================================================================
def _richiesta_link_donazione_metodo(chat_id: int, amount: str, method: str) -> dict:
    """
    Effettua la richiesta al backend per carta o bonifico.
    """
    logger.info(f"REQUEST_BACKEND: chat_id={chat_id}, amount={amount}, method={method}")

    if method == "card":
        endpoint = f"{BACKEND_BASE_URL}/transak/widget-url"
    elif method == "bank":
        endpoint = f"{BACKEND_BASE_URL}/transak/bank-order"
    else:
        raise ValueError(f"Unknown payment method: {method}")

    try:
        response = requests.post(
            endpoint,
            json={
                "fiatAmount": str(amount),
                "fiatCurrency": "EUR",
                "partnerCustomerId": str(chat_id),
            },
            timeout=BACKEND_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.error(f"REQUEST_BACKEND: TIMEOUT for chat_id={chat_id}")
        raise
    except requests.ConnectionError as e:
        logger.error(f"REQUEST_BACKEND: CONNECTION_ERROR for chat_id={chat_id}: {e}")
        raise
    except requests.RequestException as e:
        logger.error(f"REQUEST_BACKEND: REQUEST_ERROR for chat_id={chat_id}: {e}")
        raise

    if response.status_code != 200:
        logger.error(
            f"REQUEST_BACKEND_HTTP_ERROR: chat_id={chat_id}, "
            f"status={response.status_code}"
        )

    try:
        data = response.json()
    except Exception as e:
        logger.error(f"REQUEST_BACKEND: invalid JSON response for chat_id={chat_id}: {e}")
        raise RuntimeError("Invalid JSON response from backend")

    logger.info(f"REQUEST_BACKEND: success={data.get('success')} for chat_id={chat_id}")
    return data


# ============================================================================
# DONATION LINK CREATION
# ============================================================================
def crea_link_donazione(chat_id: int, amount: str, method: str):
    """
    Crea link di donazione (carta via widget) o ordine bancario (bonifico via redirectUrl).
    """
    if _is_debounced(chat_id, amount, method):
        logger.debug(f"DEBOUNCE_BLOCKED: chat_id={chat_id}, amount={amount}, method={method}")
        bot.send_message(
            chat_id,
            "⏳ Richiesta già in corso. Attendi qualche secondo..."
        )
        return

    logger.info(f"DONATION_FLOW_START: chat_id={chat_id}, amount={amount}, method={method}")

    if not verifica_backend_disponibile():
        logger.warning(f"DONATION_FLOW: backend unavailable for chat_id={chat_id}")
        bot.send_message(
            chat_id,
            "⚠️ Il servizio di donazione è temporaneamente non disponibile.\n\n"
            "Per favore riprova tra pochi istanti."
        )
        return

    try:
        data = _richiesta_link_donazione_metodo(chat_id, amount, method)

        if not data.get("success"):
            error_code = data.get("error", "UNKNOWN_ERROR")
            details = data.get("details", "")

            logger.error(
                f"DONATION_FLOW: backend error for chat_id={chat_id}, "
                f"error_code={error_code}, details={details}"
            )

            error_message = _get_error_message(error_code, data.get("retry_after", 0))
            bot.send_message(chat_id, error_message)
            return

        if method == "card":
            widget_url = data.get("widgetUrl")
            if not widget_url:
                logger.error(f"DONATION_FLOW: no widgetUrl in response for chat_id={chat_id}")
                bot.send_message(
                    chat_id,
                    "❌ Errore nella creazione del link di donazione.\n\n"
                    "Per favore riprova."
                )
                return

            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("Apri Transak", url=widget_url))

            amount_formatted = _format_amount(amount)
            bot.send_message(
                chat_id,
                f"💳 Procedi con la donazione di {amount_formatted}€ tramite il pulsante qui sotto:",
                reply_markup=keyboard
            )
            logger.info(f"DONATION_FLOW_SUCCESS: card link sent to chat_id={chat_id}")

        elif method == "bank":
            redirect_url = data.get("redirectUrl")
            order_id = data.get("orderId")

            if not redirect_url or not order_id:
                logger.error(
                    f"DONATION_FLOW: no redirectUrl or orderId in response for chat_id={chat_id}"
                )
                bot.send_message(
                    chat_id,
                    "❌ Errore nella creazione dell'ordine bancario.\n\n"
                    "Per favore riprova."
                )
                return

            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("Completa Pagamento", url=redirect_url)
            )

            amount_formatted = _format_amount(amount)
            bot.send_message(
                chat_id,
                f"🏦 Ordine di bonifico creato per {amount_formatted}€\n\n"
                f"<b>ID Ordine:</b> <code>{order_id}</code>\n\n"
                f"Clicca il pulsante qui sotto per completare il pagamento tramite il tuo conto bancario.\n\n"
                f"<i>Verrai reindirizzato alla tua banca per autenticarti e confermare il trasferimento.</i>",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            logger.info(f"DONATION_FLOW_SUCCESS: bank order with redirectUrl sent to chat_id={chat_id}")

    except requests.Timeout:
        logger.error(f"DONATION_FLOW: TIMEOUT for chat_id={chat_id}")
        bot.send_message(
            chat_id,
            "⏱️ La richiesta ha impiegato troppo tempo.\n\n"
            "Per favore riprova."
        )

    except requests.ConnectionError as e:
        logger.error(f"DONATION_FLOW: CONNECTION_ERROR for chat_id={chat_id}: {e}")
        bot.send_message(
            chat_id,
            "🔌 Errore di connessione.\n\n"
            "Per favore riprova."
        )

    except requests.RequestException as e:
        logger.error(f"DONATION_FLOW: REQUEST_ERROR for chat_id={chat_id}: {e}")
        bot.send_message(
            chat_id,
            "❌ Errore nella richiesta al servizio.\n\n"
            "Per favore riprova."
        )

    except RuntimeError as e:
        logger.error(f"DONATION_FLOW: INVALID_RESPONSE for chat_id={chat_id}: {e}")
        bot.send_message(
            chat_id,
            "❌ Errore nella risposta del servizio.\n\n"
            "Per favore riprova."
        )

    except Exception as e:
        logger.exception(f"DONATION_FLOW: UNEXPECTED_ERROR for chat_id={chat_id}: {e}")
        bot.send_message(
            chat_id,
            "❌ Errore interno del servizio.\n\n"
            "Per favore riprova."
        )


# ============================================================================
# BOT HANDLERS
# ============================================================================
@bot.message_handler(commands=["start"])
def start(message):
    """Gestore comando /start."""
    chat_id = message.chat.id
    logger.info(f"HANDLER_START: chat_id={chat_id}")

    if chat_id in pending_payment_method:
        del pending_payment_method[chat_id]

    bot.send_message(
        chat_id,
        testo_centrale(),
        reply_markup=tastiera_importi()
    )


@bot.callback_query_handler(func=lambda call: True)
def risposta_pulsanti(call):
    """Gestore callback pulsanti donazione (Step 1: Importo, Step 2: Metodo)."""
    chat_id = call.message.chat.id
    callback_data = call.data

    bot.answer_callback_query(call.id)

    logger.info(f"HANDLER_CALLBACK: chat_id={chat_id}, callback_data={callback_data}")

    if callback_data.startswith("amount_"):
        amount = callback_data.replace("amount_", "")
        if amount in DONATION_AMOUNTS:
            logger.debug(f"HANDLER_CALLBACK: amount selected, amount={amount}, chat_id={chat_id}")
            pending_payment_method[chat_id] = amount
            bot.send_message(
                chat_id,
                "Scegli il metodo di pagamento:",
                reply_markup=tastiera_metodo_pagamento(amount)
            )
        return

    if callback_data.startswith("method_"):
        parts = callback_data.split("_")
        if len(parts) >= 3:
            method = parts[1]
            amount = "_".join(parts[2:])

            if chat_id in pending_payment_method and pending_payment_method[chat_id] == amount:
                if method in PAYMENT_METHODS:
                    logger.debug(
                        f"HANDLER_CALLBACK: method selected, method={method}, amount={amount}, chat_id={chat_id}"
                    )
                    del pending_payment_method[chat_id]
                    crea_link_donazione(chat_id, amount, method)
        return


@bot.message_handler(commands=["post"])
def post_canale(message):
    """Gestore comando /post per amministratori."""
    user_id = message.from_user.id
    logger.info(f"HANDLER_POST: user_id={user_id}")

    if user_id not in AUTHORIZED_USERS:
        logger.warning(f"HANDLER_POST: unauthorized user_id={user_id}")
        bot.reply_to(message, "Non sei autorizzato.")
        return

    testo = message.text.replace("/post", "", 1).strip()

    if testo == "":
        bot.reply_to(message, "Inserisci il testo dopo /post")
        return

    try:
        bot.send_message(CHANNEL_ID, testo)
        bot.reply_to(message, "Messaggio pubblicato nel canale.")
        logger.info(f"HANDLER_POST: message posted by user_id={user_id}")
    except Exception as e:
        logger.error(f"HANDLER_POST: failed to post message: {e}")
        bot.reply_to(message, "Errore nella pubblicazione del messaggio.")


@bot.message_handler(commands=["id"])
def id_utente(message):
    """Gestore comando /id per ottenere user ID."""
    user_id = message.from_user.id
    logger.debug(f"HANDLER_ID: user_id={user_id}")
    bot.reply_to(message, f"Il tuo user ID è: {user_id}")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    logger.info("STARTUP: bot starting...")
    bot.remove_webhook()
    logger.info("STARTUP: webhook removed, starting polling...")
    bot.infinity_polling(skip_pending=True)
