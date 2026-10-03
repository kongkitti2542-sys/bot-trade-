from datetime import datetime
from collections import defaultdict

from backtest_oos_time_exit import (
    get_historical_candles_100k,
    validate_candles,
    run_oos_backtest,
    CANDLES_NEEDED,
    OOS_BOUNDARY,
)

MAX_HOLD_BARS = 240


def stats(trades):
    if not trades:
        return 0, 0.0, 0, 0

    pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] < 0)

    return len(trades), pnl, wins, losses


def print_grouped(title, groups):
    print()
    print(title)
    print("-" * 78)
    print(
        f"{'GROUP':25s}"
        f"{'TRADES':>8s}"
        f"{'W':>6s}"
        f"{'L':>6s}"
        f"{'GROSS':>14s}"
        f"{'AVG':>12s}"
    )

    for key in sorted(groups, key=str):
        trades = groups[key]
        count, pnl, wins, losses = stats(trades)
        avg = pnl / count if count else 0.0

        print(
            f"{str(key):25s}"
            f"{count:8d}"
            f"{wins:6d}"
            f"{losses:6d}"
            f"${pnl:13.4f}"
            f"${avg:11.6f}"
        )


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

    by_regime = defaultdict(list)
    by_side = defaultdict(list)
    by_score = defaultdict(list)

    for t in realized:
        by_regime[t["regime"]].append(t)
        by_side[t["side"]].append(t)

        score = t["score"]

        if score < -80:
            bucket = "< -80"
        elif score < -60:
            bucket = "-80 to -61"
        elif score < -40:
            bucket = "-60 to -41"
        elif score < 0:
            bucket = "-40 to -1"
        elif score < 40:
            bucket = "0 to 39"
        elif score < 60:
            bucket = "40 to 59"
        elif score < 80:
            bucket = "60 to 79"
        else:
            bucket = "80+"

        by_score[bucket].append(t)

    print("=" * 78)
    print("SIGNAL QUALITY ATTRIBUTION — OOS 20H")
    print("=" * 78)

    print_grouped("BY REGIME", by_regime)
    print_grouped("BY SIDE", by_side)
    print_grouped("BY STRATEGY SCORE", by_score)


if __name__ == "__main__":
    main()
