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


def state(rank):
    if rank < 33:
        return "LOW"
    if rank <= 66:
        return "MID"
    return "HIGH"


def net_pnl(trade):
    entry = trade["entry_price"]
    exit_price = trade["exit_price"]
    size = trade["position_size"]

    if trade["side"] == "BUY":
        gross = (exit_price - entry) * size
    else:
        gross = (entry - exit_price) * size

    fees = (
        entry * size * FEE_RATE
        + exit_price * size * FEE_RATE
    )

    return gross - fees


def summarize(label, items):
    if not items:
        print(
            f"{label:<28} N=  0"
        )
        return

    gross = sum(x["trade"]["pnl"] for x in items)
    net = sum(x["net"] for x in items)

    wins = sum(
        1 for x in items
        if x["trade"]["pnl"] > 0
    )

    losses = sum(
        1 for x in items
        if x["trade"]["pnl"] < 0
    )

    gross_profit = sum(
        x["trade"]["pnl"]
        for x in items
        if x["trade"]["pnl"] > 0
    )

    gross_loss = -sum(
        x["trade"]["pnl"]
        for x in items
        if x["trade"]["pnl"] < 0
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    print(
        f"{label:<28} "
        f"N={len(items):3d} "
        f"W={wins:3d} "
        f"L={losses:3d} "
        f"WR={wins / len(items) * 100:6.2f}% "
        f"Gross={gross:+9.4f} "
        f"Net={net:+9.4f} "
        f"PF={pf:.3f}"
    )


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

        vol_state = state(metrics["volatility_rank"])
        volume_state = state(metrics["volume_rank"])

        analyzed.append(
            {
                "trade": trade,
                "net": net_pnl(trade),
                "vol": vol_state,
                "volume": volume_state,
            }
        )

    print("=" * 90)
    print("VOLATILITY × VOLUME MARKET STATE")
    print("=" * 90)
    print(f"Trades analyzed: {len(analyzed)}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"Fee:             {FEE_RATE * 100:.2f}% / side")
    print()
    print("State definition: rank <33 LOW | 33-66 MID | >66 HIGH")
    print()

    print("ALL DIRECTIONS")
    print("-" * 90)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                x for x in analyzed
                if x["vol"] == vol
                and x["volume"] == volume
            ]

            summarize(
                f"V={vol:<4} VOL={volume:<4}",
                group,
            )

    print()
    print("BUY ONLY")
    print("-" * 90)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                x for x in analyzed
                if x["vol"] == vol
                and x["volume"] == volume
                and x["trade"]["side"] == "BUY"
            ]

            summarize(
                f"V={vol:<4} VOL={volume:<4}",
                group,
            )

    print()
    print("SELL ONLY")
    print("-" * 90)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                x for x in analyzed
                if x["vol"] == vol
                and x["volume"] == volume
                and x["trade"]["side"] == "SELL"
            ]

            summarize(
                f"V={vol:<4} VOL={volume:<4}",
                group,
            )

    print()
    print("=" * 90)
    print("RESEARCH ONLY")
    print("No trading rules modified.")
    print("No state selected from P/L.")
    print("=" * 90)


if __name__ == "__main__":
    main()
