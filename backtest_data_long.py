import time
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.binance.com/api/v3/klines"

INTERVAL_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
}


def get_historical_candles_long(
    symbol="BTCUSDT",
    interval="5m",
    candles_needed=20000,
):
    if interval not in INTERVAL_MINUTES:
        raise ValueError(
            f"Unsupported interval: {interval}"
        )

    if candles_needed <= 0:
        raise ValueError(
            "candles_needed must be greater than 0"
        )

    interval_minutes = INTERVAL_MINUTES[interval]

    now = datetime.now(timezone.utc)

    # Start far enough in the past to cover the
    # requested number of candles.
    start_time = now - timedelta(
        minutes=interval_minutes * candles_needed
    )

    start_ms = int(start_time.timestamp() * 1000)

    candles = []

    while len(candles) < candles_needed:
        remaining = candles_needed - len(candles)
        batch_limit = min(1000, remaining)

        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ms,
            "limit": batch_limit,
        }

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=10,
        )

        response.raise_for_status()

        raw_candles = response.json()

        if not raw_candles:
            break

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

        last_open_time = raw_candles[-1][0]

        next_start_time = (
            last_open_time
            + interval_minutes * 60 * 1000
        )

        if next_start_time <= start_ms:
            raise RuntimeError(
                "Pagination did not advance."
            )

        start_ms = next_start_time

        if len(raw_candles) < batch_limit:
            break

        time.sleep(0.2)

    # Remove any candle whose open time is still in
    # the current unfinished interval.
    current_interval_start = (
        now.timestamp() // (interval_minutes * 60)
    ) * (interval_minutes * 60)

    candles = [
        candle
        for candle in candles
        if candle["time"].timestamp()
        < current_interval_start
    ]

    # Remove duplicate timestamps.
    unique = {}

    for candle in candles:
        unique[candle["time"]] = candle

    candles = list(unique.values())

    # Guarantee chronological order.
    candles.sort(
        key=lambda candle: candle["time"]
    )

    # Keep only the requested number.
    if len(candles) > candles_needed:
        candles = candles[-candles_needed:]

    return candles


if __name__ == "__main__":
    candles = get_historical_candles_long(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=20000,
    )

    print("=" * 60)
    print("LONG BACKTEST DATA")
    print("=" * 60)

    print(f"Candles: {len(candles)}")

    if candles:
        print(f"First:  {candles[0]['time']}")
        print(f"Last:   {candles[-1]['time']}")

        duplicate_count = (
            len(candles)
            - len(set(c["time"] for c in candles))
        )

        print(f"Duplicates: {duplicate_count}")

        if len(candles) >= 2:
            interval = (
                candles[1]["time"]
                - candles[0]["time"]
            )

            print(f"Interval: {interval}")

        print("=" * 60)
