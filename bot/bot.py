import os
import logging
import requests
import telebot
from telebot import types
from tenacity import retry, stop_after_attempt, wait_exponential

# Logging configuration
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "").rstrip("/")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN non impostato")

if not BACKEND_BASE_URL:
    raise RuntimeError("BACKEND_BASE_URL non impostato")

# Configuration
BACKEND_REQUEST_TIMEOUT = int(os.getenv("BACKEND_REQUEST_TIMEOUT", "60"))
BACKEND_MAX_RETRIES = int(os.getenv("BACKEND_MAX_RETRIES", "3"))
BACKEND_RETRY_BACKOFF = int(os.getenv("BACKEND_RETRY_BACKOFF", "2"))

bot = telebot.TeleBot(TOKEN)

CHANNEL_ID = "@FRONTE_MERIDIONALE"
AUTHORIZED_USERS = {1685607625}

pending_free_donation = set()


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


def tastiera_donazione():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    btn1 = types.InlineKeyboardButton("Dona 20€", callback_data="donazione_20")
    btn2 = types.InlineKeyboardButton("Dona 30€", callback_data="donazione_30")
    btn3 = types.InlineKeyboardButton("Dona 50€", callback_data="donazione_50")
    btn4 = types.InlineKeyboardButton("Donazione libera", callback_data="donazione_libera")

    keyboard.add(btn1, btn2, btn3, btn4)
    return keyboard


def verifica_backend_disponibile():
    """Verifica se il backend è disponibile prima di fare richieste."""
    try:
        response = requests.get(
            f"{BACKEND_BASE_URL}/health",
            timeout=10,
        )
        is_healthy = response.status_code == 200
        if is_healthy:
            logger.info("Backend health check: OK")
        else:
            logger.warning(f"Backend health check failed: status {response.status_code}")
        return is_healthy
    except requests.RequestException as e:
        logger.warning(f"Backend health check failed: {e}")
        return False


@retry(
    stop=stop_after_attempt(BACKEND_MAX_RETRIES),
    wait=wait_exponential(multiplier=BACKEND_RETRY_BACKOFF, min=1, max=10),
    reraise=True,
)
def _richiesta_link_donazione(chat_id: int, amount: str) -> dict:
    """Effettua la richiesta al backend con retry automatico."""
    logger.info(f"Requesting donation link for chat_id={chat_id}, amount={amount}")
    
    response = requests.post(
        f"{BACKEND_BASE_URL}/transak/widget-url",
        json={
            "fiatAmount": str(amount),
            "fiatCurrency": "EUR",
            "partnerCustomerId": str(chat_id),
        },
        timeout=BACKEND_REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    data = response.json()
    
    logger.info(f"Backend response: success={data.get('success')}")
    return data


def crea_link_donazione(chat_id: int, amount: str):
    """Crea link di donazione con gestione robusta degli errori."""
    try:
        # Verifica che il backend sia disponibile
        if not verifica_backend_disponibile():
            bot.send_message(
                chat_id,
                "⚠️ Il servizio di donazione è temporaneamente non disponibile.\n\n"
                "Per favore riprova tra pochi istanti."
            )
            logger.warning(f"Backend unavailable for chat_id={chat_id}")
            return

        # Richiesta con retry
        data = _richiesta_link_donazione(chat_id, amount)

        if not data.get("success") or not data.get("widgetUrl"):
            bot.send_message(
                chat_id,
                "⚠️ Errore nella creazione del link di donazione.\n\n"
                "Per favore riprova."
            )
            logger.error(f"Backend returned error for chat_id={chat_id}: {data}")
            return

        widget_url = data["widgetUrl"]

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("Apri Transak", url=widget_url)
        )

        bot.send_message(
            chat_id,
            f"💳 Procedi con la donazione di {amount}€ tramite il pulsante qui sotto:",
            reply_markup=keyboard
        )
        logger.info(f"Donation link sent to chat_id={chat_id}")

    except requests.Timeout:
        bot.send_message(
            chat_id,
            "⏱️ La richiesta ha impiegato troppo tempo.\n\n"
            "Per favore riprova."
        )
        logger.error(f"Timeout while creating donation link for chat_id={chat_id}")
    
    except requests.ConnectionError as e:
        bot.send_message(
            chat_id,
            "🔌 Errore di connessione.\n\n"
            "Per favore riprova."
        )
        logger.error(f"Connection error for chat_id={chat_id}: {e}")
    
    except requests.RequestException as e:
        bot.send_message(
            chat_id,
            "⚠️ Errore nella richiesta al servizio.\n\n"
            "Per favore riprova."
        )
        logger.error(f"Request exception for chat_id={chat_id}: {e}")
    
    except Exception as e:
        bot.send_message(
            chat_id,
            "⚠️ Errore interno del servizio.\n\n"
            "Per favore riprova."
        )
        logger.exception(f"Unexpected error for chat_id={chat_id}: {e}")


@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        testo_centrale(),
        reply_markup=tastiera_donazione()
    )


@bot.callback_query_handler(func=lambda call: True)
def risposta_pulsanti(call):
    chat_id = call.message.chat.id

    if call.data == "donazione_20":
        crea_link_donazione(chat_id, "20")

    elif call.data == "donazione_30":
        crea_link_donazione(chat_id, "30")

    elif call.data == "donazione_50":
        crea_link_donazione(chat_id, "50")

    elif call.data == "donazione_libera":
        pending_free_donation.add(chat_id)
        bot.send_message(
            chat_id,
            "💰 Inserisci l'importo che desideri donare in euro.\n\nEsempio: 25"
        )

    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.chat.id in pending_free_donation)
def gestisci_donazione_libera(message):
    chat_id = message.chat.id
    testo = message.text.strip().replace(",", ".")

    try:
        amount = float(testo)

        if amount <= 0:
            bot.send_message(chat_id, "❌ Inserisci un importo maggiore di zero.")
            return

        pending_free_donation.discard(chat_id)
        crea_link_donazione(chat_id, str(amount))

    except ValueError:
        bot.send_message(
            chat_id,
            "❌ Importo non valido.\n\nInserisci solo un numero, ad esempio: 25"
        )


@bot.message_handler(commands=["post"])
def post_canale(message):
    user_id = message.from_user.id

    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "Non sei autorizzato.")
        return

    testo = message.text.replace("/post", "", 1).strip()

    if testo == "":
        bot.reply_to(message, "Inserisci il testo dopo /post")
        return

    bot.send_message(CHANNEL_ID, testo)
    bot.reply_to(message, "Messaggio pubblicato nel canale.")


@bot.message_handler(commands=["id"])
def id_utente(message):
    bot.reply_to(message, f"Il tuo user ID è: {message.from_user.id}")


if __name__ == "__main__":
    logger.info("Bot in esecuzione...")
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)