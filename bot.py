from __future__ import annotations

import asyncio
import html
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai import SignalInterpreter
from config import Settings
from market import KrakenPublicMarket, MarketDataError, TwelveDataMarket, pocket_asset
from models import Direction, Signal, StrategyMode
from risk import check_demo_trade
from store import Store
from strategy import RsiLevel, direction_for_rsi_level, rsi_level_cross_signal


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
# The Telegram Bot API embeds the bot token in request URLs.  Keep transport
# libraries below INFO so deployment logs can never disclose that credential.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("pocket-ai")
BOT_RELEASE = "AGGRESSIVE-DEMO-v7"

CONFIG = Settings.from_env()
STORE = Store(
    CONFIG.database_path,
    CONFIG.demo_start_balance,
    CONFIG.default_trade_amount,
    CONFIG.default_expiry_seconds,
    CONFIG.min_signal_confidence,
)
AI = SignalInterpreter(
    CONFIG.gemini_api_key, CONFIG.gemini_model, CONFIG.default_expiry_seconds
)
if CONFIG.twelve_data_api_key:
    MARKET = TwelveDataMarket(CONFIG.twelve_data_api_key, CONFIG.market_interval)
    ACTIVE_SYMBOLS = CONFIG.auto_symbols
    MARKET_LABEL = "Twelve Data (chiave privata)"
else:
    MARKET = KrakenPublicMarket(CONFIG.market_interval)
    ACTIVE_SYMBOLS = tuple(
        symbol for symbol in CONFIG.auto_symbols if MARKET.supports(symbol)
    ) or ("BTC/USD",)
    MARKET_LABEL = "Kraken pubblico (senza chiave)"


def _authorized(chat_id: int) -> bool:
    return CONFIG.allowed_chat_id is None or chat_id == CONFIG.allowed_chat_id


