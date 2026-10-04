import json
from pathlib import Path

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from money_machine_v2.research.profit_lock_reconcile import simulate_exit, calculate_gross_return
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

TRIGGER = 0.0030
LOCK = 0.0020
OUTPUT_FILE = Path("money_machine_v2/research/profit_lock_counterfactual_audit_v1.json")


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    records = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])
        fixed_exit_index = index.get(candidate["planned_exit_time"])

        if entry_index is None or fixed_exit_index is None:
            continue

        records.append({
            "candidate": candidate,
            "entry_index": entry_index,
            "fixed_exit_index": fixed_exit_index,
        })

    records.sort(key=lambda r: r["candidate"]["entry_time"])
    return records


def simulate_policy(records, candles, policy):
    pot = STARTING_POT_THB
    active_exit_time = None
    trades = []
    skipped_overlap = 0

    for record in records:
        candidate = record["candidate"]
        entry_time = candidate["entry_time"]

        if active_exit_time is not None and entry_time < active_exit_time:
            skipped_overlap += 1
            continue

        risk = evaluate_risk(
            decision={
                "signal": candidate["signal"],
                "confidence": 0,
                "quality": "PASSED",
            },
            features={
                "close": candidate["entry"],
                "atr14": candidate["features"]["atr"],
            },
            capital=pot / REFERENCE_USDTHB,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk.get("allowed"):
            continue

        position_value_thb = float(risk["position_value"]) * REFERENCE_USDTHB

        if policy == "NO_LOCK":
            exit_index = record["fixed_exit_index"]
            exit_price = candles[exit_index]["close"]
            exit_type = "FIXED_HORIZON"
        else:
            result = simulate_exit(
                candidate=candidate,
                entry_index=record["entry_index"],
                fixed_exit_index=record["fixed_exit_index"],
                candles=candles,
                trigger=TRIGGER,
                lock=LOCK,
            )

            if result is None:
                continue

            exit_index = result["exit_index"]
            exit_price = result["exit_price"]
            exit_type = result["exit_type"]

        gross_return = calculate_gross_return(
            candidate["signal"],
            candidate["entry"],
            exit_price,
        )

        gross_pnl = position_value_thb * gross_return
        cost = position_value_thb * ROUND_TRIP_COST
        net_pnl = gross_pnl - cost

        pot_before = pot
        pot += net_pnl

        trades.append({
            "entry_time": entry_time.isoformat(),
            "fixed_exit_time": candles[record["fixed_exit_index"]]["time"].isoformat(),
            "actual_exit_time": candles[exit_index]["time"].isoformat(),
            "entry": candidate["entry"],
            "exit_price": exit_price,
            "exit_type": exit_type,
            "gross_return_pct": gross_return * 100.0,
            "position_value_thb": position_value_thb,
            "gross_pnl_thb": gross_pnl,
            "cost_thb": cost,
            "net_pnl_thb": net_pnl,
            "pot_before_thb": pot_before,
            "pot_after_thb": pot,
        })

        active_exit_time = candles[exit_index]["time"]

    peak = STARTING_POT_THB
    max_dd = 0.0

    for trade in trades:
        peak = max(peak, trade["pot_after_thb"])
        if peak > 0:
            max_dd = min(max_dd, (trade["pot_after_thb"] - peak) / peak)

    return {
        "policy": policy,
        "trades": len(trades),
        "wins": sum(t["net_pnl_thb"] > 0 for t in trades),
        "losses": sum(t["net_pnl_thb"] < 0 for t in trades),
        "win_rate_pct": (
            sum(t["net_pnl_thb"] > 0 for t in trades) / len(trades) * 100
            if trades else 0.0
        ),
        "skipped_overlap": skipped_overlap,
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT_THB,
        "return_pct": (pot - STARTING_POT_THB) / STARTING_POT_THB * 100,
        "max_drawdown_pct": max_dd * 100,
        "gross_pnl_thb": sum(t["gross_pnl_thb"] for t in trades),
        "cost_thb": sum(t["cost_thb"] for t in trades),
        "net_pnl_thb": sum(t["net_pnl_thb"] for t in trades),
        "trades_detail": trades,
    }


def main():
    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)

    no_lock = simulate_policy(records, candles, "NO_LOCK")
    profit_lock = simulate_policy(records, candles, "PL_030_LOCK_020")

    no_lock_by_entry = {t["entry_time"]: t for t in no_lock["trades_detail"]}
    lock_by_entry = {t["entry_time"]: t for t in profit_lock["trades_detail"]}

    common_entries = sorted(set(no_lock_by_entry) & set(lock_by_entry))

    differences = []

    for entry_time in common_entries:
        a = no_lock_by_entry[entry_time]
        b = lock_by_entry[entry_time]

        if (
            a["actual_exit_time"] != b["actual_exit_time"]
            or abs(a["net_pnl_thb"] - b["net_pnl_thb"]) > 1e-12
        ):
            differences.append({
                "entry_time": entry_time,
                "fixed_exit": a["actual_exit_time"],
                "lock_exit": b["actual_exit_time"],
                "fixed_net_pnl_thb": a["net_pnl_thb"],
                "lock_net_pnl_thb": b["net_pnl_thb"],
                "net_pnl_difference_lock_minus_fixed_thb": (
                    b["net_pnl_thb"] - a["net_pnl_thb"]
                ),
            })

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "resolved_candidates": len(records),
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
        },
        "policies": {
            "NO_LOCK": no_lock,
            "PL_030_LOCK_020": profit_lock,
        },
        "comparison": {
            "ending_pot_difference_lock_minus_fixed_thb": (
                profit_lock["ending_pot_thb"] - no_lock["ending_pot_thb"]
            ),
            "net_profit_difference_lock_minus_fixed_thb": (
                profit_lock["net_profit_thb"] - no_lock["net_profit_thb"]
            ),
            "trade_count_difference_lock_minus_fixed": (
                profit_lock["trades"] - no_lock["trades"]
            ),
            "skipped_overlap_difference_lock_minus_fixed": (
                profit_lock["skipped_overlap"] - no_lock["skipped_overlap"]
            ),
            "common_entry_count": len(common_entries),
            "different_exit_count": len(differences),
            "trade_level_differences": differences,
        },
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 72)
    print("PROFIT LOCK COUNTERFACTUAL AUDIT V1")
    print("=" * 72)
    print(f"Candles              : {len(candles)}")
    print(f"Candidates           : {len(records)}")
    print()
    for result in (no_lock, profit_lock):
        print(
            f"{result['policy']:<20} "
            f"N={result['trades']} "
            f"WR={result['win_rate_pct']:.2f}% "
            f"Return={result['return_pct']:.4f}% "
            f"End={result['ending_pot_thb']:.4f} "
            f"DD={result['max_drawdown_pct']:.4f}% "
            f"Skip={result['skipped_overlap']}"
        )
    print()
    print(
        "Lock - Fixed End Pot : "
        f"{output['comparison']['ending_pot_difference_lock_minus_fixed_thb']:.4f} THB"
    )
    print(
        "Different exits      : "
        f"{output['comparison']['different_exit_count']}"
    )
    print(
        "Common entries       : "
        f"{output['comparison']['common_entry_count']}"
    )
    print("=" * 72)
    print("Saved:", OUTPUT_FILE)
    print("=" * 72)


if __name__ == "__main__":
    main()
