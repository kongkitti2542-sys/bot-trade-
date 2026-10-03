from datetime import datetime

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from edge_fingerprint_trend_buy import run

OOS_BOUNDARY = datetime.fromisoformat(
    "2026-07-21T10:05:00+00:00"
)

HORIZONS = [1, 3, 5, 10, 20, 40, 80, 120, 160, 200, 240]


def main():
    print("=" * 100)
    print("TREND_PULLBACK + BUY — WINNER HORIZON ANALYSIS")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {valid}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    boundary = OOS_BOUNDARY

    final_capital, trades = run(candles, boundary)

    winners = [
        t for t in trades
        if t["gross_pnl"] > 0
    ]

    print()
    print("=" * 100)
    print("WINNER SET")
    print("=" * 100)
    print(f"Candidate trades: {len(trades)}")
    print(f"Winners:          {len(winners)}")

    if not winners:
        print("NO WINNERS FOUND")
        return

    time_to_index = {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }

    print()
    print("=" * 100)
    print("WINNER HORIZON — INDIVIDUAL")
    print("=" * 100)

    rows = []

    for number, trade in enumerate(winners, 1):
        entry_time = trade["entry_time"]
        entry_price = trade["entry_price"]
        position_size = trade["position_size"]

        if entry_time not in time_to_index:
            print(
                f"{number:02d} | ENTRY TIME NOT FOUND: "
                f"{entry_time}"
            )
            continue

        entry_index = time_to_index[entry_time]

        values = {}

        for bars in HORIZONS:
            target_index = entry_index + bars

            if target_index >= len(candles):
                values[bars] = None
                continue

            price = candles[target_index]["close"]

            gross = (
                price - entry_price
            ) * position_size

            values[bars] = gross

        rows.append(values)

        parts = [
            f"{number:02d}",
            f"Entry {entry_time}",
        ]

        for bars in HORIZONS:
            value = values[bars]

            if value is None:
                parts.append(f"{bars}b=N/A")
            else:
                parts.append(f"{bars}b=${value:+.6f}")

        print(" | ".join(parts))

    print()
    print("=" * 100)
    print("WINNER HORIZON — AGGREGATE")
    print("=" * 100)

    for bars in HORIZONS:
        values = [
            row[bars]
            for row in rows
            if row[bars] is not None
        ]

        if not values:
            print(f"{bars:3d} bars | N/A")
            continue

        positive = sum(
            1 for value in values
            if value > 0
        )

        negative = sum(
            1 for value in values
            if value < 0
        )

        average = sum(values) / len(values)

        print(
            f"{bars:3d} bars | "
            f"N={len(values):2d} | "
            f"Positive={positive:2d} | "
            f"Negative={negative:2d} | "
            f"Avg=${average:+.6f} | "
            f"Min=${min(values):+.6f} | "
            f"Max=${max(values):+.6f}"
        )

    print()
    print("=" * 100)
    print("WINNER HORIZON — MEDIAN")
    print("=" * 100)

    for bars in HORIZONS:
        values = sorted(
            row[bars]
            for row in rows
            if row[bars] is not None
        )

        if not values:
            print(f"{bars:3d} bars | N/A")
            continue

        middle = len(values) // 2

        if len(values) % 2:
            median = values[middle]
        else:
            median = (
                values[middle - 1]
                + values[middle]
            ) / 2

        print(
            f"{bars:3d} bars | "
            f"Median=${median:+.6f}"
        )

    print()
    print("=" * 100)
    print("IMPORTANT")
    print("=" * 100)
    print("Horizon P/L is mark-to-market gross P/L.")
    print("It is not a new exit strategy.")
    print("Fees and slippage are not included in this diagnostic.")
    print("No future information is used to create entry signals.")
    print("No Core strategy/risk/execution file was modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
