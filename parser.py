from __future__ import annotations

import re

from models import Direction, Signal


_DIRECTION_PATTERNS: tuple[tuple[Direction, re.Pattern[str]], ...] = (
    (Direction.CALL, re.compile(r"\b(CALL|BUY|UP|LONG|COMPRA|SU)\b", re.I)),
    (Direction.PUT, re.compile(r"\b(PUT|SELL|DOWN|SHORT|VENDI|GIU|GIÙ)\b", re.I)),
)

_FX_ASSET = re.compile(
    r"\b([A-Z]{3})\s*[/_-]?\s*([A-Z]{3})(?:\s*[-_]?\s*(OTC))?\b", re.I
)
_CRYPTO_ASSET = re.compile(
    r"\b(BTC|ETH|SOL|XRP|DOGE|ADA)\s*[/_-]?\s*(USD|USDT)(?:\s*[-_]?\s*(OTC))?\b",
    re.I,
)
_EXPIRY = re.compile(
    r"\b(\d{1,3})\s*(S|SEC|SECS|SECOND|SECONDS|M|MIN|MINS|MINUTE|MINUTES)\b",
    re.I,
)
_CONFIDENCE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*%")


def _extract_asset(text: str) -> str | None:
    # Crypto first, otherwise BTC/USD would also look like a generic FX pair.
    match = _CRYPTO_ASSET.search(text) or _FX_ASSET.search(text)
    if not match:
        return None
    base, quote = match.group(1).upper(), match.group(2).upper()
    otc = bool(match.group(3))
    return f"{base}{quote}{'_OTC' if otc else ''}"


def parse_signal(text: str, default_expiry_seconds: int = 60) -> Signal | None:
    cleaned = re.sub(r"^\s*/signal(?:@[A-Za-z0-9_]+)?\s*", "", text, flags=re.I)
    asset = _extract_asset(cleaned)
    direction: Direction | None = None
    for candidate, pattern in _DIRECTION_PATTERNS:
        if pattern.search(cleaned):
            direction = candidate
            break

    if asset is None or direction is None:
        return None

    expiry_seconds = default_expiry_seconds
    expiry = _EXPIRY.search(cleaned)
    if expiry:
        value = int(expiry.group(1))
        unit = expiry.group(2).upper()
        expiry_seconds = value * 60 if unit.startswith("M") else value

    confidence: float | None = None
    conf = _CONFIDENCE.search(cleaned)
    if conf:
        confidence = float(conf.group(1).replace(",", "."))
        if not 0 <= confidence <= 100:
            confidence = None

    return Signal(
        asset=asset,
        direction=direction,
        expiry_seconds=expiry_seconds,
        confidence=confidence,
        raw_text=text,
    )

