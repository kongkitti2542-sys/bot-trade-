from datetime import datetime
from statistics import mean, median

from backtest_oos_time_exit import (
    get_historical_candles_100k,
    validate_candles,
    run_oos_backtest,
    CANDLES_NEEDED,
    OOS_BOUNDARY,
)

MAX_HOLD_BARS = 240


def percentile(values, p):
    if not values:
        return None
    x = sorted(values)
    k = (len(x) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(x) - 1)
    fraction = k - lo
    return x[lo] + (x[hi] - x[lo]) * fraction


def report(name, trades):
    bars = [t["bars_held"] for t in trades]

    print()
    print(name)
    print("-" * 64)

    if not bars:
        print("No trades")
        return

    print(f"Trades : {len(bars)}")
    print(f"Min    : {min(bars):.0f} bars")
    print(f"P25    : {percentile(bars, 0.25):.1f} bars")
    print(f"Median : {median(bars):.1f} bars")
    print(f"P75    : {percentile(bars, 0.75):.1f} bars")
    print(f"P90    : {percentile(bars, 0.90):.1f} bars")
    print(f"Mean   : {mean(bars):.2f} bars")
    print(f"Max    : {max(bars):.0f} bars")

    buckets = (
        (1, 6),
        (7, 12),
        (13, 24),
        (25, 48),
        (49, 96),
        (97, 144),
        (145, 192),
        (193, 239),
        (240, 10**9),
    )

    print()
    print("Distribution")

    for low, high in buckets:
        count = sum(low <= b <= high for b in bars)
        pct = count / len(bars) * 100

        label = (
            f"{low:3d}-{high:3d}"
            if high < 10**9
            else "240+"
        )

        print(f"{label} bars : {count:3d} ({pct:6.2f}%)")


def main():
    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=CANDLES_NEEDED,
    )
    validate_candles(candles)

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY.replace("Z", "+00:00")
    )

    _, trades, _ = run_oos_backtest(
        candles=candles,
        max_hold_bars=MAX_HOLD_BARS,
        boundary=boundary,
    )

    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    stop = [
        t for t in realized
        if t["exit_reason"] == "STOP_LOSS"
    ]

    time_exit = [
        t for t in realized
        if t["exit_reason"] == "TIME_EXIT"
    ]

    report("ALL REALIZED", realized)
    report("STOP LOSS", stop)
    report("TIME EXIT", time_exit)

    report(
        "STOP LOSS — BUY",
        [t for t in stop if t["side"] == "BUY"],
    )

    report(
        "STOP LOSS — SELL",
        [t for t in stop if t["side"] == "SELL"],
    )


if __name__ == "__main__":
    main()
