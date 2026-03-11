import os
import requests
import telebot
from telebot import types

TOKEN = os.getenv("BOT_TOKEN")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "").rstrip("/")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN non impostato")

if not BACKEND_BASE_URL:
    raise RuntimeError("BACKEND_BASE_URL non impostato")

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

    btn1 = types.InlineKeyboardButton("Dona 15€", callback_data="donazione_15")
    btn2 = types.InlineKeyboardButton("Dona 30€", callback_data="donazione_30")
    btn3 = types.InlineKeyboardButton("Dona 50€", callback_data="donazione_50")
    btn4 = types.InlineKeyboardButton("Donazione libera", callback_data="donazione_libera")

    keyboard.add(btn1, btn2, btn3, btn4)
    return keyboard


def crea_link_donazione(chat_id: int, amount: str):
    try:
        response = requests.post(
            f"{BACKEND_BASE_URL}/transak/widget-url",
            json={
                "fiatAmount": str(amount),
                "fiatCurrency": "EUR",
                "partnerCustomerId": str(chat_id),
            },
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("success") or not data.get("widgetUrl"):
            bot.send_message(chat_id, "Errore nella creazione del link di donazione.")
            return

        widget_url = data["widgetUrl"]

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("Apri Transak", url=widget_url)
        )

        bot.send_message(
            chat_id,
            f"Procedi con la donazione di {amount}€ tramite il pulsante qui sotto:",
            reply_markup=keyboard
        )

    except requests.RequestException as e:
        bot.send_message(chat_id, f"Errore di connessione al backend: {e}")
    except Exception as e:
        bot.send_message(chat_id, f"Errore interno: {e}")


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

    if call.data == "donazione_15":
        crea_link_donazione(chat_id, "15")

    elif call.data == "donazione_30":
        crea_link_donazione(chat_id, "30")

    elif call.data == "donazione_50":
        crea_link_donazione(chat_id, "50")

    elif call.data == "donazione_libera":
        pending_free_donation.add(chat_id)
        bot.send_message(
            chat_id,
            "Inserisci l'importo che desideri donare in euro. Esempio: 25"
        )

    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.chat.id in pending_free_donation)
def gestisci_donazione_libera(message):
    chat_id = message.chat.id
    testo = message.text.strip().replace(",", ".")

    try:
        amount = float(testo)

        if amount <= 0:
            bot.send_message(chat_id, "Inserisci un importo maggiore di zero.")
            return

        pending_free_donation.discard(chat_id)
        crea_link_donazione(chat_id, str(amount))

    except ValueError:
        bot.send_message(chat_id, "Importo non valido. Inserisci solo un numero, ad esempio: 25")


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


print("Bot in esecuzione...")
bot.remove_webhook()
bot.infinity_polling(skip_pending=True)
