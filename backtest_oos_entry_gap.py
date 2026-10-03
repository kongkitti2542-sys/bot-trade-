from datetime import datetime

from backtest_data_100k import get_historical_candles_100k, validate_candles
from backtest_oos_time_exit import (
    OOS_BOUNDARY,
    TEST_HOLDS,
    run_oos_backtest,
)


def realized_trades(trades):
    return [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]


def percentile(values, percentile):
    if not values:
        return 0.0

    values = sorted(values)

    index = (len(values) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    fraction = index - lower

    return (
        values[lower]
        + (values[upper] - values[lower]) * fraction
    )


def analyze_entry_gaps(trades):
    trades = sorted(
        realized_trades(trades),
        key=lambda t: t["entry_time"],
    )

    if len(trades) < 2:
        print("Not enough trades.")
        return

    gaps_hours = []

    for previous, current in zip(
        trades,
        trades[1:],
    ):
        gap = (
            current["entry_time"]
            - previous["entry_time"]
        ).total_seconds() / 3600

        gaps_hours.append(gap)

    print(f"Realized trades: {len(trades)}")
    print(f"Entry gaps:      {len(gaps_hours)}")
    print()
    print("ENTRY GAP DISTRIBUTION")
    print("-" * 60)
    print(f"Minimum:         {min(gaps_hours):.4f} h")
    print(f"P25:             {percentile(gaps_hours, 25):.4f} h")
    print(f"Median:          {percentile(gaps_hours, 50):.4f} h")
    print(f"P75:             {percentile(gaps_hours, 75):.4f} h")
    print(f"P90:             {percentile(gaps_hours, 90):.4f} h")
    print(f"P95:             {percentile(gaps_hours, 95):.4f} h")
    print(f"P99:             {percentile(gaps_hours, 99):.4f} h")
    print(f"Maximum:         {max(gaps_hours):.4f} h")

    print()
    print("ENTRY GAP COUNTS")
    print("-" * 60)

    thresholds = (
        1,
        2,
        4,
        6,
        12,
        24,
        48,
        72,
    )

    for hours in thresholds:
        count = sum(
            1
            for gap in gaps_hours
            if gap <= hours
        )

        percentage = (
            count / len(gaps_hours) * 100
        )

        print(
            f"<= {hours:>2}h:"
            f" {count:>4}"
            f" ({percentage:>6.2f}%)"
        )


def main():
    print("=" * 100)
    print("OOS ENTRY GAP ANALYSIS")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:       {len(candles)}")
    print(f"Validation:    {valid}")
    print(f"Reason:        {reason}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {boundary}")

    for label, bars in TEST_HOLDS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            max_hold_bars=bars,
            boundary=boundary,
        )

        print()
        print("=" * 100)
        print(f"TIME EXIT {label} ({bars} bars)")
        print("=" * 100)
        print(f"Ending capital:  ${capital:.2f}")
        print(f"Risk rejections: {risk_rejections}")
        print()

        analyze_entry_gaps(trades)

    print()
    print("=" * 100)
    print("Research only. No Core files were modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
