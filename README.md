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
- pulsanti **NORMALE / INVERSA / ENTRAMBE DEMO** per provare le due direzioni con
  lo stesso evento RSI;
- classifica separata con trade chiusi, WIN, LOSS, pareggi, win rate e P/L di
  ogni versione;
- anti-duplicazione: una stessa candela RSI non può aprire due volte lo stesso
  segnale, anche dopo un riavvio;
- nessuna richiesta di password, cookie o sessione Pocket Option.

## Strategia RSI automatica

La configurazione iniziale è intenzionalmente semplice e modificabile:

- `RSI_PERIOD=7`
- `RSI_LOWER=14`
- `RSI_UPPER=86`
- importo DEMO iniziale: `$0.60` (modificabile dal pannello Telegram);
- **NORMALE**: ingresso in zona 86 → `CALL/BUY`; ingresso in zona 14 → `PUT/SELL`;
- **INVERSA**: ingresso in zona 86 → `PUT/SELL`; ingresso in zona 14 → `CALL/BUY`;
- **ENTRAMBE DEMO**: registra entrambe le versioni in parallelo nel ledger DEMO;
- una sola decisione per candela;
- esecuzione automatica solo sul ledger DEMO locale;
- chiusura automatica alla scadenza usando di nuovo il prezzo reale del feed.

La decisione scatta quando l'RSI attraversa la soglia ed entra nella zona
estrema. Il controllo dell'attraversamento evita che un RSI fermo sopra 86 o
sotto 14 crei una raffica di ordini duplicati.

Per accenderla premi **📡 RSI AUTO** in Telegram: non serve alcuna chiave.
Senza `TWELVE_DATA_API_KEY` il bot usa il feed pubblico Kraken per `BTC/USD`
(oltre a `ETH/USD` e `SOL/USD` se inseriti in `AUTO_SYMBOLS`). Se configuri una
chiave Twelve Data, può usare anche i simboli FX indicati in `AUTO_SYMBOLS`.

La strategia non assegna una falsa "probabilità di vincita" al valore RSI. La
performance va misurata su DEMO prima di qualsiasi uso con fondi reali.

## Pocket Option: limite importante

Pocket Option dichiara che il suo **Telegram Signal Bot ufficiale** può essere
collegato al conto, scegliere **Demo o Real** e usare Auto-trade. Pocket Option
afferma inoltre che automazioni esterne non approvate possono violare le sue
condizioni. Per questo il progetto **non** contiene cookie, SSID, WebSocket
privati, reverse engineering o una falsa "API Pocket Option".

Il ledger chiamato "DEMO locale" è volutamente distinto dal conto DEMO di
Pocket Option. Per far eseguire gli ordini sul **DEMO Pocket Option vero** bisogna
usare l'integrazione ufficiale fornita da Pocket Option oppure una API ufficiale
documentata/abilitata per il proprio account.

Il collegamento ufficiale associa l'account al **bot di Pocket Option**, non
consegna credenziali o permessi di trading a questo bot personalizzato. Perciò il
progetto non dichiara falsamente che le strategie personalizzate siano eseguite
nel conto Pocket Option.

## Avvio in 5 minuti

1. Su Telegram apri **@BotFather**, crea un bot con `/newbot` e copia il token.
2. Copia `.env.example` in `.env`.
3. Inserisci `TELEGRAM_BOT_TOKEN` in `.env`.
4. Installa ed esegui:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python bot.py
   ```

5. Apri il tuo bot Telegram, invia `/start` e premi **📡 RSI AUTO OFF** per
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
