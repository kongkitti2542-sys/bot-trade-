from compare_vol_volume_periods import (
    DISCOVERY_START,
    DISCOVERY_END,
    VALIDATION_START,
    VALIDATION_END,
    load_candles,
    run_period,
    summarize,
)

def pct(value, total):
    return (value / total * 100.0) if total else 0.0


def detailed(group):
    n = len(group)

    wins = [t for t in group if t["pnl"] > 0]
    losses = [t for t in group if t["pnl"] < 0]

    gross = sum(t["pnl"] for t in group)
    net = sum(t["net"] for t in group)

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    avg_winner = (
        sum(t["pnl"] for t in wins) / len(wins)
        if wins else 0.0
    )

    avg_loser = (
        sum(t["pnl"] for t in losses) / len(losses)
        if losses else 0.0
    )

    buy = [t for t in group if t["side"] == "BUY"]
    sell = [t for t in group if t["side"] == "SELL"]

    stop = [
        t for t in group
        if t["exit_reason"] == "STOP_LOSS"
    ]

    time_exit = [
        t for t in group
        if t["exit_reason"] == "TIME_EXIT"
    ]

    return {
        "n": n,
        "buy": len(buy),
        "sell": len(sell),
        "win_rate": pct(len(wins), n),
        "gross": gross,
        "net": net,
        "net_per_trade": net / n if n else 0.0,
        "pf": pf,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "stop_pct": pct(len(stop), n),
        "time_pct": pct(len(time_exit), n),
        "buy_net": sum(t["net"] for t in buy),
        "sell_net": sum(t["net"] for t in sell),
    }


def print_grid(name, trades):
    print()
    print("=" * 150)
    print(name)
    print("=" * 150)

    print(
        f"{'STATE':<12}"
        f"{'N':>5}"
        f"{'BUY':>6}"
        f"{'SELL':>6}"
        f"{'WR%':>8}"
        f"{'GROSS':>12}"
        f"{'NET':>12}"
        f"{'NET/TR':>12}"
        f"{'PF':>8}"
        f"{'AVG W':>12}"
        f"{'AVG L':>12}"
        f"{'STOP%':>8}"
        f"{'TIME%':>8}"
        f"{'BUY NET':>12}"
        f"{'SELL NET':>12}"
    )

    print("-" * 150)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                t for t in trades
                if t["vol_state"] == vol
                and t["volume_state"] == volume
            ]

            r = detailed(group)

            print(
                f"{vol+'×'+volume:<12}"
                f"{r['n']:>5}"
                f"{r['buy']:>6}"
                f"{r['sell']:>6}"
                f"{r['win_rate']:>7.2f}%"
                f"{r['gross']:>12.4f}"
                f"{r['net']:>12.4f}"
                f"{r['net_per_trade']:>12.4f}"
                f"{r['pf']:>8.3f}"
                f"{r['avg_winner']:>12.4f}"
                f"{r['avg_loser']:>12.4f}"
                f"{r['stop_pct']:>7.2f}%"
                f"{r['time_pct']:>7.2f}%"
                f"{r['buy_net']:>12.4f}"
                f"{r['sell_net']:>12.4f}"
            )

    print("-" * 150)

    total = detailed(trades)

    print(
        f"{'ALL':<12}"
        f"{total['n']:>5}"
        f"{total['buy']:>6}"
        f"{total['sell']:>6}"
        f"{total['win_rate']:>7.2f}%"
        f"{total['gross']:>12.4f}"
        f"{total['net']:>12.4f}"
        f"{total['net_per_trade']:>12.4f}"
        f"{total['pf']:>8.3f}"
        f"{total['avg_winner']:>12.4f}"
        f"{total['avg_loser']:>12.4f}"
        f"{total['stop_pct']:>7.2f}%"
        f"{total['time_pct']:>7.2f}%"
        f"{total['buy_net']:>12.4f}"
        f"{total['sell_net']:>12.4f}"
    )


def main():
    candles = load_candles()

    discovery, discovery_rej = run_period(
        candles,
        DISCOVERY_START,
        DISCOVERY_END,
    )

    validation, validation_rej = run_period(
        candles,
        VALIDATION_START,
        VALIDATION_END,
    )

    print("=" * 150)
    print("FULL-GRID VOLATILITY × VOLUME AUDIT")
    print("=" * 150)
    print("Research only.")
    print("No Core files modified.")
    print()
    print(f"Discovery risk rejections:  {discovery_rej}")
    print(f"Validation risk rejections: {validation_rej}")

    print_grid("DISCOVERY", discovery)
    print_grid("VALIDATION", validation)

    print()
    print("=" * 150)
    print("END OF FULL-GRID AUDIT")
    print("=" * 150)


if __name__ == "__main__":
    main()
