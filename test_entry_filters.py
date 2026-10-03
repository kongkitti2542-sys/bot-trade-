from datetime import datetime

from backtest_oos_time_exit import (
    get_historical_candles_100k,
    validate_candles,
    run_oos_backtest,
    CANDLES_NEEDED,
    OOS_BOUNDARY,
)

MAX_HOLD_BARS = 240
FEE_RATE = 0.0005


def calculate(trades):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "gross": 0.0,
            "fees": 0.0,
            "net": 0.0,
            "pf": 0.0,
        }

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]

    gross = sum(t["pnl"] for t in trades)

    fees = sum(
        (t["entry_price"] * t["position_size"]
         + t["exit_price"] * t["position_size"])
        * FEE_RATE
        for t in trades
    )

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross": gross,
        "fees": fees,
        "net": gross - fees,
        "pf": gross_profit / gross_loss if gross_loss else float("inf"),
    }


def run_filter(name, trades, predicate):
    selected = [t for t in trades if predicate(t)]
    r = calculate(selected)

    print(
        f"{name:28s} "
        f"Trades={r['trades']:3d} "
        f"W={r['wins']:3d} "
        f"L={r['losses']:3d} "
        f"Gross=${r['gross']:9.3f} "
        f"Fee=${r['fees']:8.3f} "
        f"Net=${r['net']:9.3f} "
        f"PF={r['pf']:.3f}"
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

    print("=" * 110)
    print("ENTRY FILTER COUNTERFACTUAL — FUTURES TAKER 0.05%")
    print("=" * 110)

    run_filter(
        "BASELINE",
        realized,
        lambda t: True,
    )

    run_filter(
        "SCORE 60-79",
        realized,
        lambda t: 60 <= t["score"] <= 79,
    )

    run_filter(
        "BUY ONLY",
        realized,
        lambda t: t["side"] == "BUY",
    )

    run_filter(
        "SCORE 60-79 + BUY",
        realized,
        lambda t: (
            60 <= t["score"] <= 79
            and t["side"] == "BUY"
        ),
    )


if __name__ == "__main__":
    main()
