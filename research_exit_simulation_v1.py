import json
from statistics import mean, median

from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
)

from money_maker_01_adapter_v1 import find_candidates


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLE_LIMIT = 100_000

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = (2 * FEE_PER_SIDE) + (2 * SLIPPAGE_PER_SIDE)

TP_LEVELS = (
    0.0020,
    0.0030,
    0.0050,
    0.0075,
    0.0100,
    0.0150,
    0.0200,
)


def build_candle_index(candles):
    return {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }


def calculate_mfe(candidate, entry_index, exit_index, candles):
    entry = candidate["entry"]

    window = candles[entry_index : exit_index + 1]

    if not window:
        return None

    max_high = max(c["high"] for c in window)

    return (max_high - entry) / entry


def calculate_fixed_return(candidate, exit_index, candles):
    entry = candidate["entry"]
    exit_price = candles[exit_index]["close"]

    return (exit_price - entry) / entry


def simulate_tp(candidate, candle_index, candles, tp):
    entry_index = candle_index.get(candidate["entry_time"])
    fixed_exit_index = candle_index.get(candidate["planned_exit_time"])

    if entry_index is None or fixed_exit_index is None:
        return None

    if fixed_exit_index < entry_index:
        return None

    entry = candidate["entry"]
    target_price = entry * (1.0 + tp)

    tp_index = None

    for index in range(entry_index, fixed_exit_index + 1):
        candle = candles[index]

        if candle["high"] >= target_price:
            tp_index = index
            break

    fixed_return = calculate_fixed_return(
        candidate,
        fixed_exit_index,
        candles,
    )

    if tp_index is None:
        gross_return = fixed_return
        exit_type = "FIXED_EXIT"
        exit_index = fixed_exit_index
        ambiguous = False
    else:
        gross_return = tp
        exit_type = "TAKE_PROFIT"
        exit_index = tp_index

        ambiguous = (
            tp_index == fixed_exit_index
        )

        if ambiguous:
            gross_return = fixed_return
            exit_type = "FIXED_EXIT_AMBIGUOUS_TP"

    net_return = gross_return - ROUND_TRIP_COST

    return {
        "signal_time": candidate["signal_time"].isoformat(),
        "entry_time": candidate["entry_time"].isoformat(),
        "planned_exit_time": candidate["planned_exit_time"].isoformat(),
        "entry": entry,
        "tp": tp,
        "gross_return": gross_return,
        "net_return": net_return,
        "exit_type": exit_type,
        "exit_index": exit_index,
        "tp_hit": tp_index is not None and not ambiguous,
        "ambiguous": ambiguous,
    }


def calculate_stats(results):
    net = [r["net_return"] for r in results]

    wins = [r for r in results if r["net_return"] > 0]
    losses = [r for r in results if r["net_return"] <= 0]

    pot = 1_500.0
    peak = pot
    max_dd = 0.0
    loss_streak = 0
    max_loss_streak = 0

    for result in results:
        pot *= 1.0 + result["net_return"]

        if pot > peak:
            peak = pot

        drawdown = (pot / peak) - 1.0

        if drawdown < max_dd:
            max_dd = drawdown

        if result["net_return"] <= 0:
            loss_streak += 1
            max_loss_streak = max(
                max_loss_streak,
                loss_streak,
            )
        else:
            loss_streak = 0

    return {
        "trades": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(results)
        if results
        else 0.0,
        "avg_net_return": mean(net) if net else 0.0,
        "median_net_return": median(net) if net else 0.0,
        "ending_pot": pot,
        "net_profit": pot - 1_500.0,
        "return": (pot / 1_500.0) - 1.0,
        "max_drawdown": max_dd,
        "max_loss_streak": max_loss_streak,
    }


def main():
    print("=" * 72)
    print("EXIT SIMULATION V1")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Candles      : {CANDLE_LIMIT:,}")
    print("Entry        : MONEY_MAKER_01")
    print(f"Cost         : {ROUND_TRIP_COST * 100:.4f}% RT")
    print("Fallback     : FIXED EXIT")
    print("Ambiguous TP : NOT COUNTED AS TP")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        CANDLE_LIMIT,
    )

    print(f"Candles returned: {len(candles):,}")

    candidates = find_candidates(candles)

    print(f"Candidates      : {len(candidates):,}")

    candle_index = build_candle_index(candles)

    all_results = {}

    for tp in TP_LEVELS:
        results = []

        for candidate in candidates:
            result = simulate_tp(
                candidate,
                candle_index,
                candles,
                tp,
            )

            if result is not None:
                results.append(result)

        results.sort(key=lambda r: r["entry_time"])

        all_results[str(tp)] = {
            "tp": tp,
            "stats": calculate_stats(results),
            "tp_hits": sum(
                1 for r in results
                if r["tp_hit"]
            ),
            "fixed_exits": sum(
                1 for r in results
                if r["exit_type"] == "FIXED_EXIT"
            ),
            "ambiguous": sum(
                1 for r in results
                if r["ambiguous"]
            ),
        }

    print()
    print("=" * 72)
    print("TP COMPARISON")
    print("=" * 72)

    for tp in TP_LEVELS:
        data = all_results[str(tp)]
        stats = data["stats"]

        print(
            f"TP {tp * 100:5.2f}% | "
            f"Trades {stats['trades']:4d} | "
            f"TP hits {data['tp_hits']:4d} | "
            f"WR {stats['win_rate'] * 100:6.2f}% | "
            f"Avg Net {stats['avg_net_return'] * 100:8.4f}% | "
            f"Median Net {stats['median_net_return'] * 100:8.4f}% | "
            f"End Pot {stats['ending_pot']:9.2f} | "
            f"Return {stats['return'] * 100:8.2f}% | "
            f"DD {stats['max_drawdown'] * 100:8.2f}% | "
            f"LS {stats['max_loss_streak']:2d}"
        )

    output = {
        "version": "EXIT_SIMULATION_V1",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "candles": len(candles),
        "candidates": len(candidates),
        "starting_pot_thb": 1500.0,
        "round_trip_cost": ROUND_TRIP_COST,
        "tp_levels": list(TP_LEVELS),
        "results": all_results,
    }

    output_path = "research_exit_simulation_v1_results.json"

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(
            output,
            handle,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
