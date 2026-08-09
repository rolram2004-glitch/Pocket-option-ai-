from __future__ import annotations

import httpx

from models import Candle


class MarketDataError(RuntimeError):
    pass


class TwelveDataMarket:
    """Small adapter around Twelve Data's documented time_series endpoint."""

    BASE_URL = "https://api.twelvedata.com/time_series"

    def __init__(self, api_key: str, interval: str = "1min") -> None:
        self.api_key = api_key
        self.interval = interval

    async def candles(self, symbol: str, outputsize: int = 100) -> list[Candle]:
        params = {
            "symbol": symbol,
            "interval": self.interval,
            "outputsize": max(20, min(outputsize, 500)),
            "timezone": "UTC",
            "order": "ASC",
            "apikey": self.api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MarketDataError(f"Feed non raggiungibile: {exc}") from exc

        values = payload.get("values") if isinstance(payload, dict) else None
        if not values:
            message = payload.get("message", "nessuna candela") if isinstance(payload, dict) else "risposta non valida"
            raise MarketDataError(f"{symbol}: {message}")

        candles: list[Candle] = []
        try:
            for row in values:
                candles.append(
                    Candle(
                        timestamp=str(row["datetime"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(f"{symbol}: formato candele non valido") from exc
        return candles

    async def latest_price(self, symbol: str) -> float:
        candles = await self.candles(symbol, outputsize=20)
        return candles[-1].close


def pocket_asset(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()
