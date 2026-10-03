import json
from datetime import datetime, timezone
from pathlib import Path


CACHE_DIR = Path("research_cache")


def _serialize_candle(candle):
    return {
        "time": candle["time"].isoformat(),
        "open": float(candle["open"]),
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": float(candle["close"]),
        "volume": float(candle["volume"]),
    }


def save_candles(candles, filename="btc_usdt_5m_100k.json"):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    path = CACHE_DIR / filename

    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(candles),
        "symbol": "BTCUSDT",
        "interval": "5m",
        "candles": [_serialize_candle(candle) for candle in candles],
    }

    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, separators=(",", ":"))

    return path


def load_candles(filename="btc_usdt_5m_100k.json"):
    path = CACHE_DIR / filename

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    candles = []

    for candle in payload["candles"]:
        candles.append({
            "time": datetime.fromisoformat(candle["time"]),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle["volume"]),
        })

    return candles


if __name__ == "__main__":
    print("Research Data Cache")
    print(f"Cache directory: {CACHE_DIR}")
