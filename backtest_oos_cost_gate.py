from datetime import datetime, timezone

from backtest_oos_time_exit import (
    get_historical_candles_100k,
    validate_candles,
    run_oos_backtest,
    summarize,
    CANDLES_NEEDED,
    OOS_BOUNDARY,
)

# Research-only cost gate.
# Does NOT modify strategy, risk, or OOS baseline.
# Cost assumptions:
# Spot Regular User: 0.10% taker each side
# USDⓈ-M Futures Regular User: 0.05% taker each side
# Slippage is tested separately as stress, not claimed as exchange fact.

COST_PROFILES = {
    "SPOT_TAKER": 0.0010,
    "FUTURES_TAKER": 0.0005,
}

SLIPPAGE_STRESS = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}

MAX_HOLD_BARS = 240


def apply_costs(trades, fee_rate, slippage_rate):
    net_pnl = 0.0
    total_fees = 0.0
    total_slippage = 0.0

    for trade in trades:
        entry = trade["entry_price"]
        exit_price = trade["exit_price"]
        size = trade["position_size"]
        side = trade["side"]

        entry_slip_price = (
            entry * (1 + slippage_rate)
            if side == "BUY"
            else entry * (1 - slippage_rate)
        )

        exit_slip_price = (
            exit_price * (1 - slippage_rate)
            if side == "BUY"
            else exit_price * (1 + slippage_rate)
        )

        if side == "BUY":
            gross = (exit_slip_price - entry_slip_price) * size
        else:
            gross = (entry_slip_price - exit_slip_price) * size

        entry_fee = entry_slip_price * size * fee_rate
        exit_fee = exit_slip_price * size * fee_rate

        slippage_cost = (
            abs(entry_slip_price - entry) * size
            + abs(exit_slip_price - exit_price) * size
        )

        total_fees += entry_fee + exit_fee
        total_slippage += slippage_cost
        net_pnl += gross - entry_fee - exit_fee

    return net_pnl, total_fees, total_slippage


def main():
    print("=" * 90)
    print("OOS COST GATE — RESEARCH ONLY")
    print("=" * 90)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)
    print(f"Candles:      {len(candles)}")
    print(f"Validation:   {valid}")
    print(f"Reason:       {reason}")
    print(f"OOS Boundary: {OOS_BOUNDARY}")
    print(f"Hold:         20h / {MAX_HOLD_BARS} bars")

    if not valid:
        raise RuntimeError(f"Dataset validation failed: {reason}")

    result = run_oos_backtest(
        candles,
        max_hold_bars=MAX_HOLD_BARS,
        boundary=datetime.fromisoformat(OOS_BOUNDARY.replace("Z", "+00:00")).astimezone(timezone.utc),
    )

    baseline_capital, baseline_trades, baseline_risk_rejections = result
    baseline = summarize(baseline_capital, baseline_trades, baseline_risk_rejections)

    print("\nBASELINE — BEFORE COST")
    print(f"Ending Equity: {baseline['final_capital']:.4f}")
    print(f"Realized P/L:  {baseline['realized_pnl']:.4f}")
    print(f"Trades:        {baseline['realized_trades']}")
    print(f"Wins:          {baseline['wins']}")
    print(f"Losses:        {baseline['losses']}")
    print(f"PF:            {baseline['profit_factor']:.4f}")

    print("\nCOST GATE")
    print("-" * 90)

    for profile, fee_rate in COST_PROFILES.items():
        print(f"\n[{profile}] fee={fee_rate * 100:.3f}% each side")

        for slip_name, slip_rate in SLIPPAGE_STRESS.items():
            net_pnl, fees, slippage = apply_costs(
                baseline_trades,
                fee_rate,
                slip_rate,
            )

            final_equity = 1000.0 + net_pnl

            print(
                f"  Slippage {slip_name:<6} | "
                f"Final ${final_equity:>9.2f} | "
                f"Net P/L ${net_pnl:>8.2f} | "
                f"Fees ${fees:>7.2f} | "
                f"Slippage ${slippage:>7.2f}"
            )

    print("\nIMPORTANT")
    print("This is a cost sensitivity gate, not a prediction.")
    print("No Core files were modified.")


if __name__ == "__main__":
    main()
