from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # Keeps core/tests usable before optional dependencies are installed.
    def load_dotenv() -> bool:
        return False


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def _float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    return float(value) if value else default


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    allowed_chat_id: int | None
    gemini_api_key: str | None
    gemini_model: str
    demo_start_balance: float
    default_trade_amount: float
    default_expiry_seconds: int
    min_signal_confidence: float
    max_trade_amount: float
    max_daily_trades: int
    max_daily_loss: float
    demo_payout: float
    twelve_data_api_key: str | None
    auto_symbols: tuple[str, ...]
    market_interval: str
    strategy_poll_seconds: int
    rsi_period: int
    rsi_lower: float
    rsi_upper: float
    po_official_telegram_bot_url: str | None
    database_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
        symbols = tuple(
            symbol.strip().upper()
            for symbol in os.getenv("AUTO_SYMBOLS", "EUR/USD;GBP/USD;BTC/USD").split(";")
            if symbol.strip()
        )
        return cls(
            telegram_bot_token=token,
            allowed_chat_id=int(allowed) if allowed else None,
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
            demo_start_balance=_float("DEMO_START_BALANCE", 10_000.0),
            default_trade_amount=_float("DEFAULT_TRADE_AMOUNT", 0.6),
            default_expiry_seconds=_int("DEFAULT_EXPIRY_SECONDS", 60),
            min_signal_confidence=_float("MIN_SIGNAL_CONFIDENCE", 80.0),
            max_trade_amount=_float("MAX_TRADE_AMOUNT", 10.0),
            max_daily_trades=_int("MAX_DAILY_TRADES", 20),
            max_daily_loss=_float("MAX_DAILY_LOSS", 50.0),
            demo_payout=_float("DEMO_PAYOUT", 0.82),
            twelve_data_api_key=os.getenv("TWELVE_DATA_API_KEY", "").strip() or None,
            auto_symbols=symbols,
            market_interval=os.getenv("MARKET_INTERVAL", "1min").strip(),
            strategy_poll_seconds=_int("STRATEGY_POLL_SECONDS", 15),
            rsi_period=_int("RSI_PERIOD", 7),
            rsi_lower=_float("RSI_LOWER", 14.0),
            rsi_upper=_float("RSI_UPPER", 86.0),
            po_official_telegram_bot_url=os.getenv(
                "PO_OFFICIAL_TELEGRAM_BOT_URL", ""
            ).strip()
            or None,
            database_path=os.getenv("DATABASE_PATH", "pocket_ai.sqlite3").strip(),
        )

    def validate(self) -> None:
        if not self.telegram_bot_token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN mancante. Copia .env.example in .env e inserisci il token di @BotFather."
            )
        if self.default_trade_amount <= 0:
            raise RuntimeError("DEFAULT_TRADE_AMOUNT deve essere > 0")
        if not 0 <= self.min_signal_confidence <= 100:
            raise RuntimeError("MIN_SIGNAL_CONFIDENCE deve essere tra 0 e 100")
        if self.max_trade_amount <= 0 or self.max_daily_trades <= 0:
            raise RuntimeError("I limiti di rischio devono essere positivi")
        if self.rsi_period < 2:
            raise RuntimeError("RSI_PERIOD deve essere almeno 2")
        if not 0 <= self.rsi_lower < self.rsi_upper <= 100:
            raise RuntimeError("RSI_LOWER/RSI_UPPER non validi")
        if self.strategy_poll_seconds < 5:
            raise RuntimeError("STRATEGY_POLL_SECONDS deve essere almeno 5")
        if any("OTC" in symbol for symbol in self.auto_symbols):
            raise RuntimeError(
                "AUTO_SYMBOLS non accetta OTC: il feed esterno non è il feed OTC di Pocket Option"
            )
