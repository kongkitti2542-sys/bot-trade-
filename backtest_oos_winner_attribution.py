from collections import Counter, defaultdict
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


def remove_top_winners_pnl(trades, n):
    realized = realized_trades(trades)

    winners = sorted(
        [t["pnl"] for t in realized if t["pnl"] > 0],
        reverse=True,
    )

    losers = [
        t["pnl"] for t in realized
        if t["pnl"] < 0
    ]

    removed = sum(winners[:n])
    remaining_profit = sum(winners[n:])

    return {
        "original_pnl": sum(winners) + sum(losers),
        "removed": removed,
        "remaining_pnl": remaining_profit + sum(losers),
    }


def print_winner_attribution(trades):
    realized = realized_trades(trades)

    winners = [
        t for t in realized
        if t["pnl"] > 0
    ]

    winners.sort(
        key=lambda t: t["pnl"],
        reverse=True,
    )

    print("TOP WINNERS")
    print("-" * 110)
    print(
        f"{'Rank':<6}"
        f"{'P/L':>10}"
        f"{'Side':>8}"
        f"{'Regime':<18}"
        f"{'Score':>8}"
        f"{'Entry':<26}"
        f"{'Exit':<26}"
    )
    print("-" * 110)

    for rank, trade in enumerate(winners[:10], start=1):
        print(
            f"{rank:<6}"
            f"{trade['pnl']:>10.4f}"
            f"{trade['side']:>8}"
            f"{trade['regime']:<18}"
            f"{trade['score']:>8}"
            f"{str(trade['entry_time']):<26}"
            f"{str(trade['exit_time']):<26}"
        )

    print()

    regime_counts = Counter(
        t["regime"] for t in winners
    )

    regime_pnl = defaultdict(float)

    for trade in winners:
        regime_pnl[trade["regime"]] += trade["pnl"]

    print("WINNERS BY REGIME")
    print("-" * 70)

    for regime, count in regime_counts.most_common():
        print(
            f"{regime:<20}"
            f"count={count:<5}"
            f"profit=${regime_pnl[regime]:.4f}"
        )

    print()

    side_counts = Counter(
        t["side"] for t in winners
    )

    side_pnl = defaultdict(float)

    for trade in winners:
        side_pnl[trade["side"]] += trade["pnl"]

    print("WINNERS BY SIDE")
    print("-" * 70)

    for side in ("BUY", "SELL"):
        print(
            f"{side:<20}"
            f"count={side_counts[side]:<5}"
            f"profit=${side_pnl[side]:.4f}"
        )


def main():
    print("=" * 110)
    print("OOS WINNER ATTRIBUTION")
    print("=" * 110)

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

        realized = realized_trades(trades)

        print()
        print("=" * 110)
        print(f"TIME EXIT {label} ({bars} bars)")
        print("=" * 110)
        print(f"Ending capital:  ${capital:.2f}")
        print(f"Realized trades: {len(realized)}")
        print(f"Risk rejections: {risk_rejections}")

        print()

        print_winner_attribution(trades)

        print()
        print("REMOVE TOP WINNERS STRESS TEST")
        print("-" * 70)

        for n in (1, 5, 10, 20):
            result = remove_top_winners_pnl(
                trades,
                n,
            )

            print(
                f"Remove top {n:<2} winners:"
                f" original=${result['original_pnl']:.4f}"
                f" removed=${result['removed']:.4f}"
                f" remaining=${result['remaining_pnl']:.4f}"
            )

    print()
    print("=" * 110)
    print("Research only. No Core files were modified.")
    print("=" * 110)


if __name__ == "__main__":
    main()
