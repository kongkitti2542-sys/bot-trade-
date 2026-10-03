from validate_atr_expansion_ema50 import fetch_closed_candles, evaluate


STARTING_POT_THB = 1500.0

FLOOR_LOCKS = {
    "NO_FLOOR": None,
    "LOCK_25": 0.25,
    "LOCK_50": 0.50,
    "LOCK_75": 0.75,
}


def run_floor_model(trades, lock_ratio, starting_pot=STARTING_POT_THB):
    pot = starting_pot
    peak = pot
    floor = starting_pot

    max_drawdown = 0.0
    lowest_pot = pot

    floor_hit = False
    floor_hit_trade = None
    trades_taken = 0

    for number, trade in enumerate(trades, start=1):
        old_pot = pot
        net_return = trade["net"]

        pot = old_pot * (1.0 + net_return)
        trades_taken += 1

        if pot > peak:
            peak = pot

        if lock_ratio is None:
            floor = starting_pot
        else:
            locked_profit = (peak - starting_pot) * lock_ratio
            floor = starting_pot + locked_profit

        drawdown = (pot - peak) / peak if peak > 0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        lowest_pot = min(lowest_pot, pot)

        if (
            lock_ratio is not None
            and peak > starting_pot
            and pot <= floor
        ):
            floor_hit = True
            floor_hit_trade = number
            break

    growth = (pot / starting_pot) - 1.0

    return {
        "final_pot": pot,
        "growth": growth,
        "max_drawdown": max_drawdown,
        "lowest_pot": lowest_pot,
        "trades_taken": trades_taken,
        "floor_hit": floor_hit,
        "floor_hit_trade": floor_hit_trade,
    }


def split_blocks(trades, block_count=4):
    n = len(trades)
    blocks = []

    for i in range(block_count):
        start = (n * i) // block_count
        end = (n * (i + 1)) // block_count
        blocks.append(trades[start:end])

    return blocks


def main():
    print("=" * 72)
    print("POT FLOOR RESEARCH V3")
    print("=" * 72)
    print(f"Starting POT       : THB {STARTING_POT_THB:,.2f}")
    print("Blocks             : 4 chronological blocks")
    print("Compounding        : 100% of current POT")
    print("Floor Action       : STOP NEW TRADES")
    print("Resume             : NONE")
    print()

    candles = fetch_closed_candles()
    trades = evaluate(candles)

    print(f"Candles            : {len(candles)}")
    print(f"Source Trades      : {len(trades)}")

    if not trades:
        print("No trades returned.")
        return

    blocks = split_blocks(trades, 4)

    print()
    print("BLOCK SIZES")
    print("-" * 72)

    for i, block in enumerate(blocks, start=1):
        print(f"Block {i:<2}           : {len(block)} trades")

    print()

    for block_number, block in enumerate(blocks, start=1):
        print("=" * 72)
        print(f"BLOCK {block_number}")
        print("=" * 72)

        for name, lock_ratio in FLOOR_LOCKS.items():
            result = run_floor_model(block, lock_ratio)

            hit = "YES" if result["floor_hit"] else "NO"
            hit_trade = (
                str(result["floor_hit_trade"])
                if result["floor_hit_trade"] is not None
                else "-"
            )

            print(
                f"{name:<14}"
                f" Final={result['final_pot']:>9,.2f}"
                f" Growth={result['growth']:>8.2%}"
                f" MaxDD={result['max_drawdown']:>8.2%}"
                f" Trades={result['trades_taken']:>4}"
                f" Floor={hit:>3}"
                f" HitTrade={hit_trade:>3}"
            )

        print()

    print("=" * 72)
    print("CONSISTENCY SUMMARY")
    print("=" * 72)

    for name, lock_ratio in FLOOR_LOCKS.items():
        print()
        print(name)

        positive_blocks = 0
        floor_hits = 0

        for block in blocks:
            result = run_floor_model(block, lock_ratio)

            if result["growth"] > 0:
                positive_blocks += 1

            if result["floor_hit"]:
                floor_hits += 1

        print(f"Positive Blocks    : {positive_blocks}/4")
        print(f"Floor Hits         : {floor_hits}/4")


if __name__ == "__main__":
    main()
