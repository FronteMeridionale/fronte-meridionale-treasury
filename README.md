# Fronte Meridionale Treasury

Tesoreria pubblica del Fronte Meridionale.

## Architettura

```
Sito Fronte Meridionale
        ↓
Bot Telegram Tesoreria
        ↓
Backend Python Flask
        ↓
      Transak
        ↓
Acquisto MATIC su Polygon
        ↓
  Wallet Tesoreria
```

## Stack tecnologico

- **Linguaggio:** Python 3
- **Backend:** Flask (REST API)
- **Pagamenti:** Transak (widget fiat → crypto)
- **Blockchain:** Polygon (token MATIC)
- **Comunicazione:** Telegram Bot API (`pyTelegramBotAPI`)

## Wallet tesoreria

`0x57f333c398c9625D84432aBD00871E2d8049cAaC`

## Cosa abbiamo fatto

- ✅ Sito online
- ✅ Bot Telegram realizzato (`bot/bot.py`)
  - Comando `/start` con testo di presentazione e pulsanti donazione (15€, 30€, 50€, libera)
  - Comando `/post` per pubblicare messaggi nel canale (solo admin)
  - Comando `/id` per ottenere il proprio Telegram ID
- ✅ Backend Flask realizzato (`backend/server.py`)
  - `GET /health` — health check
  - `POST /transak/widget-url` — genera URL widget Transak per la donazione
  - Gestione token partner con cache (refresh automatico ogni 6 giorni)
  - Retry automatico in caso di 401 Unauthorized
- ✅ Integrazione bot → backend
  - Quando l'utente preme un pulsante di donazione, il bot chiama il backend Flask
  - Il backend genera l'URL del widget Transak con l'importo selezionato
  - Il bot invia all'utente il link diretto per completare la donazione

## Cosa dobbiamo fare

- [ ] Persistenza dei dati (database per donazioni e transazioni)
- [ ] Webhook Transak per conferma pagamento avvenuto
- [ ] Notifica admin su Telegram quando arriva una donazione
- [ ] Dashboard pubblica per visualizzare le donazioni ricevute
- [ ] Rate limiting e protezione anti-spam sul backend
- [ ] Disabilitare `debug=True` in produzione (o usare Gunicorn)
- [ ] Logging strutturato per monitoraggio in produzione

## Configurazione

Copia `.env.example` in `.env` e compila le variabili:

```bash
cp .env.example .env
```

| Variabile | Descrizione |
|---|---|
| `BOT_TOKEN` | Token del bot Telegram |
| `TRANSAK_API_KEY` | API key Transak |
| `TRANSAK_API_SECRET` | API secret Transak |
| `TREASURY_WALLET` | Indirizzo wallet tesoreria |
| `REFERRER_DOMAIN` | Dominio referrer per Transak |
| `TRANSAK_REFRESH_TOKEN_URL` | Endpoint Transak per il token |
| `TRANSAK_CREATE_WIDGET_URL` | Endpoint Transak per il widget |
| `BACKEND_URL` | URL del backend Flask (usato dal bot) |

## Avvio

```bash
pip install -r requirements.txt

# Avvia il backend
python backend/server.py

# Avvia il bot (in un altro terminale)
python bot/bot.py
```
