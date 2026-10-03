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
    path = []

    for number, trade in enumerate(trades, start=1):
        # A floor is inactive until profit has been locked.
        # Therefore the first trade must always be allowed.
        old_pot = pot
        net_return = trade["net"]

        pot = old_pot * (1.0 + net_return)
        trades_taken += 1

        # Update peak only after the completed trade.
        if pot > peak:
            peak = pot

        # Trailing profit lock.
        if lock_ratio is None:
            floor = STARTING_POT_THB
        else:
            locked_profit = (peak - STARTING_POT_THB) * lock_ratio
            floor = STARTING_POT_THB + locked_profit

        drawdown = (pot - peak) / peak if peak > 0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        lowest_pot = min(lowest_pot, pot)

        if net_return <= 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0

        breached = (
            lock_ratio is not None
            and peak > STARTING_POT_THB
            and pot <= floor
        )

        path.append(
            {
                "trade": number,
                "old_pot": old_pot,
                "net_return": net_return,
                "pot": pot,
                "peak": peak,
                "floor": floor,
                "drawdown": drawdown,
                "floor_breached": breached,
            }
        )

        # The historical data only gives the completed trade result.
        # Therefore a breach is acted upon AFTER this trade completes.
        if breached:
            floor_hit = True
            floor_hit_trade = number
            break

    growth = (
        (pot / STARTING_POT_THB) - 1.0
        if STARTING_POT_THB > 0
        else 0.0
    )

    return {
        "final_pot": pot,
        "growth": growth,
        "peak": peak,
        "lowest_pot": lowest_pot,
        "max_drawdown": max_drawdown,
        "max_loss_streak": max_loss_streak,
        "trades_taken": trades_taken,
        "final_floor": floor,
        "floor_hit": floor_hit,
        "floor_hit_trade": floor_hit_trade,
        "path": path,
    }


def print_model(name, result):
    print()
    print(name)
    print("-" * 72)
    print(f"Final POT          : THB {result['final_pot']:,.2f}")
    print(f"Net Growth         : {result['growth']:+.4%}")
    print(f"Peak POT           : THB {result['peak']:,.2f}")
    print(f"Lowest POT         : THB {result['lowest_pot']:,.2f}")
    print(f"Max Drawdown       : {result['max_drawdown']:+.4%}")
    print(f"Max Loss Streak    : {result['max_loss_streak']}")
    print(f"Trades Taken       : {result['trades_taken']}")
    print(f"Final Floor        : THB {result['final_floor']:,.2f}")
    print(f"Floor Hit          : {'YES' if result['floor_hit'] else 'NO'}")

    if result["floor_hit"]:
        print(f"Floor Hit Trade    : #{result['floor_hit_trade']}")

        if result["path"]:
            hit = result["path"][-1]
            print(f"POT Before Hit     : THB {hit['old_pot']:,.2f}")
            print(f"POT After Trade    : THB {hit['pot']:,.2f}")
            print(f"Floor At Hit       : THB {hit['floor']:,.2f}")
            print(f"Peak At Hit        : THB {hit['peak']:,.2f}")


def main():
    print("=" * 72)
    print("POT FLOOR RESEARCH V2")
    print("=" * 72)
    print(f"Starting POT       : THB {STARTING_POT_THB:,.2f}")
    print("Compounding        : 100% of current POT")
    print("Floor Action       : STOP NEW TRADES AFTER COMPLETED TRADE")
    print("Intratrade CUT     : NOT MODELED")
    print("Resume             : NONE")
    print()

    candles = fetch_closed_candles()
    trades = evaluate(candles)

    print(f"Candles            : {len(candles)}")
    print(f"Source Trades      : {len(trades)}")

    if not trades:
        print("No trades returned.")
        return

    results = {}

    for name, lock_ratio in FLOOR_LOCKS.items():
        result = run_floor_model(trades, lock_ratio)
        results[name] = result
        print_model(name, result)

    print()
    print("=" * 72)
    print("COMPARISON")
    print("=" * 72)
    print(
        f"{'MODEL':<14}"
        f"{'FINAL POT':>14}"
        f"{'GROWTH':>12}"
        f"{'MAX DD':>12}"
        f"{'LOWEST':>14}"
        f"{'TRADES':>10}"
        f"{'FLOOR':>10}"
    )

    for name, result in results.items():
        hit = "YES" if result["floor_hit"] else "NO"
        print(
            f"{name:<14}"
            f"{result['final_pot']:>14,.2f}"
            f"{result['growth']:>11.2%}"
            f"{result['max_drawdown']:>11.2%}"
            f"{result['lowest_pot']:>14,.2f}"
            f"{result['trades_taken']:>10}"
            f"{hit:>10}"
        )


if __name__ == "__main__":
    main()
