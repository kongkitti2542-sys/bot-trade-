from datetime import datetime

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from edge_fingerprint_trend_buy import run

OOS_BOUNDARY = datetime.fromisoformat(
    "2026-07-21T10:05:00+00:00"
)

HORIZONS = [20, 40, 80, 120, 160, 200, 240]

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002


def calculate_cost(entry_price, exit_price, position_size):
    entry_value = entry_price * position_size
    exit_value = exit_price * position_size

    fees = (
        entry_value * FEE_PER_SIDE
        + exit_value * FEE_PER_SIDE
    )

    slippage = (
        entry_value * SLIPPAGE_PER_SIDE
        + exit_value * SLIPPAGE_PER_SIDE
    )

    return fees, slippage


def simulate(trades, candles, horizon):
    time_to_index = {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }

    results = []

    for trade in trades:
        entry_time = trade["entry_time"]
        entry_index = time_to_index.get(entry_time)

        if entry_index is None:
            continue

        stop_exit = trade["exit_reason"] == "STOP_LOSS"

        if stop_exit:
            exit_price = trade["exit_price"]
            actual_bars = trade["bars_held"]
            exit_reason = "STOP_LOSS"

        else:
            target_index = entry_index + horizon

            if target_index >= len(candles):
                continue

            exit_price = candles[target_index]["close"]
            actual_bars = horizon
            exit_reason = f"HORIZON_{horizon}"

        gross = (
            exit_price - trade["entry_price"]
        ) * trade["position_size"]

        fees, slippage = calculate_cost(
            trade["entry_price"],
            exit_price,
            trade["position_size"],
        )

        net = gross - fees - slippage

        results.append({
            "gross": gross,
            "fees": fees,
            "slippage": slippage,
            "net": net,
            "bars": actual_bars,
            "exit_reason": exit_reason,
        })

    if not results:
        return None

    gross = sum(x["gross"] for x in results)
    fees = sum(x["fees"] for x in results)
    slippage = sum(x["slippage"] for x in results)
    net = sum(x["net"] for x in results)

    wins = [
        x for x in results
        if x["net"] > 0
    ]

    losses = [
        x for x in results
        if x["net"] < 0
    ]

    gross_wins = sum(
        x["gross"]
        for x in results
        if x["gross"] > 0
    )

    gross_losses = abs(sum(
        x["gross"]
        for x in results
        if x["gross"] < 0
    ))

    profit_factor = (
        gross_wins / gross_losses
        if gross_losses
        else float("inf")
    )

    return {
        "trades": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "expectancy": net / len(results),
        "profit_factor": profit_factor,
    }


def main():
    print("=" * 100)
    print("TREND_PULLBACK + BUY — HORIZON EXIT EDGE TEST")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {valid}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    boundary = OOS_BOUNDARY

    final_capital, trades = run(
        candles,
        boundary,
    )

    print()
    print("=" * 100)
    print("BASELINE CANDIDATE")
    print("=" * 100)

    print(f"Trades:         {len(trades)}")
    print(
        f"Existing Gross: "
        f"${sum(t['gross_pnl'] for t in trades):+.6f}"
    )
    print(
        f"Existing Final: "
        f"${final_capital:.6f}"
    )

    print()
    print("=" * 100)
    print("HORIZON EXIT COMPARISON")
    print("=" * 100)

    for horizon in HORIZONS:
        result = simulate(
            trades,
            candles,
            horizon,
        )

        if result is None:
            print(
                f"{horizon:3d} bars | NO RESULT"
            )
            continue

        print(
            f"{horizon:3d} bars | "
            f"N={result['trades']:3d} | "
            f"W={result['wins']:3d} | "
            f"L={result['losses']:3d} | "
            f"Gross=${result['gross']:+.6f} | "
            f"Fees=${result['fees']:.6f} | "
            f"Slip=${result['slippage']:.6f} | "
            f"Net=${result['net']:+.6f} | "
            f"Exp=${result['expectancy']:+.6f} | "
            f"PF={result['profit_factor']:.4f}"
        )

    print()
    print("=" * 100)
    print("INTERPRETATION")
    print("=" * 100)
    print("All candidate trades are included.")
    print("STOP_LOSS trades retain their actual stop exit.")
    print("Non-stop trades are evaluated at each requested horizon.")
    print("Costs are included using the project's research assumptions.")
    print("No horizon is declared an edge from this test alone.")
    print("No Core strategy/risk/execution file was modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
