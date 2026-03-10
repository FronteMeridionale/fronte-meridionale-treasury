import telebot
from telebot import types

# Inserisci qui il token del bot
TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

# Canale dove pubblicare gli aggiornamenti
CHANNEL_ID = "@FRONTE_MERIDIONALE"

# Inserisci il tuo user id dopo aver usato /id
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


# ---------- START BOT ----------

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        testo_centrale(),
        reply_markup=tastiera_donazione()
    )


# ---------- GESTIONE PULSANTI ----------

@bot.callback_query_handler(func=lambda call: True)
def risposta_pulsanti(call):

    if call.data == "donazione_15":
        bot.send_message(call.message.chat.id, "Procedi con la donazione di 15€")

    elif call.data == "donazione_30":
        bot.send_message(call.message.chat.id, "Procedi con la donazione di 30€")

    elif call.data == "donazione_50":
        bot.send_message(call.message.chat.id, "Procedi con la donazione di 50€")

    elif call.data == "donazione_libera":
        bot.send_message(call.message.chat.id, "Inserisci l'importo che desideri donare")


# ---------- COMANDO POST (SOLO ADMIN) ----------

@bot.message_handler(commands=['post'])
def post_canale(message):

    user_id = message.from_user.id

    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "Non sei autorizzato.")
        return

    testo = message.text.replace("/post", "").strip()

    if testo == "":
        bot.reply_to(message, "Inserisci il testo dopo /post")
        return

    bot.send_message(CHANNEL_ID, testo)

    bot.reply_to(message, "Messaggio pubblicato nel canale.")


# ---------- COMANDO ID ----------

@bot.message_handler(commands=['id'])
def id_utente(message):

    bot.reply_to(message, f"Il tuo user ID è: {message.from_user.id}")


# ---------- AVVIO BOT ----------

print("Bot in esecuzione...")

bot.remove_webhook()

bot.infinity_polling(skip_pending=True)
