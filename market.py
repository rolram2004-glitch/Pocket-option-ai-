from __future__ import annotations

from datetime import UTC, datetime

try:
    import httpx
except ImportError:  # Core calculation tests can run before dependencies are installed.
    httpx = None

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
        if httpx is None:
            raise MarketDataError("Dipendenza httpx non installata")
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

    @staticmethod
    def supports(symbol: str) -> bool:
        return bool(symbol.strip())


class KrakenPublicMarket:
    """Public, keyless OHLC feed used for crypto-only DEMO testing."""

    BASE_URL = "https://api.kraken.com/0/public/OHLC"
    PAIRS = {
        "BTC/USD": "XBTUSD",
        "BTCUSD": "XBTUSD",
        "ETH/USD": "ETHUSD",
        "ETHUSD": "ETHUSD",
        "SOL/USD": "SOLUSD",
        "SOLUSD": "SOLUSD",
    }
    INTERVALS = {
        "1min": 1,
        "1m": 1,
        "5min": 5,
        "5m": 5,
        "15min": 15,
        "15m": 15,
        "30min": 30,
        "30m": 30,
        "60min": 60,
        "1h": 60,
    }

    def __init__(self, interval: str = "1min") -> None:
        normalized = interval.strip().lower()
        if normalized not in self.INTERVALS:
            raise ValueError(
                "MARKET_INTERVAL non supportato dal feed pubblico Kraken: "
                "usa 1min, 5min, 15min, 30min o 60min"
            )
        self.interval = self.INTERVALS[normalized]

    @classmethod
    def supports(cls, symbol: str) -> bool:
        return symbol.strip().upper() in cls.PAIRS

    @classmethod
    def pair_for(cls, symbol: str) -> str:
        try:
            return cls.PAIRS[symbol.strip().upper()]
        except KeyError as exc:
            raise MarketDataError(
                f"{symbol}: il feed pubblico senza chiave supporta solo BTC/USD, ETH/USD e SOL/USD"
            ) from exc

    @staticmethod
    def _parse_payload(
        symbol: str,
        payload: object,
        outputsize: int,
        *,
        include_current: bool,
    ) -> list[Candle]:
        if not isinstance(payload, dict):
            raise MarketDataError(f"{symbol}: risposta Kraken non valida")
        errors = payload.get("error")
        if errors:
            message = "; ".join(str(item) for item in errors)
            raise MarketDataError(f"{symbol}: {message}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MarketDataError(f"{symbol}: candele Kraken mancanti")
        rows = next((value for key, value in result.items() if key != "last"), None)
        if not isinstance(rows, list) or not rows:
            raise MarketDataError(f"{symbol}: nessuna candela Kraken")

        # Kraken documents the last row as the still-open candle. Signals use
        # only closed candles, while settlement may request the live close.
        selected = rows if include_current else rows[:-1]
        selected = selected[-max(20, min(outputsize, 500)) :]
        if not selected:
            raise MarketDataError(f"{symbol}: nessuna candela chiusa")
        candles: list[Candle] = []
        try:
            for row in selected:
                timestamp = datetime.fromtimestamp(int(row[0]), UTC).isoformat()
                candles.append(
                    Candle(
                        timestamp=timestamp,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                    )
                )
        except (IndexError, TypeError, ValueError) as exc:
            raise MarketDataError(f"{symbol}: formato candele Kraken non valido") from exc
        return candles

    async def _request(self, symbol: str) -> object:
        if httpx is None:
            raise MarketDataError("Dipendenza httpx non installata")
        params = {
            "pair": self.pair_for(symbol),
            "interval": self.interval,
            "assetVersion": 1,
        }
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MarketDataError(f"Feed pubblico Kraken non raggiungibile: {exc}") from exc

    async def candles(self, symbol: str, outputsize: int = 100) -> list[Candle]:
        payload = await self._request(symbol)
        return self._parse_payload(
            symbol, payload, outputsize, include_current=False
        )

    async def latest_price(self, symbol: str) -> float:
        payload = await self._request(symbol)
        candles = self._parse_payload(
            symbol, payload, 20, include_current=True
        )
        return candles[-1].close


def pocket_asset(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()