async def _guard(update: Update) -> bool:
    chat = update.effective_chat
    if chat is None or not _authorized(chat.id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ Bot privato: chat non autorizzata.")
        return False
    return True


def _fmt_expiry(seconds: int) -> str:
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s"


def _strategy_variants(
    mode: StrategyMode, level: RsiLevel
) -> list[tuple[StrategyMode, Direction]]:
    normal = (StrategyMode.NORMAL, direction_for_rsi_level(level, inverse=False))
    inverse = (StrategyMode.INVERSE, direction_for_rsi_level(level, inverse=True))
    if mode is StrategyMode.NORMAL:
        return [normal]
    if mode is StrategyMode.INVERSE:
        return [inverse]
    return [normal, inverse]


def _mode_label(mode: StrategyMode) -> str:
    return "ENTRAMBE DEMO" if mode is StrategyMode.COMPARE else mode.value


def _comparison_card(chat_id: int) -> str:
    stats = STORE.strategy_comparison(chat_id, days=7)
    amount = STORE.get_profile(chat_id).trade_amount
    lines = [
        "📊 <b>CONFRONTO STRATEGIE • ULTIMI 7 GIORNI</b>",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for mode in (StrategyMode.NORMAL, StrategyMode.INVERSE):
        item = stats[mode.value]
        rate = f"{item['win_rate']:.1f}%" if item["closed"] else "—"
        lines.extend(
            [
                f"\n<b>{mode.value}</b>",
                f"Chiusi: <b>{item['closed']}</b> • WIN: <b>{item['wins']}</b> "
                f"• LOSS: <b>{item['losses']}</b> • TIE: <b>{item['ties']}</b>",
                f"Win rate: <b>{rate}</b> • P/L: <b>${item['pnl']:+.2f}</b>",
                f"Saldo separato: <b>${item['balance']:,.2f}</b>",
            ]
        )

    normal = stats[StrategyMode.NORMAL.value]
    inverse = stats[StrategyMode.INVERSE.value]
    if not normal["closed"] and not inverse["closed"]:
        winner = "Nessun trade chiuso: attiva ENTRAMBE DEMO e RSI AUTO."
    elif normal["pnl"] > inverse["pnl"]:
        winner = "🏆 Migliore finora: NORMALE"
    elif inverse["pnl"] > normal["pnl"]:
        winner = "🏆 Migliore finora: INVERSA"
    else:
        winner = "🤝 Risultato attuale: PAREGGIO"
    lines.extend(
        [
            f"\n{winner}",
            f"\nLa modalità ENTRAMBE apre due trade virtuali da ${amount:g} sullo stesso evento RSI; non usa denaro reale.",
        ]
    )
    return "\n".join(lines)


def _dashboard(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    p = STORE.get_profile(chat_id)
    strategy_balances = STORE.strategy_balances(chat_id)
    count, pnl = STORE.daily_stats(chat_id)
    status = "🛑 STOP" if p.stopped else "🟢 ATTIVO"
    auto = "ON" if p.auto_demo else "OFF"
    strategy = "ON" if p.strategy_on else "OFF"
    text = (
        "<b>POCKET AI • DEMO CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Versione: ✅ <b>{BOT_RELEASE}</b>\n"
        f"Modalità: 🧪 <b>DEMO locale</b>\n"
        f"Stato: {status}\n"
        f"Saldo manuale: <b>${p.demo_balance:,.2f}</b>\n"
        f"Saldo NORMALE: <b>${strategy_balances[StrategyMode.NORMAL.value]:,.2f}</b>\n"
        f"Saldo INVERSA: <b>${strategy_balances[StrategyMode.INVERSE.value]:,.2f}</b>\n"
        f"Importo: <b>${p.trade_amount:g}</b> • Scadenza: <b>{_fmt_expiry(p.expiry_seconds)}</b>\n"
        f"Filtro: <b>{p.min_confidence:.0f}%</b> • Auto DEMO: <b>{auto}</b>\n"
        f"RSI AUTO: <b>{strategy}</b> • RSI({CONFIG.rsi_period}) "
        f"<b>{CONFIG.rsi_lower:g}/{CONFIG.rsi_upper:g}</b>\n"
        f"Versione RSI: <b>{_mode_label(p.strategy_mode)}</b>\n"
        f"Feed DEMO: <b>{html.escape(MARKET_LABEL)}</b>\n"
        f"Oggi: <b>{count}</b> trade • P/L chiuso: <b>${pnl:+.2f}</b>\n\n"
        "Inoltra un segnale, per esempio:\n"
        "<code>BTCUSD CALL 1m 87%</code>"
    )
    keyboard = [
        [InlineKeyboardButton("🧪 DEMO LOCALE • NESSUN ACCESSO CONTO", callback_data="dash")],
        [
            InlineKeyboardButton(f"🤖 Auto DEMO {auto}", callback_data="auto"),
            InlineKeyboardButton("🧠 Leggi segnale", callback_data="help_signal"),
        ],
        [
            InlineKeyboardButton(f"📡 RSI AUTO {strategy}", callback_data="strategy"),
        ],
        [
            InlineKeyboardButton(
                ("✅ " if p.strategy_mode is StrategyMode.NORMAL else "")
                + "NORMALE",
                callback_data="mode_normal",
            ),
            InlineKeyboardButton(
                ("✅ " if p.strategy_mode is StrategyMode.INVERSE else "")
                + "INVERSA",
                callback_data="mode_inverse",
            ),
        ],
        [
            InlineKeyboardButton(
                ("✅ " if p.strategy_mode is StrategyMode.COMPARE else "")
                + "ENTRAMBE DEMO",
                callback_data="mode_compare",
            ),
            InlineKeyboardButton("📊 Risultati", callback_data="strategy_results"),
        ],
        [InlineKeyboardButton("📈 Regole RSI", callback_data="strategy_info")],
        [
            InlineKeyboardButton(f"💵 ${p.trade_amount:g}", callback_data="amount"),
            InlineKeyboardButton(f"⏱ {_fmt_expiry(p.expiry_seconds)}", callback_data="expiry"),
            InlineKeyboardButton(f"🎯 {p.min_confidence:.0f}%", callback_data="confidence"),
        ],
        [
            InlineKeyboardButton("🧾 Ultimi trade", callback_data="trades"),
            InlineKeyboardButton(
                "▶️ RIATTIVA" if p.stopped else "🛑 STOP", callback_data="toggle_stop"
            ),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    assert update.effective_chat and update.effective_message
    STORE.activate_dual_demo(update.effective_chat.id)
    # Telegram keeps URL buttons inside messages already sent. The Bot API
    # cannot search chat history by text, so on /start we remove the most
    # recent messages that were sent by this bot. Attempts against user
    # messages simply fail and are ignored. Trade data remains in SQLite.
    current_message_id = update.effective_message.message_id
    for message_id in range(max(1, current_message_id - 12), current_message_id):
        try:
            await context.bot.delete_message(update.effective_chat.id, message_id)
        except Exception as exc:
            log.debug("Legacy panel cleanup skipped message %s: %s", message_id, exc)
    text, keyboard = _dashboard(update.effective_chat.id)
    await update.effective_message.reply_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    assert update.effective_message
    await update.effective_message.reply_text(
        f"✅ Versione attiva: {BOT_RELEASE}\n"
        "Nessun pulsante o collegamento esterno è presente in questa versione."
    )


async def results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    assert update.effective_chat and update.effective_message
    await update.effective_message.reply_text(
        _comparison_card(update.effective_chat.id), parse_mode=ParseMode.HTML
    )


def _signal_card(signal: Signal) -> str:
    arrow = "🟢 CALL ↑" if signal.direction is Direction.CALL else "🔴 PUT ↓"
    confidence = (
        f"{signal.confidence:.0f}%" if signal.confidence is not None else "non indicata"
    )
    return (
        "<b>SEGNALE RILEVATO</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Asset: <b>{html.escape(signal.asset)}</b>\n"
        f"Direzione: <b>{arrow}</b>\n"
        f"Scadenza: <b>{_fmt_expiry(signal.expiry_seconds)}</b>\n"
        f"Confidenza dichiarata: <b>{confidence}</b>"
    )


async def _show_signal(update: Update, signal: Signal) -> None:
    assert update.effective_chat and update.effective_message
    p = STORE.get_profile(update.effective_chat.id)
    allowed, reason = check_demo_trade(CONFIG, STORE, p, signal)
    card = _signal_card(signal)
    if not allowed:
        await update.effective_message.reply_text(
            card + f"\n\n⚠️ <b>Bloccato:</b> {html.escape(reason)}",
            parse_mode=ParseMode.HTML,
        )
        return

    conf = "x" if signal.confidence is None else f"{signal.confidence:g}"
    cb = f"trade|{signal.asset}|{signal.direction.value}|{signal.expiry_seconds}|{conf}"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"🧪 Esegui DEMO ${p.trade_amount:g}", callback_data=cb)]]
    )
    await update.effective_message.reply_text(
        card + "\n\n✅ Controlli rischio superati.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    if p.auto_demo:
        await _place_demo(update.effective_chat.id, signal, update.effective_message.reply_text)


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    assert update.effective_message
    text = update.effective_message.text or ""
    signal = await AI.interpret(text)
    if signal is None:
        await update.effective_message.reply_text(
            "Non trovo un segnale completo. Esempio:\n"
            "<code>/signal EURUSD OTC CALL 1m 87%</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await _show_signal(update, signal)


async def text_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    assert update.effective_message
    signal = await AI.interpret(update.effective_message.text or "")
    if signal is None:
        await update.effective_message.reply_text(
            "🧠 Non ho eseguito nulla: nel testo manca asset o direzione.\n"
            "Prova <code>EURUSD CALL 1m 85%</code>.",
            parse_mode=ParseMode.HTML,
        )
        return
    await _show_signal(update, signal)


async def _place_demo(chat_id: int, signal: Signal, reply) -> None:
    p = STORE.get_profile(chat_id)
    allowed, reason = check_demo_trade(CONFIG, STORE, p, signal)
    if not allowed:
        await reply(f"⚠️ DEMO non eseguita: {reason}")
        return
    trade = STORE.create_demo_trade(chat_id, signal)
    p2 = STORE.get_profile(chat_id)
    await reply(
        "🧪 <b>TRADE DEMO REGISTRATO</b>\n"
        f"ID: <code>{trade.trade_id}</code>\n"
        f"{html.escape(trade.asset)} • {trade.direction.value} • {_fmt_expiry(trade.expiry_seconds)}\n"
        f"Stake virtuale: <b>${trade.amount:.2f}</b>\n"
        f"Saldo virtuale disponibile: <b>${p2.demo_balance:,.2f}</b>\n\n"
        "Il bot non inventa l'esito. Per collaudare il ledger:\n"
        f"<code>/settle {trade.trade_id} WIN</code> oppure <code>LOSS</code>",
        parse_mode=ParseMode.HTML,
    )


async def _strategy_cycle(app: Application) -> None:
    chat_ids = STORE.strategy_chat_ids()
    if not chat_ids:
        return

    candle_cache = {}
    for symbol in ACTIVE_SYMBOLS:
        try:
            candle_cache[symbol] = await MARKET.candles(
                symbol, outputsize=max(60, CONFIG.rsi_period * 6)
            )
        except MarketDataError as exc:
            log.warning("Market feed %s: %s", symbol, exc)

    for chat_id in chat_ids:
        p = STORE.get_profile(chat_id)
        for symbol, candles in candle_cache.items():
            decision = rsi_level_cross_signal(
                candles,
                CONFIG.rsi_period,
                CONFIG.rsi_lower,
                CONFIG.rsi_upper,
            )
            if decision is None:
                continue
            asset = pocket_asset(symbol)
            variants = _strategy_variants(p.strategy_mode, decision.level)
            normal_direction = direction_for_rsi_level(decision.level, inverse=False)
            eligible_variants: list[tuple[StrategyMode, Direction, Signal]] = []
            for variant, direction in variants:
                signal = Signal(
                    asset=asset,
                    direction=direction,
                    expiry_seconds=p.expiry_seconds,
                    confidence=None,
                    raw_text=(
                        f"RSI({CONFIG.rsi_period})={decision.rsi:.2f} "
                        f"{variant.value}"
                    ),
                )
                allowed, reason = check_demo_trade(
                    CONFIG,
                    STORE,
                    p,
                    signal,
                    strategy_variant=variant.value,
                )
                if allowed:
                    eligible_variants.append((variant, direction, signal))
                else:
                    log.info(
                        "Strategy trade blocked chat=%s variant=%s: %s",
                        chat_id,
                        variant.value,
                        reason,
                    )
            if not eligible_variants:
                continue
            if not STORE.claim_strategy_event(
                chat_id, asset, decision.candle_time, normal_direction
            ):
                continue

            expiry_at = (
                datetime.now(UTC) + timedelta(seconds=p.expiry_seconds)
            ).isoformat(timespec="seconds")
            for variant, direction, signal in eligible_variants:
                trade = STORE.create_demo_trade(
                    chat_id,
                    signal,
                    entry_price=decision.entry_price,
                    expiry_at=expiry_at,
                    strategy_variant=variant.value,
                )
                await app.bot.send_message(
                    chat_id,
                    "📡 <b>RSI AUTO • DEMO</b>\n"
                    f"Versione: <b>{variant.value}</b>\n"
                    f"Zona RSI: <b>{decision.level.value}</b>\n"
                    f"{html.escape(asset)} • <b>{direction.value}</b>\n"
                    f"RSI({CONFIG.rsi_period}): {decision.previous_rsi:.2f} → "
                    f"<b>{decision.rsi:.2f}</b>\n"
                    f"Entry feed: <b>{decision.entry_price:g}</b>\n"
                    f"Scadenza: <b>{_fmt_expiry(p.expiry_seconds)}</b>\n"
                    f"Stake virtuale: <b>${trade.amount:g}</b>\n"
                    f"ID: <code>{trade.trade_id}</code>",
                    parse_mode=ParseMode.HTML,
                )


async def _settle_due_strategy_trades(app: Application) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    due = STORE.due_demo_trades(now)
    if not due:
        return
    symbol_map = {pocket_asset(symbol): symbol for symbol in ACTIVE_SYMBOLS}
    price_cache: dict[str, float] = {}
    for trade in due:
        symbol = symbol_map.get(trade.asset)
        if not symbol or trade.entry_price is None:
            continue
        try:
            if symbol not in price_cache:
                price_cache[symbol] = await MARKET.latest_price(symbol)
            exit_price = price_cache[symbol]
        except MarketDataError as exc:
            log.warning("Settlement feed %s: %s", symbol, exc)
            continue

        if exit_price == trade.entry_price:
            result = "TIE"
        elif trade.direction is Direction.CALL:
            result = "WIN" if exit_price > trade.entry_price else "LOSS"
        else:
            result = "WIN" if exit_price < trade.entry_price else "LOSS"
        closed = STORE.settle_demo_trade(
            trade.chat_id,
            trade.trade_id,
            result,
            CONFIG.demo_payout,
            exit_price=exit_price,
        )
        await app.bot.send_message(
            trade.chat_id,
            "🏁 <b>RSI AUTO • RISULTATO DEMO</b>\n"
            f"Versione: <b>{html.escape(trade.strategy_variant or 'MANUALE')}</b>\n"
            f"{html.escape(trade.asset)} • {trade.direction.value}\n"
            f"{trade.entry_price:g} → <b>{exit_price:g}</b>\n"
            f"Esito: <b>{closed.status}</b> • P/L virtuale <b>${closed.pnl:+.2f}</b>",
            parse_mode=ParseMode.HTML,
        )


async def strategy_worker(app: Application) -> None:
    while True:
        try:
            await _settle_due_strategy_trades(app)
            await _strategy_cycle(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("RSI strategy cycle failed")
        await asyncio.sleep(CONFIG.strategy_poll_seconds)


async def post_init(app: Application) -> None:
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Apri il pannello DEMO"),
            BotCommand("version", "Controlla la versione attiva"),
            BotCommand("results", "Confronto DEMO degli ultimi 7 giorni"),
            BotCommand("status", "Stato del bot"),
        ]
    )
    identity = await app.bot.get_me()
    app.bot_data["strategy_worker_task"] = asyncio.create_task(
        strategy_worker(app), name="rsi-auto-strategy"
    )
    log.info(
        "Telegram ready: @%s release=%s; RSI worker: %s (%s)",
        identity.username,
        BOT_RELEASE,
        MARKET_LABEL,
        ", ".join(ACTIVE_SYMBOLS),
    )


async def post_shutdown(app: Application) -> None:
    task = app.bot_data.get("strategy_worker_task")
    if isinstance(task, asyncio.Task):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    assert update.effective_chat and update.effective_message
    if len(context.args) != 2:
        await update.effective_message.reply_text("Uso: /settle ID WIN|LOSS|TIE")
        return
    try:
        trade = STORE.settle_demo_trade(
            update.effective_chat.id,
            context.args[0],
            context.args[1],
            CONFIG.demo_payout,
        )
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}")
        return
    p = STORE.get_profile(update.effective_chat.id)
    await update.effective_message.reply_text(
        f"✅ {trade.trade_id}: {trade.status} • P/L ${trade.pnl:+.2f}\n"
        f"Saldo DEMO: ${p.demo_balance:,.2f}"
    )


def _cycle(value, choices):
    try:
        idx = choices.index(value)
    except ValueError:
        idx = -1
    return choices[(idx + 1) % len(choices)]


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_chat is None:
        return
    if not _authorized(update.effective_chat.id):
        await query.answer("Non autorizzato", show_alert=True)
        return
    await query.answer()
    chat_id = update.effective_chat.id
    data = query.data or ""

    if data == "po":
        await query.message.reply_text(
            "🔒 <b>COLLEGAMENTO RIMOSSO</b>\n\n"
            "Questo bot non chiede password, cookie o SSID Pocket Option e non dichiara "
            "un accesso al conto che non possiede. Usa /start per aprire il nuovo pannello "
            "DEMO senza collegamento esterno.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "help_signal":
        await query.message.reply_text(
            "🧠 Inviami o inoltrami un segnale così:\n"
            "<code>EURUSD OTC CALL 1m 87%</code>\n"
            "<code>BTCUSD PUT 30s 82%</code>\n\n"
            "Se GEMINI_API_KEY è configurata, uso Gemini solo per capire formati di testo più liberi; "
            "non invento prezzi o segnali mancanti.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "strategy_info":
        symbols = ", ".join(ACTIVE_SYMBOLS)
        await query.message.reply_text(
            "📈 <b>STRATEGIA RSI AUTOMATICA</b>\n\n"
            f"RSI: <b>{CONFIG.rsi_period}</b> periodi\n"
            f"Zona bassa: <b>{CONFIG.rsi_lower:g}</b>\n"
            f"Zona alta: <b>{CONFIG.rsi_upper:g}</b>\n"
            f"<b>NORMALE</b>: RSI {CONFIG.rsi_upper:g} → CALL/BUY; "
            f"RSI {CONFIG.rsi_lower:g} → PUT/SELL.\n"
            f"<b>INVERSA</b>: RSI {CONFIG.rsi_upper:g} → PUT/SELL; "
            f"RSI {CONFIG.rsi_lower:g} → CALL/BUY.\n"
            "<b>ENTRAMBE DEMO</b>: apre le due versioni insieme e confronta i risultati.\n"
            "Il segnale scatta una sola volta quando l'RSI entra nella zona estrema.\n"
            f"Mercati: <b>{html.escape(symbols)}</b>\n"
            f"Feed: <b>{html.escape(MARKET_LABEL)}</b>\n"
            "Senza chiave personale il feed automatico è crypto e non replica i prezzi OTC di Pocket Option.\n\n"
            "L'RSI non è una percentuale di probabilità: il bot non trasforma il valore RSI in una promessa di vincita.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "strategy_results":
        await query.message.reply_text(
            _comparison_card(chat_id), parse_mode=ParseMode.HTML
        )
        return

    if data == "trades":
        trades = STORE.recent_trades(chat_id)
        if not trades:
            await query.message.reply_text("🧾 Nessun trade DEMO registrato.")
            return
        lines = ["<b>ULTIMI TRADE DEMO</b>"]
        for t in trades:
            variant = html.escape(t.strategy_variant or "MANUALE")
            lines.append(
                f"<code>{t.trade_id}</code> {html.escape(t.asset)} {t.direction.value} "
                f"[{variant}] ${t.amount:g} • {t.status} • ${t.pnl:+.2f}"
            )
        await query.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    p = STORE.get_profile(chat_id)
    if data == "auto":
        STORE.set_value(chat_id, "auto_demo", not p.auto_demo)
    elif data == "strategy":
        STORE.set_value(chat_id, "strategy_on", not p.strategy_on)
    elif data == "strategy_mode":
        next_mode = _cycle(
            p.strategy_mode,
            [StrategyMode.NORMAL, StrategyMode.INVERSE, StrategyMode.COMPARE],
        )
        STORE.set_value(chat_id, "strategy_mode", next_mode.value)
    elif data == "mode_normal":
        STORE.set_value(chat_id, "strategy_mode", StrategyMode.NORMAL.value)
    elif data == "mode_inverse":
        STORE.set_value(chat_id, "strategy_mode", StrategyMode.INVERSE.value)
    elif data == "mode_compare":
        STORE.set_value(chat_id, "strategy_mode", StrategyMode.COMPARE.value)
    elif data == "amount":
        STORE.set_value(
            chat_id,
            "trade_amount",
            _cycle(p.trade_amount, [0.6, 1.0, 2.0, 5.0, 10.0]),
        )
    elif data == "expiry":
        STORE.set_value(chat_id, "expiry_seconds", _cycle(p.expiry_seconds, [30, 60, 180, 300]))
    elif data == "confidence":
        STORE.set_value(chat_id, "min_confidence", _cycle(p.min_confidence, [70.0, 75.0, 80.0, 85.0, 90.0]))
    elif data == "toggle_stop":
        STORE.set_value(chat_id, "stopped", not p.stopped)
    elif data.startswith("trade|"):
        try:
            _, asset, direction, expiry, conf = data.split("|", 4)
            signal = Signal(
                asset=asset,
                direction=Direction(direction),
                expiry_seconds=int(expiry),
                confidence=None if conf == "x" else float(conf),
                raw_text="telegram-confirmation",
            )
        except (ValueError, TypeError):
            await query.message.reply_text("⚠️ Conferma trade non valida.")
            return
        await _place_demo(chat_id, signal, query.message.reply_text)
        return

    text, keyboard = _dashboard(chat_id)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as exc:  # Telegram returns BadRequest when message is unchanged.
        log.debug("Dashboard edit skipped: %s", exc)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        log.error(
            "Telegram token in uso da un altro servizio. Scollega ModularBot/altre istanze "
            "oppure genera un nuovo token BotFather e aggiornalo solo su Railway."
        )
        return
    log.exception("Unhandled Telegram update error", exc_info=context.error)


def main() -> None:
    CONFIG.validate()
    app = (
        Application.builder()
        .token(CONFIG.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("version", version))
    app.add_handler(CommandHandler("results", results))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("settle", settle))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_signal))
    app.add_error_handler(error_handler)
    log.info("Pocket AI Telegram started")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

