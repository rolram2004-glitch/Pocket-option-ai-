from __future__ import annotations

from config import Settings
from models import Profile, Signal
from store import Store


def check_demo_trade(
    config: Settings, store: Store, profile: Profile, signal: Signal
) -> tuple[bool, str]:
    if profile.stopped:
        return False, "Kill switch attivo. Premi RIATTIVA prima di operare."
    if profile.trade_amount > config.max_trade_amount:
        return False, f"Importo sopra il massimo (${config.max_trade_amount:g})."
    if profile.trade_amount > profile.demo_balance:
        return False, "Saldo DEMO insufficiente."
    count, pnl = store.daily_stats(profile.chat_id)
    if count >= config.max_daily_trades:
        return False, f"Limite giornaliero raggiunto ({config.max_daily_trades} trade)."
    if pnl <= -config.max_daily_loss:
        return False, f"Stop-loss giornaliero raggiunto (-${config.max_daily_loss:g})."
    if signal.confidence is not None and signal.confidence < profile.min_confidence:
        return (
            False,
            f"Confidenza {signal.confidence:.0f}% sotto la soglia {profile.min_confidence:.0f}%.",
        )
    return True, "OK"

