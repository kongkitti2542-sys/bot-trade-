from statistics import median
from market_intelligence_formula_v1 import (
    build_feature_rows,
    calculate_metrics,
)
from backtest_oos_time_exit import (
    run_oos_backtest,
    OOS_BOUNDARY,
)
from research_data_cache import load_candles
from datetime import datetime


FEE_RATE = 0.0005
WINDOW = 2016


def calculate_net(trade, slippage_rate=0.0):
    entry = trade["entry_price"]
    exit_price = trade["exit_price"]
    size = trade["position_size"]
    side = trade["side"]

    if side == "BUY":
        entry_exec = entry * (1 + slippage_rate)
        exit_exec = exit_price * (1 - slippage_rate)
        gross = (exit_exec - entry_exec) * size
    else:
        entry_exec = entry * (1 - slippage_rate)
        exit_exec = exit_price * (1 + slippage_rate)
        gross = (entry_exec - exit_exec) * size

    fees = (
        entry_exec * size * FEE_RATE
        + exit_exec * size * FEE_RATE
    )

    slippage_cost = (
        abs(entry_exec - entry) * size
        + abs(exit_exec - exit_price) * size
    )

    return gross - fees - slippage_cost


def main():
    candles = load_candles()

    rows = build_feature_rows(candles)
    row_by_time = {
        row["time"]: (index, row)
        for index, row in enumerate(rows)
    }

    boundary = datetime.fromisoformat(OOS_BOUNDARY)

    _, trades, risk_rejections = run_oos_backtest(
        candles,
        max_hold_bars=240,
        boundary=boundary,
    )

    analyzed = []

    for trade in trades:
        entry_time = trade["entry_time"]

        if entry_time not in row_by_time:
            continue

        index, row = row_by_time[entry_time]

        metrics = calculate_metrics(rows, index)

        analyzed.append(
            {
                "trade": trade,
                "mq": metrics["market_quality"],
                "net": calculate_net(trade),
            }
        )

    analyzed.sort(key=lambda x: x["mq"])

    n = len(analyzed)

    print("=" * 70)
    print("MARKET QUALITY RESULT ANALYSIS")
    print("=" * 70)
    print(f"Trades analyzed: {n}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"Fee rate:        {FEE_RATE * 100:.2f}% / side")
    print()

    if n < 5:
        print("NOT_ENOUGH_TRADES")
        return

    groups = []

    for q in range(5):
        start = (n * q) // 5
        end = (n * (q + 1)) // 5
        groups.append(analyzed[start:end])

    print("MQ QUINTILES")
    print("-" * 70)

    for i, group in enumerate(groups, start=1):
        gross = sum(x["trade"]["pnl"] for x in group)
        net = sum(x["net"] for x in group)

        wins = sum(
            1 for x in group
            if x["trade"]["pnl"] > 0
        )
        losses = sum(
            1 for x in group
            if x["trade"]["pnl"] < 0
        )

        gross_profit = sum(
            x["trade"]["pnl"]
            for x in group
            if x["trade"]["pnl"] > 0
        )

        gross_loss = -sum(
            x["trade"]["pnl"]
            for x in group
            if x["trade"]["pnl"] < 0
        )

        pf = (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf")
        )

        mq_values = [x["mq"] for x in group]

        print(
            f"Q{i} "
            f"N={len(group):3d} "
            f"MQ={min(mq_values):.2f}-{max(mq_values):.2f} "
            f"W={wins:3d} "
            f"L={losses:3d} "
            f"WR={wins / len(group) * 100:6.2f}% "
            f"Gross={gross:+9.4f} "
            f"Net={net:+9.4f} "
            f"PF={pf:.3f}"
        )

    print()
    print("MQ MEDIANS")
    print("-" * 70)

    for i, group in enumerate(groups, start=1):
        values = [x["mq"] for x in group]
        print(
            f"Q{i}: median MQ={median(values):.2f}"
        )

    print()
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)
    print("Q1 = lowest MQ")
    print("Q5 = highest MQ")
    print("No threshold was selected from P/L.")
    print("Research only. Core files were not modified.")
    print("=" * 70)


if __name__ == "__main__":
    main()
