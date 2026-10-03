import requests
from datetime import datetime, timezone

BASE_URL = "https://api.binance.com/api/v3/klines"


def get_historical_candles(
    symbol="BTCUSDT",
    interval="5m",
    limit=1000,
):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    response = requests.get(
        BASE_URL,
        params=params,
        timeout=10,
    )
    response.raise_for_status()

    raw_candles = response.json()

    candles = []

    for candle in raw_candles:
        candles.append({
            "time": datetime.fromtimestamp(
                candle[0] / 1000,
                tz=timezone.utc,
            ),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        })

    return candles


if __name__ == "__main__":
    candles = get_historical_candles(
        symbol="BTCUSDT",
        interval="5m",
        limit=1000,
    )

    print("BACKTEST DATA")
    print("=" * 60)
    print(f"Candles: {len(candles)}")

    if candles:
        print(f"First: {candles[0]['time']}")
        print(f"Last:  {candles[-1]['time']}")
