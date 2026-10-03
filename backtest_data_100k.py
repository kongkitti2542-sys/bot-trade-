import time
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.binance.com/api/v3/klines"

INTERVAL_MINUTES = {
    "5m": 5,
}


def get_historical_candles_100k(
    symbol="BTCUSDT",
    interval="5m",
    candles_needed=100000,
):
    if interval not in INTERVAL_MINUTES:
        raise ValueError(
            f"Unsupported interval: {interval}"
        )

    interval_minutes = INTERVAL_MINUTES[interval]

    if candles_needed <= 0:
        raise ValueError(
            "candles_needed must be greater than 0"
        )

    now = datetime.now(timezone.utc)

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

        next_start_ms = (
            last_open_time
            + interval_minutes * 60 * 1000
        )

        if next_start_ms <= start_ms:
            raise RuntimeError(
                "Pagination did not advance."
            )

        start_ms = next_start_ms

        time.sleep(0.15)

    # Remove the current unfinished candle.
    current_interval_start = (
        int(now.timestamp())
        // (interval_minutes * 60)
    ) * (interval_minutes * 60)

    candles = [
        candle
        for candle in candles
        if int(candle["time"].timestamp())
        < current_interval_start
    ]

    # Remove duplicate timestamps.
    unique = {}

    for candle in candles:
        unique[candle["time"]] = candle

    candles = list(unique.values())

    # Chronological order.
    candles.sort(
        key=lambda candle: candle["time"]
    )

    # Keep requested size.
    if len(candles) > candles_needed:
        candles = candles[-candles_needed:]

    return candles


def validate_candles(candles, interval_minutes=5):
    if not candles:
        return {
            "valid": False,
            "reason": "NO_DATA",
        }

    timestamps = [
        candle["time"]
        for candle in candles
    ]

    if len(timestamps) != len(set(timestamps)):
        return {
            "valid": False,
            "reason": "DUPLICATE_TIMESTAMPS",
        }

    for index in range(1, len(timestamps)):
        delta = (
            timestamps[index]
            - timestamps[index - 1]
        )

        if delta.total_seconds() != interval_minutes * 60:
            return {
                "valid": False,
                "reason": (
                    "TIMELINE_GAP_OR_INVALID_INTERVAL"
                ),
            }

    return {
        "valid": True,
        "reason": "OK",
    }


if __name__ == "__main__":
    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100000,
    )

    validation = validate_candles(candles)

    print("=" * 60)
    print("100K BACKTEST DATA")
    print("=" * 60)

    print(f"Candles:     {len(candles)}")
    print(f"Validation:  {validation['valid']}")
    print(f"Reason:      {validation['reason']}")

    if candles:
        print(f"First:       {candles[0]['time']}")
        print(f"Last:        {candles[-1]['time']}")

    print("=" * 60)
