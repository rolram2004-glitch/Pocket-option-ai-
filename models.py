from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Signal:
    asset: str
    direction: Direction
    expiry_seconds: int
    confidence: float | None
    raw_text: str


@dataclass(frozen=True)
class Profile:
    chat_id: int
    demo_balance: float
    trade_amount: float
    expiry_seconds: int
    min_confidence: float
    auto_demo: bool
    strategy_on: bool
    stopped: bool


@dataclass(frozen=True)
class Trade:
    trade_id: str
    chat_id: int
    asset: str
    direction: Direction
    amount: float
    expiry_seconds: int
    confidence: float | None
    status: str
    pnl: float
    created_at: str
    entry_price: float | None = None
    exit_price: float | None = None
    expiry_at: str | None = None
