from statistics import median
from datetime import datetime

from market_intelligence_formula_v1 import (
    build_feature_rows,
    calculate_metrics,
)
from backtest_oos_time_exit import (
    run_oos_backtest,
    OOS_BOUNDARY,
)
from research_data_cache import load_candles


FEE_RATE = 0.0005
WINDOW = 2016

COMPONENTS = (
    "trend_rank",
    "momentum_rank",
    "volatility_rank",
    "volume_rank",
    "structure_rank",
)


def calculate_net(trade):
    entry = trade["entry_price"]
    exit_price = trade["exit_price"]
    size = trade["position_size"]
    side = trade["side"]

    if side == "BUY":
        gross = (exit_price - entry) * size
    else:
        gross = (entry - exit_price) * size

    fees = (
        entry * size * FEE_RATE
        + exit_price * size * FEE_RATE
    )

    return gross - fees


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

        index, _ = row_by_time[entry_time]
        metrics = calculate_metrics(rows, index)

        analyzed.append(
            {
                "trade": trade,
                "net": calculate_net(trade),
                **{
                    component: metrics[component]
                    for component in COMPONENTS
                },
            }
        )

    print("=" * 78)
    print("MARKET INTELLIGENCE COMPONENT ANALYSIS")
    print("=" * 78)
    print(f"Trades analyzed: {len(analyzed)}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"Fee rate:        {FEE_RATE * 100:.2f}% / side")
    print()

    for component in COMPONENTS:
        ordered = sorted(
            analyzed,
            key=lambda x: x[component],
        )

        n = len(ordered)

        print()
        print("=" * 78)
        print(component.upper())
        print("=" * 78)

        for q in range(5):
            start = (n * q) // 5
            end = (n * (q + 1)) // 5
            group = ordered[start:end]

            gross = sum(
                x["trade"]["pnl"]
                for x in group
            )

            net = sum(
                x["net"]
                for x in group
            )

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

            values = [x[component] for x in group]

            print(
                f"Q{q + 1} "
                f"N={len(group):3d} "
                f"Range={min(values):5.1f}-{max(values):5.1f} "
                f"W={wins:3d} "
                f"L={losses:3d} "
                f"WR={wins / len(group) * 100:6.2f}% "
                f"Gross={gross:+9.4f} "
                f"Net={net:+9.4f} "
                f"PF={pf:.3f}"
            )

        all_values = [x[component] for x in analyzed]

        print(
            f"Median: {median(all_values):.2f}"
        )

    print()
    print("=" * 78)
    print("RESEARCH ONLY")
    print("No Core files modified.")
    print("No thresholds selected from P/L.")
    print("=" * 78)


if __name__ == "__main__":
    main()
