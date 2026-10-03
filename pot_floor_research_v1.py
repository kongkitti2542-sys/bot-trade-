from validate_atr_expansion_ema50 import fetch_closed_candles, evaluate


STARTING_POT_THB = 1500.0

FLOOR_LOCKS = {
    "NO_FLOOR": None,
    "LOCK_25": 0.25,
    "LOCK_50": 0.50,
    "LOCK_75": 0.75,
}


def run_floor_model(trades, lock_ratio):
    pot = STARTING_POT_THB
    peak = pot
    floor = STARTING_POT_THB

    max_drawdown = 0.0
    lowest_pot = pot
    max_loss_streak = 0
    loss_streak = 0

    floor_hit = False
    floor_hit_trade = None
    trades_taken = 0
    results = []

    for number, trade in enumerate(trades, start=1):
        if floor_hit:
            break

        old_pot = pot
        net_return = trade["net"]

        pot = old_pot * (1.0 + net_return)

        trades_taken += 1

        if pot > peak:
            peak = pot

        if lock_ratio is None:
            floor = STARTING_POT_THB
        else:
            locked_profit = (peak - STARTING_POT_THB) * lock_ratio
            floor = STARTING_POT_THB + locked_profit

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
            "net_return": net_return,
            "old_pot": old_pot,
            "new_pot": pot,
            "peak": peak,
            "floor": floor,
            "drawdown": drawdown,
        })

        if (
            lock_ratio is not None
            and peak > STARTING_POT_THB
            and pot <= floor
        ):
            floor_hit = True
            floor_hit_trade = number

    return {
        "results": results,
        "final_pot": pot,
        "growth": pot / STARTING_POT_THB - 1.0,
        "lowest_pot": lowest_pot,
        "max_drawdown": max_drawdown,
        "max_loss_streak": max_loss_streak,
        "floor_hit": floor_hit,
        "floor_hit_trade": floor_hit_trade,
        "trades_taken": trades_taken,
        "final_floor": floor,
        "peak": peak,
    }


def print_model(name, result):
    print(f"\n{name}")
    print("-" * 72)

    print(
        f"Final POT          : THB {result['final_pot']:,.2f}"
    )
    print(
        f"Net Growth         : {result['growth'] * 100:+.4f}%"
    )
    print(
        f"Peak POT           : THB {result['peak']:,.2f}"
    )
    print(
        f"Lowest POT         : THB {result['lowest_pot']:,.2f}"
    )
    print(
        f"Max Drawdown       : {result['max_drawdown'] * 100:.4f}%"
    )
    print(
        f"Max Loss Streak    : {result['max_loss_streak']}"
    )
    print(
        f"Trades Taken       : {result['trades_taken']}"
    )
    print(
        f"Final Floor        : THB {result['final_floor']:,.2f}"
    )
    print(
        f"Floor Hit          : {'YES' if result['floor_hit'] else 'NO'}"
    )

    if result["floor_hit"]:
        print(
            f"Floor Hit Trade    : #{result['floor_hit_trade']}"
        )


def main():
    print("=" * 72)
    print("POT FLOOR RESEARCH V1")
    print("=" * 72)
    print(f"Starting POT       : THB {STARTING_POT_THB:,.2f}")
    print("Compounding        : 100% of current POT")
    print("Floor Action       : STOP NEW TRADES")
    print("Resume             : NONE")
    print()

    candles = fetch_closed_candles()
    trades = evaluate(candles)

    print(f"Candles            : {len(candles)}")
    print(f"Source Trades      : {len(trades)}")

    if not trades:
        print("\nNo trades generated.")
        return

    results = {}

    for name, lock_ratio in FLOOR_LOCKS.items():
        results[name] = run_floor_model(
            trades,
            lock_ratio,
        )

    for name, result in results.items():
        print_model(name, result)

    print("\n" + "=" * 72)
    print("COMPARISON")
    print("=" * 72)

    print(
        f"{'MODEL':<12}"
        f"{'FINAL POT':>14}"
        f"{'GROWTH':>12}"
        f"{'MAX DD':>12}"
        f"{'LOWEST':>14}"
        f"{'TRADES':>10}"
        f"{'FLOOR':>10}"
    )

    for name, result in results.items():
        print(
            f"{name:<12}"
            f"{result['final_pot']:>14,.2f}"
            f"{result['growth'] * 100:>11.2f}%"
            f"{result['max_drawdown'] * 100:>11.2f}%"
            f"{result['lowest_pot']:>14,.2f}"
            f"{result['trades_taken']:>10}"
            f"{'YES' if result['floor_hit'] else 'NO':>10}"
        )


if __name__ == "__main__":
    main()
