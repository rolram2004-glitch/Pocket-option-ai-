from __future__ import annotations

import json
import re

import httpx

from models import Direction, Signal
from parser import parse_signal


class SignalInterpreter:
    """Normalize a Telegram signal; Gemini is only a parsing fallback.

    The model is deliberately not asked to invent market prices or a forecast.
    A trading signal must exist in the incoming text.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str,
        default_expiry_seconds: int,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.default_expiry_seconds = default_expiry_seconds

    async def interpret(self, text: str) -> Signal | None:
        local = parse_signal(text, self.default_expiry_seconds)
        if local is not None or not self.api_key:
            return local
        return await self._gemini_parse(text)

    async def _gemini_parse(self, text: str) -> Signal | None:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        prompt = f"""
Extract an explicit binary-options signal from the message below. Never infer or
invent a market direction. If asset or direction is missing, return null.
Return ONLY compact JSON with fields asset, direction, expiry_seconds,
confidence. direction is CALL or PUT. confidence is a number 0..100 or null.
Normalize EUR/USD to EURUSD and append _OTC only when the text explicitly says OTC.

MESSAGE:
{text[:2500]}
""".strip()
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {"Content-Type": "application/json", "X-goog-api-key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
            output = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
            output = re.sub(r"^```(?:json)?|```$", "", output, flags=re.I).strip()
            if output.lower() == "null":
                return None
            data = json.loads(output)
            direction = Direction(str(data["direction"]).upper())
            asset = re.sub(r"[^A-Z0-9_]", "", str(data["asset"]).upper())
            expiry = int(data.get("expiry_seconds") or self.default_expiry_seconds)
            confidence_raw = data.get("confidence")
            confidence = float(confidence_raw) if confidence_raw is not None else None
            if not asset or expiry <= 0 or (confidence is not None and not 0 <= confidence <= 100):
                return None
            return Signal(asset, direction, expiry, confidence, text)
        except (httpx.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None

