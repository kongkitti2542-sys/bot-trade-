from validate_atr_expansion_ema50 import fetch_closed_candles, evaluate


STARTING_POT_THB = 1500.0


def run_compounding(trades):
    pot = STARTING_POT_THB
    peak = pot

    max_drawdown = 0.0
    lowest_pot = pot

    max_loss_streak = 0
    loss_streak = 0

    results = []

    for number, trade in enumerate(trades, start=1):
        old_pot = pot

        # One trade uses 100% of the current pot.
        net_return = trade["net"]

        pot = old_pot * (1.0 + net_return)

        peak = max(peak, pot)

        drawdown = (
            (pot - peak) / peak
            if peak > 0
            else 0.0
        )

        max_drawdown = min(max_drawdown, drawdown)
        lowest_pot = min(lowest_pot, pot)

        if net_return <= 0:
            loss_streak += 1
            max_loss_streak = max(
                max_loss_streak,
                loss_streak,
            )
        else:
            loss_streak = 0

        results.append({
            "number": number,
            "time": trade["time"],
            "old_pot": old_pot,
            "net_return": net_return,
            "new_pot": pot,
            "drawdown": drawdown,
        })

    return results, max_drawdown, lowest_pot, max_loss_streak


def main():
    print("=" * 72)
    print("TRADE-TO-TRADE COMPOUNDING BACKTEST")
    print("=" * 72)
    print("Starting Pot       : THB 1,500.00")
    print("Position per Trade : 100% of current Pot")
    print("Compounding        : Every Trade")
    print("Session Target     : NONE")
    print("Parameter Tuning   : NONE")
    print()

    candles = fetch_closed_candles()
    trades = evaluate(candles)

    print(f"Candles            : {len(candles)}")
    print(f"Trades             : {len(trades)}")
    print()

    if not trades:
        print("No trades generated.")
        return

    results, max_drawdown, lowest_pot, max_loss_streak = (
        run_compounding(trades)
    )

    final_pot = results[-1]["new_pot"]
    growth = final_pot / STARTING_POT_THB - 1.0

    profitable = sum(
        1
        for r in results
        if r["net_return"] > 0
    )

    losing = sum(
        1
        for r in results
        if r["net_return"] <= 0
    )

    print("RESULT")
    print("-" * 72)
    print(f"Starting Pot       : THB {STARTING_POT_THB:,.2f}")
    print(f"Final Pot          : THB {final_pot:,.2f}")
    print(f"Net Growth         : {growth * 100:.4f}%")
    print(f"Profitable Trades  : {profitable}")
    print(f"Losing Trades      : {losing}")
    print(f"Lowest Pot         : THB {lowest_pot:,.2f}")
    print(f"Max Drawdown       : {max_drawdown * 100:.4f}%")
    print(f"Max Loss Streak    : {max_loss_streak}")
    print()

    print("TRADE-BY-TRADE POT")
    print("-" * 72)

    for r in results:
        print(
            f"#{r['number']:03d} | "
            f"{r['time']} | "
            f"Net {r['net_return'] * 100:+.4f}% | "
            f"Pot "
            f"THB {r['old_pot']:,.2f}"
            f" -> "
            f"THB {r['new_pot']:,.2f}"
        )


if __name__ == "__main__":
    main()
