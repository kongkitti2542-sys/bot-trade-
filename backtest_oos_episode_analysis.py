from datetime import datetime, timedelta

from backtest_data_100k import get_historical_candles_100k, validate_candles
from backtest_oos_time_exit import (
    OOS_BOUNDARY,
    TEST_HOLDS,
    run_oos_backtest,
)


EPISODE_GAP_HOURS = 24


def realized_trades(trades):
    return [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]


def build_episodes(trades):
    trades = sorted(
        realized_trades(trades),
        key=lambda t: t["entry_time"],
    )

    if not trades:
        return []

    episodes = []
    current = [trades[0]]

    max_gap = timedelta(
        hours=EPISODE_GAP_HOURS
    )

    for trade in trades[1:]:
        previous = current[-1]

        if (
            trade["entry_time"]
            - previous["entry_time"]
            <= max_gap
        ):
            current.append(trade)
        else:
            episodes.append(current)
            current = [trade]

    episodes.append(current)

    results = []

    for index, episode in enumerate(episodes, start=1):
        pnl = sum(
            t["pnl"] for t in episode
        )

        results.append({
            "index": index,
            "start": episode[0]["entry_time"],
            "end": episode[-1]["entry_time"],
            "trades": len(episode),
            "pnl": pnl,
            "wins": sum(
                1 for t in episode
                if t["pnl"] > 0
            ),
            "losses": sum(
                1 for t in episode
                if t["pnl"] < 0
            ),
        })

    return results


def print_episode_analysis(episodes):
    if not episodes:
        print("No episodes.")
        return

    total_pnl = sum(
        e["pnl"] for e in episodes
    )

    profitable = [
        e for e in episodes
        if e["pnl"] > 0
    ]

    losing = [
        e for e in episodes
        if e["pnl"] < 0
    ]

    print(f"Total episodes:       {len(episodes)}")
    print(f"Profitable episodes:  {len(profitable)}")
    print(f"Losing episodes:      {len(losing)}")
    print(f"Episode P/L:          ${total_pnl:.4f}")

    print()
    print("TOP EPISODES")
    print("-" * 100)

    top = sorted(
        episodes,
        key=lambda e: e["pnl"],
        reverse=True,
    )

    for rank, episode in enumerate(
        top[:10],
        start=1,
    ):
        print(
            f"{rank:<5}"
            f"P/L=${episode['pnl']:>9.4f} "
            f"Trades={episode['trades']:<3} "
            f"W={episode['wins']:<3} "
            f"L={episode['losses']:<3} "
            f"{episode['start']} -> {episode['end']}"
        )

    print()
    print("BOTTOM EPISODES")
    print("-" * 100)

    bottom = sorted(
        episodes,
        key=lambda e: e["pnl"],
    )

    for rank, episode in enumerate(
        bottom[:10],
        start=1,
    ):
        print(
            f"{rank:<5}"
            f"P/L=${episode['pnl']:>9.4f} "
            f"Trades={episode['trades']:<3} "
            f"W={episode['wins']:<3} "
            f"L={episode['losses']:<3} "
            f"{episode['start']} -> {episode['end']}"
        )

    print()
    print("REMOVE TOP EPISODES")
    print("-" * 70)

    for n in (1, 3, 5):
        removed = sum(
            e["pnl"] for e in top[:n]
        )

        remaining = total_pnl - removed

        print(
            f"Remove top {n} episodes: "
            f"removed=${removed:.4f} "
            f"remaining=${remaining:.4f}"
        )


def main():
    print("=" * 110)
    print("OOS EPISODE ANALYSIS")
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

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {boundary}")
    print(
        f"Episode gap:   {EPISODE_GAP_HOURS} hours"
    )

    for label, bars in TEST_HOLDS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            max_hold_bars=bars,
            boundary=boundary,
        )

        episodes = build_episodes(trades)

        print()
        print("=" * 110)
        print(f"TIME EXIT {label} ({bars} bars)")
        print("=" * 110)
        print(f"Ending capital:   ${capital:.2f}")
        print(f"Risk rejections:  {risk_rejections}")

        print()

        print_episode_analysis(episodes)

    print()
    print("=" * 110)
    print("Research only. No Core files were modified.")
    print("=" * 110)


if __name__ == "__main__":
    main()
