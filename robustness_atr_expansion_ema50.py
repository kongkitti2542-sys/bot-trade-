from validate_atr_expansion_ema50 import fetch_closed_candles, evaluate


def pct(x):
    return f"{x * 100:.4f}%"


def summarize(label, trades):
    if not trades:
        print(f"{label}: N=0")
        return

    nets = [t["net"] for t in trades]
    gross = sum(t["gross"] for t in trades)
    net = sum(nets)

    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]

    pf = (
        sum(wins) / abs(sum(losses))
        if losses
        else float("inf")
    )

    avg = net / len(nets)

    ordered = sorted(nets)

    median = ordered[len(ordered) // 2]

    print(f"{label}")
    print("-" * 72)
    print(f"N              : {len(nets)}")
    print(f"Win Rate       : {len(wins) / len(nets) * 100:.2f}%")
    print(f"Avg Net        : {pct(avg)}")
    print(f"Median Net     : {pct(median)}")
    print(f"Gross Return   : {pct(gross)}")
    print(f"Net Return     : {pct(net)}")
    print(f"Profit Factor  : {pf:.3f}")
    print(f"Best Trade     : {pct(max(nets))}")
    print(f"Worst Trade    : {pct(min(nets))}")


def main():
    print("=" * 72)
    print("ATR EXPANSION + EMA50 ROBUSTNESS TEST")
    print("=" * 72)
    print("LOCKED RULE: Original ATR Expansion + Close > EMA50")
    print("NO PARAMETER OPTIMIZATION")
    print()

    candles = fetch_closed_candles()

    print(f"Candles        : {len(candles)}")
    print(
        f"Period         : "
        f"{candles[0]['time']} -> {candles[-1]['time']}"
    )
    print()

    trades = evaluate(candles)

    summarize("FULL DATASET", trades)
    print()

    if len(trades) < 20:
        raise RuntimeError(
            "Too few trades for robustness analysis."
        )

    # Chronological thirds.
    n = len(trades)
    third = n // 3

    part1 = trades[:third]
    part2 = trades[third:2 * third]
    part3 = trades[2 * third:]

    summarize("CHRONOLOGICAL THIRD 1", part1)
    print()

    summarize("CHRONOLOGICAL THIRD 2", part2)
    print()

    summarize("CHRONOLOGICAL THIRD 3", part3)
    print()

    # First half / second half.
    half = n // 2

    summarize("FIRST HALF", trades[:half])
    print()

    summarize("SECOND HALF", trades[half:])
    print()

    # Trade distribution.
    nets = [t["net"] for t in trades]
    sorted_nets = sorted(nets, reverse=True)

    total_net = sum(nets)

    top_5 = sum(sorted_nets[:5])
    top_10 = sum(sorted_nets[:10])

    print("PROFIT CONCENTRATION")
    print("-" * 72)
    print(f"Total Net      : {pct(total_net)}")
    print(f"Top 5 Trades   : {pct(top_5)}")
    print(f"Top 10 Trades  : {pct(top_10)}")

    if total_net != 0:
        print(
            f"Top 5 Share    : "
            f"{top_5 / total_net * 100:.2f}%"
        )
        print(
            f"Top 10 Share   : "
            f"{top_10 / total_net * 100:.2f}%"
        )

    print()

    # Losing streak / winning streak.
    max_loss_streak = 0
    max_win_streak = 0

    loss_streak = 0
    win_streak = 0

    for value in nets:
        if value > 0:
            win_streak += 1
            loss_streak = 0
        else:
            loss_streak += 1
            win_streak = 0

        max_win_streak = max(max_win_streak, win_streak)
        max_loss_streak = max(max_loss_streak, loss_streak)

    print("STREAKS")
    print("-" * 72)
    print(f"Max Win Streak : {max_win_streak}")
    print(f"Max Loss Streak: {max_loss_streak}")


if __name__ == "__main__":
    main()
