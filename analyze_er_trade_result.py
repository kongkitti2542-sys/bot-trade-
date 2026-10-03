from datetime import datetime

from incremental_features import IncrementalFeatures
from backtest_oos_time_exit import run_oos_backtest, OOS_BOUNDARY
from research_data_cache import load_candles


ER_LOOKBACK = 12
ER_THRESHOLD = 0.30
FEE_RATE = 0.0005


def calculate_er(closes):
    if len(closes) < ER_LOOKBACK + 1:
        return None

    net_move = abs(
        closes[-1] - closes[-1 - ER_LOOKBACK]
    )

    path = sum(
        abs(closes[i] - closes[i - 1])
        for i in range(
            len(closes) - ER_LOOKBACK,
            len(closes),
        )
    )

    if path <= 0:
        return 0.0

    return net_move / path


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
        print(f"{label}: N=0")
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
        f"{label:<18} "
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

    closes = []
    er_by_time = {}

    for candle in candles:
        closes.append(float(candle["close"]))

        er = calculate_er(closes)

        if er is not None:
            er_by_time[candle["time"]] = er

    boundary = datetime.fromisoformat(OOS_BOUNDARY)

    _, trades, risk_rejections = run_oos_backtest(
        candles,
        max_hold_bars=240,
        boundary=boundary,
    )

    analyzed = []

    for trade in trades:
        er = er_by_time.get(trade["entry_time"])

        if er is None:
            continue

        analyzed.append(
            {
                "trade": trade,
                "er": er,
                "net": net_pnl(trade),
            }
        )

    low = [
        x for x in analyzed
        if x["er"] < ER_THRESHOLD
    ]

    high = [
        x for x in analyzed
        if x["er"] >= ER_THRESHOLD
    ]

    print("=" * 78)
    print("EFFICIENCY RATIO × TRADE RESULT")
    print("=" * 78)
    print(f"Trades analyzed: {len(analyzed)}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"ER lookback:     {ER_LOOKBACK} bars")
    print(f"ER threshold:    {ER_THRESHOLD:.2f}")
    print(f"Fee:             {FEE_RATE * 100:.2f}% / side")
    print()

    summarize("ER < 0.30", low)
    summarize("ER >= 0.30", high)

    print()
    print("BY SIDE")
    print("-" * 78)

    for label, group in (
        ("ER < 0.30", low),
        ("ER >= 0.30", high),
    ):
        summarize(
            f"{label} BUY",
            [
                x for x in group
                if x["trade"]["side"] == "BUY"
            ],
        )

        summarize(
            f"{label} SELL",
            [
                x for x in group
                if x["trade"]["side"] == "SELL"
            ],
        )

    print()
    print("BY EXIT")
    print("-" * 78)

    for label, group in (
        ("ER < 0.30", low),
        ("ER >= 0.30", high),
    ):
        summarize(
            f"{label} STOP",
            [
                x for x in group
                if x["trade"]["exit_reason"] == "STOP_LOSS"
            ],
        )

        summarize(
            f"{label} TIME",
            [
                x for x in group
                if x["trade"]["exit_reason"] == "TIME_EXIT"
            ],
        )

    print()
    print("=" * 78)
    print("RESEARCH ONLY")
    print("No trading rules modified.")
    print("=" * 78)


if __name__ == "__main__":
    main()
