# Pocket AI Telegram — DEMO-first

Bot Telegram in italiano per leggere/normalizzare segnali di opzioni, applicare
controlli di rischio e provarli con un ledger DEMO virtuale. È pronto per essere
eseguito in locale o come worker su Railway.

## Cosa funziona

- dashboard Telegram con bottoni e kill switch;
- segnali come `EURUSD OTC CALL 1m 87%` o `BTCUSD PUT 30s 82%`;
- parsing locale immediato + fallback Gemini opzionale per messaggi poco strutturati;
- filtro di confidenza, importo massimo, limite trade/giorno e perdita/giorno;
- conferma manuale o Auto-DEMO;
- saldo DEMO e storico SQLite;
- chiusura di collaudo `WIN / LOSS / TIE` senza inventare risultati;
- **RSI AUTO**: scarica candele reali, calcola Wilder RSI e apre/chiude i trade
  DEMO automaticamente;
- anti-duplicazione: una stessa candela RSI non può aprire due volte lo stesso
  segnale, anche dopo un riavvio;
- pulsante/istruzioni per aprire il bot Telegram ufficiale di Pocket Option.

## Strategia RSI automatica

La configurazione iniziale è intenzionalmente semplice e modificabile:

- `RSI_PERIOD=7`
- `RSI_LOWER=14`
- `RSI_UPPER=86`
- importo DEMO iniziale: `$0.60` (modificabile dal pannello Telegram);
- **CALL** quando l'RSI era sotto 14 e rientra sopra 14;
- **PUT** quando l'RSI era sopra 86 e rientra sotto 86;
- una sola decisione per candela;
- esecuzione automatica solo sul ledger DEMO locale;
- chiusura automatica alla scadenza usando di nuovo il prezzo reale del feed.

Il rientro dalla zona estrema è usato al posto del semplice `RSI >= 86` o
`RSI <= 14`, perché restare in zona estrema per più candele non deve creare una
raffica di ordini duplicati.

Per accenderla imposta `TWELVE_DATA_API_KEY` e premi **📡 RSI AUTO** in Telegram.
I simboli iniziali sono `EUR/USD;GBP/USD;BTC/USD` e si cambiano con
`AUTO_SYMBOLS`.

La strategia non assegna una falsa "probabilità di vincita" al valore RSI. La
performance va misurata su DEMO prima di qualsiasi uso con fondi reali.

## Pocket Option: limite importante

Pocket Option dichiara che il suo **Telegram Signal Bot ufficiale** può essere
collegato al conto, scegliere **Demo o Real** e usare Auto-trade. Pocket Option
afferma inoltre che automazioni esterne non approvate possono violare le sue
condizioni. Per questo il progetto **non** contiene cookie, SSID, WebSocket
privati, reverse engineering o una falsa "API Pocket Option".

La voce `PO_OFFICIAL_TELEGRAM_BOT_URL` serve solo per il link ufficiale che viene
mostrato nel proprio account Pocket Option (Help → Applications → Telegram Bot).

Il ledger chiamato "DEMO locale" è volutamente distinto dal conto DEMO di
Pocket Option. Per far eseguire gli ordini sul **DEMO Pocket Option vero** bisogna
usare l'integrazione ufficiale fornita da Pocket Option oppure una API ufficiale
documentata/abilitata per il proprio account.

## Avvio in 5 minuti

1. Su Telegram apri **@BotFather**, crea un bot con `/newbot` e copia il token.
2. Copia `.env.example` in `.env`.
3. Inserisci `TELEGRAM_BOT_TOKEN` in `.env`.
4. Per la strategia automatica inserisci anche `TWELVE_DATA_API_KEY`.
5. Installa ed esegui:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python bot.py
   ```

6. Apri il tuo bot Telegram, invia `/start` e premi **📡 RSI AUTO OFF** per
   portarlo su ON.

Per rendere il bot privato, inserisci anche il tuo ID numerico in
`TELEGRAM_ALLOWED_CHAT_ID`.

## AI Gemini opzionale

`GEMINI_API_KEY` è opzionale. Se manca, i segnali standard funzionano comunque.
Quando è presente, Gemini viene usato **solo per estrarre i campi da un segnale
già scritto**. Non gli viene chiesto di inventare prezzi o prevedere il mercato
senza dati reali.

Non mettere mai token Telegram, chiavi Gemini o credenziali Pocket Option nel
repository. Se una chiave è stata pubblicata in chat o in un commit, revocala e
generane una nuova.

## Comandi

- `/start` — dashboard
- `/status` — stato e parametri
- `/signal EURUSD CALL 1m 85%` — interpreta un segnale
- `/settle ID WIN` — chiude manualmente un trade DEMO di collaudo

Puoi anche inoltrare al bot un normale messaggio contenente il segnale.

## Railway

Il `Dockerfile` è già incluso. Crea un servizio dal repository, imposta le
variabili di `.env` come Variables su Railway e avvia il container. Per
conservare lo storico attraverso i redeploy, usa un volume persistente e punta
`DATABASE_PATH` al percorso del volume.

## Test

```bash
python -m unittest discover -s tests -v
```

I test coprono parsing, rifiuto di segnali incompleti e contabilità DEMO.
