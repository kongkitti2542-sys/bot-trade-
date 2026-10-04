import json
from pathlib import Path

from money_machine_v2.research.profit_lock_reconcile import (
    build_candidates,
    simulate_exit,
    calculate_gross_return,
)
from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
)
from research_standard_v1 import (
    SYMBOL,
    INTERVAL,
    WINDOW_30D_CANDLES,
)
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = (
    2 * FEE_PER_SIDE
    + 2 * SLIPPAGE_PER_SIDE
)

TRIGGERS = (
    0.0020,
    0.0030,
    0.0050,
    0.0075,
    0.0100,
)

LOCKS = (
    0.0005,
    0.0010,
    0.0020,
    0.0030,
    0.0050,
)

OUTPUT_FILE = Path(
    "money_machine_v2/research/profit_lock_economics_audit_v1.json"
)


def run_strategy(records, candles, trigger, lock):
    pot = STARTING_POT_THB
    active_exit_time = None

    trades = []
    skipped_overlap = 0

    for record in records:
        candidate = record["candidate"]
        entry_time = candidate["entry_time"]

        if (
            active_exit_time is not None
            and entry_time < active_exit_time
        ):
            skipped_overlap += 1
            continue

        capital_usdt = pot / REFERENCE_USDTHB

        decision = {
            "signal": candidate["signal"],
            "confidence": 0,
            "quality": "PASSED",
        }

        features = {
            "close": candidate["entry"],
            "atr14": candidate["features"]["atr"],
        }

        risk = evaluate_risk(
            decision=decision,
            features=features,
            capital=capital_usdt,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk.get("allowed"):
            continue

        position_value_usdt = float(
            risk["position_value"]
        )

        position_value_thb = (
            position_value_usdt * REFERENCE_USDTHB
        )

        exit_result = simulate_exit(
            candidate=candidate,
            entry_index=record["entry_index"],
            fixed_exit_index=record["fixed_exit_index"],
            candles=candles,
            trigger=trigger,
            lock=lock,
        )

        if exit_result is None:
            continue

        gross_return = calculate_gross_return(
            candidate["signal"],
            candidate["entry"],
            exit_result["exit_price"],
        )

        gross_pnl = position_value_thb * gross_return
        cost = position_value_thb * ROUND_TRIP_COST
        net_pnl = gross_pnl - cost

        pot_before = pot
        pot += net_pnl

        exit_time = candles[
            exit_result["exit_index"]
        ]["time"]

        trades.append({
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "exit_type": exit_result["exit_type"],
            "entry": candidate["entry"],
            "exit_price": exit_result["exit_price"],
            "gross_return_pct": gross_return * 100.0,
            "position_value_thb": position_value_thb,
            "gross_pnl_thb": gross_pnl,
            "cost_thb": cost,
            "net_pnl_thb": net_pnl,
            "pot_before_thb": pot_before,
            "pot_after_thb": pot,
        })

        active_exit_time = exit_time

    wins = sum(
        1 for t in trades
        if t["net_pnl_thb"] > 0
    )

    losses = sum(
        1 for t in trades
        if t["net_pnl_thb"] < 0
    )

    lock_exits = sum(
        1 for t in trades
        if t["exit_type"] == "PROFIT_LOCK"
    )

    fallback_exits = sum(
        1 for t in trades
        if t["exit_type"] == "FIXED_FALLBACK"
    )

    peak = STARTING_POT_THB
    max_dd = 0.0

    for trade in trades:
        pot_after = trade["pot_after_thb"]

        if pot_after > peak:
            peak = pot_after

        if peak > 0:
            dd = (
                pot_after - peak
            ) / peak

            max_dd = min(max_dd, dd)

    net_profit = pot - STARTING_POT_THB

    return {
        "trigger_pct": trigger * 100.0,
        "lock_pct": lock * 100.0,
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": (
            wins / len(trades) * 100.0
            if trades else 0.0
        ),
        "profit_lock_exits": lock_exits,
        "fallback_exits": fallback_exits,
        "skipped_overlap": skipped_overlap,
        "ending_pot_thb": pot,
        "net_profit_thb": net_profit,
        "return_pct": (
            net_profit
            / STARTING_POT_THB
            * 100.0
        ),
        "max_drawdown_pct": max_dd * 100.0,
        "gross_pnl_thb": sum(
            t["gross_pnl_thb"]
            for t in trades
        ),
        "cost_thb": sum(
            t["cost_thb"]
            for t in trades
        ),
        "net_pnl_thb": sum(
            t["net_pnl_thb"]
            for t in trades
        ),
        "trades_detail": trades,
    }


def main():
    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_candidates(candles[:-2])

    results = []

    for trigger in TRIGGERS:
        for lock in LOCKS:
            if lock >= trigger:
                continue

            result = run_strategy(
                records,
                candles,
                trigger,
                lock,
            )

            results.append(result)

    output = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "candles": len(candles),
        "resolved_candidates": len(records),
        "starting_pot_thb": STARTING_POT_THB,
        "round_trip_cost_pct": ROUND_TRIP_COST * 100.0,
        "results": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("PROFIT LOCK ECONOMICS AUDIT V1")
    print("=" * 72)
    print(f"Candles             : {len(candles)}")
    print(f"Candidates          : {len(records)}")
    print(f"Starting Pot        : {STARTING_POT_THB:.2f} THB")
    print(
        f"Round-trip cost     : "
        f"{ROUND_TRIP_COST * 100:.4f}%"
    )
    print("=" * 72)

    for result in results:
        print(
            f"T={result['trigger_pct']:.2f}% "
            f"L={result['lock_pct']:.2f}% | "
            f"N={result['trades']} | "
            f"WR={result['win_rate_pct']:.2f}% | "
            f"Return={result['return_pct']:.4f}% | "
            f"End={result['ending_pot_thb']:.2f} | "
            f"DD={result['max_drawdown_pct']:.4f}% | "
            f"Lock={result['profit_lock_exits']} | "
            f"Fallback={result['fallback_exits']}"
        )

    print("=" * 72)
    print("Saved:", OUTPUT_FILE)
    print("=" * 72)


if __name__ == "__main__":
    main()
