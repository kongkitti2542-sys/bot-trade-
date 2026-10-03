from datetime import datetime, timezone

from backtest_oos_time_exit import (
    get_historical_candles_100k,
    validate_candles,
    run_oos_backtest,
    CANDLES_NEEDED,
    OOS_BOUNDARY,
)

STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 240

FEE_PROFILES = {
    "SPOT_TAKER_0.10%": 0.0010,
    "FUTURES_TAKER_0.05%": 0.0005,
}

SLIPPAGE_PROFILES = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}


def apply_costs(trades, fee_rate, slippage_rate):
    gross_pnl = 0.0
    net_pnl = 0.0
    fees = 0.0
    slippage = 0.0
    turnover = 0.0

    for trade in trades:
        entry = trade["entry_price"]
        exit_price = trade["exit_price"]
        size = trade["position_size"]
        side = trade["side"]

        if side == "BUY":
            entry_exec = entry * (1 + slippage_rate)
            exit_exec = exit_price * (1 - slippage_rate)

            gross = (exit_price - entry) * size
            cost_adjusted_gross = (exit_exec - entry_exec) * size

        else:
            entry_exec = entry * (1 - slippage_rate)
            exit_exec = exit_price * (1 + slippage_rate)

            gross = (entry - exit_price) * size
            cost_adjusted_gross = (entry_exec - exit_exec) * size

        entry_fee = entry_exec * size * fee_rate
        exit_fee = exit_exec * size * fee_rate

        trade_turnover = entry_exec * size + exit_exec * size
        trade_slippage = (
            abs(entry_exec - entry) * size
            + abs(exit_exec - exit_price) * size
        )

        gross_pnl += gross
        fees += entry_fee + exit_fee
        slippage += trade_slippage
        turnover += trade_turnover

        net_pnl += cost_adjusted_gross - entry_fee - exit_fee

    return {
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "fees": fees,
        "slippage": slippage,
        "turnover": turnover,
    }


def summarize_trade_set(trades):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    wins = [t for t in realized if t["pnl"] > 0]
    losses = [t for t in realized if t["pnl"] < 0]

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    return {
        "total": len(trades),
        "realized": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "gross_pnl": sum(t["pnl"] for t in realized),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0 else float("inf")
        ),
    }


def main():
    print("=" * 72)
    print("COST ATTRIBUTION — OOS 20H")
    print("=" * 72)

    candles = get_historical_candles_100k(symbol="BTCUSDT", interval="5m", candles_needed=CANDLES_NEEDED)
    validate_candles(candles)

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY.replace("Z", "+00:00")
    )

    capital, trades, risk_rejections = run_oos_backtest(
        candles=candles,
        max_hold_bars=MAX_HOLD_BARS,
        boundary=boundary,
    )

    base = summarize_trade_set(trades)

    print(f"Starting capital : ${STARTING_CAPITAL:.2f}")
    print(f"Ending capital   : ${capital:.4f}")
    print(f"Trades           : {base['realized']}")
    print(f"Wins             : {base['wins']}")
    print(f"Losses           : {base['losses']}")
    print(f"Gross P/L        : ${base['gross_pnl']:.4f}")
    print(f"Profit Factor    : {base['profit_factor']:.4f}")
    print(f"Risk rejections  : {risk_rejections}")
    print()

    print("-" * 72)
    print("COST SCENARIOS")
    print("-" * 72)

    for fee_name, fee_rate in FEE_PROFILES.items():
        for slip_name, slip_rate in SLIPPAGE_PROFILES.items():
            result = apply_costs(
                trades,
                fee_rate=fee_rate,
                slippage_rate=slip_rate,
            )

            final_equity = STARTING_CAPITAL + result["net_pnl"]

            print(
                f"{fee_name:24s} | "
                f"Slip {slip_name:6s} | "
                f"Gross ${result['gross_pnl']:>9.3f} | "
                f"Fees ${result['fees']:>8.3f} | "
                f"Slip ${result['slippage']:>8.3f} | "
                f"Net ${result['net_pnl']:>9.3f} | "
                f"Final ${final_equity:>9.3f}"
            )

    print()
    print("-" * 72)
    print("TRADE ECONOMICS")
    print("-" * 72)

    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    if realized:
        gross = sum(t["pnl"] for t in realized)
        avg_gross = gross / len(realized)

        spot_zero_slip = apply_costs(
            trades,
            fee_rate=0.0010,
            slippage_rate=0.0,
        )

        futures_zero_slip = apply_costs(
            trades,
            fee_rate=0.0005,
            slippage_rate=0.0,
        )

        print(f"Average gross P/L per trade : ${avg_gross:.6f}")
        print(
            f"Spot fee per trade          : "
            f"${spot_zero_slip['fees'] / len(realized):.6f}"
        )
        print(
            f"Futures fee per trade       : "
            f"${futures_zero_slip['fees'] / len(realized):.6f}"
        )

        print()
        print(
            "Gross P/L / Spot fees       : "
            f"{gross / spot_zero_slip['fees']:.4f}x"
        )
        print(
            "Gross P/L / Futures fees    : "
            f"{gross / futures_zero_slip['fees']:.4f}x"
        )


if __name__ == "__main__":
    main()
