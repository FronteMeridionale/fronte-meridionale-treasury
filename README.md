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

## Componenti

| Componente | File | Stato |
|---|---|---|
| Backend Flask | `backend/server.py` | ✅ Operativo |
| Bot Telegram | `bot/bot.py` | ✅ Operativo |
| Endpoint Widget URL | `POST /transak/widget-url` | ✅ Implementato |
| Endpoint Bank Order | `POST /transak/bank-order` | ⚠️ Stub — vedi sezione Bonifico |

## Flussi di pagamento

### 💳 Carta (funzionante)

1. Utente sceglie importo e metodo "Carta" nel bot
2. Bot chiama `POST /transak/widget-url`
3. Backend ottiene token partner Transak, costruisce URL widget
4. Bot invia link all'utente
5. Utente completa acquisto MATIC su Transak con carta

### 🏦 Bonifico (non ancora implementato)

1. Utente sceglie importo e metodo "Bonifico" nel bot
2. Bot chiama `POST /transak/bank-order`
3. **GAP TECNICO**: Transak non espone un'API server-side documentata per creare ordini bancari con `redirectUrl` e `orderId` nel medesimo pattern del widget URL.
4. L'endpoint restituisce attualmente un errore `NOT_IMPLEMENTED` (501)
5. Il bot mostra un messaggio che invita a usare la Carta

> **Nota**: Quando Transak documenterà e abiliterà l'API bank order, l'endpoint stub dovrà essere completato.

## Wallet tesoreria

`0x57f333c398c9625D84432aBD00871E2d8049cAaC`

## Staging vs Production

Transak fornisce due ambienti separati con credenziali separate:

| Ambiente | Endpoint token | Endpoint widget |
|---|---|---|
| **Staging** | `https://staging-api.transak.com/api/v2/partner/token` | `https://staging-api.transak.com/api/v2/partner/widget-url` |
| **Production** | `https://api.transak.com/api/v2/partner/token` | `https://api.transak.com/api/v2/partner/widget-url` |

> ⚠️ **NON mischiare** chiavi staging con endpoint production e viceversa.
> Un mismatch causa `401 Unauthorized` da Transak — errore riscontrato nei log Render.

## Deploy su Render

### Variabili d'ambiente obbligatorie

Il backend **non si avvia** se una delle seguenti variabili è mancante o vuota:

```
TRANSAK_API_KEY
TRANSAK_API_SECRET
TRANSAK_REFRESH_TOKEN_URL
TRANSAK_CREATE_WIDGET_URL
```

Variabili aggiuntive necessarie:

```
BOT_TOKEN
BACKEND_BASE_URL
TREASURY_WALLET
REFERRER_DOMAIN
PORT
```

### Checklist deploy

- [ ] `TRANSAK_REFRESH_TOKEN_URL` e `TRANSAK_CREATE_WIDGET_URL` puntano allo stesso ambiente (staging o production)
- [ ] `TRANSAK_API_KEY` e `TRANSAK_API_SECRET` sono le credenziali **dello stesso ambiente**
- [ ] `BACKEND_BASE_URL` nel bot punta all'URL Render del backend (es. `https://fronte-meridionale-treasury.onrender.com`)
- [ ] `TREASURY_WALLET` è il wallet corretto
- [ ] `REFERRER_DOMAIN` corrisponde al dominio del sito Fronte Meridionale
- [ ] Il log di avvio indica l'ambiente corretto (STAGING o PRODUCTION)

### Verifica 401 Unauthorized

Se Transak restituisce `401 Unauthorized` sull'endpoint token:

1. Verificare che `TRANSAK_REFRESH_TOKEN_URL` e `TRANSAK_API_KEY`/`TRANSAK_API_SECRET` siano dello **stesso ambiente**
2. Se si usano chiavi staging, usare anche endpoint staging
3. Se si usano endpoint production, usare anche chiavi production
4. Consultare il log di avvio del backend: la riga `STARTUP: Transak environment deduced` indica l'ambiente rilevato

## Sviluppo locale

Copiare `.env.example` in `.env` e compilare le variabili:

```bash
cp .env.example .env
# Modificare .env con le proprie credenziali
```

Avviare il backend:

```bash
pip install -r requirements.txt
python backend/server.py
```

Avviare il bot:

```bash
python bot/bot.py
```
