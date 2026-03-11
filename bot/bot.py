import logging
import os
import requests
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO)

# Token del bot preso dalle variabili di ambiente
TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

# URL del backend Flask
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

# Canale dove pubblicare gli aggiornamenti
CHANNEL_ID = "@FRONTE_MERIDIONALE"

# Utenti autorizzati a pubblicare nel canale
AUTHORIZED_USERS = {1685607625}


# ---------- TESTO CENTRALE BOT ----------

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


# ---------- PULSANTI DONAZIONE ----------

def tastiera_donazione():

    keyboard = types.InlineKeyboardMarkup(row_width=2)

    btn1 = types.InlineKeyboardButton("Dona 15€", callback_data="donazione_15")
    btn2 = types.InlineKeyboardButton("Dona 30€", callback_data="donazione_30")
    btn3 = types.InlineKeyboardButton("Dona 50€", callback_data="donazione_50")
    btn4 = types.InlineKeyboardButton("Donazione libera", callback_data="donazione_libera")

    keyboard.add(btn1, btn2, btn3, btn4)

    return keyboard


# ---------- HELPER: OTTIENI LINK DONAZIONE DAL BACKEND ----------

def ottieni_link_donazione(chat_id: int, fiat_amount: str):
    try:
        response = requests.post(
            f"{BACKEND_URL}/transak/widget-url",
            json={
                "fiatAmount": fiat_amount,
                "fiatCurrency": "EUR",
                "partnerCustomerId": str(chat_id),
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("widgetUrl")
    except Exception as e:
        logging.error("Errore nel recupero del link donazione: %s", e)
        return None


# ---------- START BOT ----------

@bot.message_handler(commands=["start"])
def start(message):

    bot.send_message(
        message.chat.id,
        testo_centrale(),
        reply_markup=tastiera_donazione()
    )


# ---------- GESTIONE PULSANTI ----------

IMPORTI = {
    "donazione_15": "15",
    "donazione_30": "30",
    "donazione_50": "50",
}

@bot.callback_query_handler(func=lambda call: True)
def risposta_pulsanti(call):

    chat_id = call.message.chat.id

    if call.data in IMPORTI:
        importo = IMPORTI[call.data]
        bot.send_message(chat_id, f"⏳ Sto generando il link per la donazione di {importo}€...")
        url = ottieni_link_donazione(chat_id, importo)
        if url:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(f"Dona {importo}€ →", url=url))
            bot.send_message(chat_id, f"✅ Clicca il pulsante per completare la donazione di {importo}€:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "❌ Impossibile generare il link di donazione. Riprova più tardi.")

    elif call.data == "donazione_libera":
        msg = bot.send_message(chat_id, "💬 Inserisci l'importo in euro che desideri donare (es: 25):")
        bot.register_next_step_handler(msg, gestisci_importo_libero)


def gestisci_importo_libero(message):
    chat_id = message.chat.id
    testo = message.text.strip().replace("€", "").replace(",", ".").strip()

    try:
        valore = float(testo)
        if valore <= 0:
            raise ValueError("importo non positivo")
        importo = f"{valore:.2f}"
    except ValueError:
        bot.send_message(chat_id, "❌ Importo non valido. Riprova con /start.")
        return

    bot.send_message(chat_id, f"⏳ Sto generando il link per la donazione di {importo}€...")
    url = ottieni_link_donazione(chat_id, importo)
    if url:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(f"Dona {importo}€ →", url=url))
        bot.send_message(chat_id, "✅ Clicca il pulsante per completare la donazione:", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, "❌ Impossibile generare il link di donazione. Riprova più tardi.")


# ---------- COMANDO POST (SOLO ADMIN) ----------

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


# ---------- COMANDO ID ----------

@bot.message_handler(commands=["id"])
def id_utente(message):

    bot.reply_to(message, f"Il tuo user ID è: {message.from_user.id}")


# ---------- AVVIO BOT ----------

print("Bot in esecuzione...")

bot.remove_webhook()

bot.infinity_polling(skip_pending=True)
