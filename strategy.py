from __future__ import annotations

from dataclasses import dataclass

from models import Candle, Direction


def rsi_series(closes: list[float], period: int) -> list[float | None]:
    """Wilder RSI, aligned to closes."""
    if period < 2:
        raise ValueError("RSI period must be >= 2")
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        if gain == 0:
            return 0.0
        rs = gain / loss
        return 100.0 - 100.0 / (1.0 + rs)

    result[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[i] = value(avg_gain, avg_loss)
    return result


@dataclass(frozen=True)
class RsiDecision:
    direction: Direction
    rsi: float
    previous_rsi: float
    candle_time: str
    entry_price: float


def rsi_reentry_signal(
    candles: list[Candle], period: int, lower: float, upper: float
) -> RsiDecision | None:
    """Trade only when RSI re-enters from an extreme.

    CALL: previous RSI below lower and current RSI back above/equal lower.
    PUT: previous RSI above upper and current RSI back below/equal upper.
    """
    if len(candles) < period + 3:
        return None
    values = rsi_series([c.close for c in candles], period)
    previous, current = values[-2], values[-1]
    if previous is None or current is None:
        return None
    if previous < lower <= current:
        return RsiDecision(
            Direction.CALL, current, previous, candles[-1].timestamp, candles[-1].close
        )
    if previous > upper >= current:
        return RsiDecision(
            Direction.PUT, current, previous, candles[-1].timestamp, candles[-1].close
        )
    return None
