import requests
from datetime import datetime, timezone


BASE_URL = "https://api.binance.com/api/v3/klines"


def get_closed_candles(
    symbol="BTCUSDT",
    interval="5m",
    limit=100
):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit + 1,
    }

    response = requests.get(
        BASE_URL,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    raw_candles = response.json()

    candles = []

    for candle in raw_candles[:-1]:
        candles.append({
            "time": datetime.fromtimestamp(
                candle[0] / 1000,
                tz=timezone.utc
            ),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        })

    return candles


if __name__ == "__main__":
    candles = get_closed_candles(
        symbol="BTCUSDT",
        interval="5m",
        limit=10
    )

    print("BTC/USDT - CLOSED 5M CANDLES")
    print("=" * 80)

    for candle in candles:
        print(
            f"{candle['time']} | "
            f"O {candle['open']:.2f} | "
            f"H {candle['high']:.2f} | "
            f"L {candle['low']:.2f} | "
            f"C {candle['close']:.2f} | "
            f"V {candle['volume']:.4f}"
        )
