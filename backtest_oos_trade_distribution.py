from datetime import datetime

from backtest_data_100k import get_historical_candles_100k, validate_candles
from backtest_oos_time_exit import (
    STARTING_CAPITAL,
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
    upper = min(lower + 1, len(values))
    fraction = index - lower

    return (
        values[lower]
        + (values[upper] - values[lower]) * fraction
    )


def analyze_distribution(trades):
    trades = realized_trades(trades)

    pnls = [t["pnl"] for t in trades]

    winners = sorted(
        [p for p in pnls if p > 0],
        reverse=True,
    )

    losers = sorted(
        [p for p in pnls if p < 0],
    )

    total_pnl = sum(pnls)

    print(f"Realized trades: {len(trades)}")
    print(f"Total P/L:       ${total_pnl:.4f}")

    if not trades:
        return

    print()
    print("P/L DISTRIBUTION")
    print("-" * 60)
    print(f"Min:             ${min(pnls):.4f}")
    print(f"P25:             ${percentile(pnls, 25):.4f}")
    print(f"Median:          ${percentile(pnls, 50):.4f}")
    print(f"P75:             ${percentile(pnls, 75):.4f}")
    print(f"Max:             ${max(pnls):.4f}")
    print()

    print("WINNERS")
    print("-" * 60)
    print(f"Count:           {len(winners)}")
    print(f"Total profit:    ${sum(winners):.4f}")

    for n in (1, 5, 10, 20):
        contribution = sum(winners[:n])
        pct = (
            contribution / total_pnl * 100
            if total_pnl != 0
            else 0.0
        )

        print(
            f"Top {n:<3} winners: "
            f"${contribution:.4f} "
            f"({pct:.2f}% of net P/L)"
        )

    print()
    print("LOSERS")
    print("-" * 60)
    print(f"Count:           {len(losers)}")
    print(f"Total loss:      ${sum(losers):.4f}")

    for n in (1, 5, 10, 20):
        contribution = sum(losers[:n])
        print(
            f"Bottom {n:<2} losses: "
            f"${contribution:.4f}"
        )

    print()
    print("PAYOFF")
    print("-" * 60)

    if winners and losers:
        avg_win = sum(winners) / len(winners)
        avg_loss = abs(sum(losers) / len(losers))

        print(f"Average win:     ${avg_win:.4f}")
        print(f"Average loss:    ${avg_loss:.4f}")
        print(
            f"Win/Loss ratio:  "
            f"{avg_win / avg_loss:.3f}"
            if avg_loss > 0
            else "Win/Loss ratio:  N/A"
        )

    print()
    print("TIME EXIT WINNERS")
    print("-" * 60)

    time_winners = [
        t["pnl"]
        for t in trades
        if t["exit_reason"] == "TIME_EXIT"
        and t["pnl"] > 0
    ]

    time_winners.sort(reverse=True)

    print(f"Count:           {len(time_winners)}")
    print(f"Total:           ${sum(time_winners):.4f}")

    for n in (1, 5, 10, 20):
        contribution = sum(time_winners[:n])
        print(
            f"Top {n:<3}:          "
            f"${contribution:.4f}"
        )


def main():
    print("=" * 100)
    print("OOS TRADE DISTRIBUTION ANALYSIS")
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

    boundary = datetime.fromisoformat(OOS_BOUNDARY)

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
        print(f"Ending capital:   ${capital:.2f}")
        print(f"Risk rejections:  {risk_rejections}")

        analyze_distribution(trades)

    print()
    print("=" * 100)
    print("Research only. No Core files were modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
