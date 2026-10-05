"""
DAILY PROFIT TARGET AUDIT V1
Research-only. Does not modify Core/MONEY_MAKER_01/Risk.
"""

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
    ROUND_TRIP_COST,
    STARTING_POT_THB,
)
from research_standard_v1 import WINDOW_30D_CANDLES
from risk import evaluate_risk

TARGETS = [5.0, 10.0, 15.0, 20.0, 25.0]


def run_target(candles, candidates, target):
    pot = STARTING_POT_THB
    day_profit = {}
    trades = []
    active_exit = None

    for c in candidates:
        entry_time = c["entry_time"]

        if active_exit is not None and entry_time <= active_exit:
            continue

        day = entry_time.date().isoformat()

        # Once daily target is reached, no more trades that day.
        if day_profit.get(day, 0.0) >= target:
            continue

        decision = {
            "signal": "BUY",
            "confidence": 0,
            "quality": "PASSED",
        }

        entry_candle = next(
            (
                x for x in candles
                if x["time"] == c["entry_time"]
            ),
            None,
        )

        if entry_candle is None:
            continue

        risk_features = dict(c["features"])
        risk_features["close"] = entry_candle["close"]
        risk_features["atr14"] = c["features"]["atr"]

        risk = evaluate_risk(
            decision,
            risk_features,
            capital=pot,
            daily_pnl=day_profit.get(day, 0.0),
            open_positions=0,
        )

        if not risk["allowed"]:
            continue

        entry = c["entry"]
        exit_index = next(
            (i for i, x in enumerate(candles)
             if x["time"] == c["planned_exit_time"]),
            None,
        )
        if exit_index is None:
            continue
        exit_price = candles[exit_index]["close"]
        exit_time = candles[exit_index]["time"]

        gross = (exit_price - entry) / entry * risk["position_value"]
        cost = risk["position_value"] * ROUND_TRIP_COST
        net = gross - cost

        pot += net
        day_profit[day] = day_profit.get(day, 0.0) + net

        trades.append({
            "entry_time": entry_time,
            "exit_time": exit_time.isoformat(),
            "net": net,
            "pot_after": pot,
        })

        active_exit = exit_time

    profitable_days = sum(v > 0 for v in day_profit.values())
    target_days = sum(v >= target for v in day_profit.values())
    total_net = pot - STARTING_POT_THB

    return {
        "target_thb": target,
        "end_pot_thb": pot,
        "net_thb": total_net,
        "return_pct": total_net / STARTING_POT_THB * 100,
        "days": len(day_profit),
        "profitable_days": profitable_days,
        "target_days": target_days,
        "target_hit_rate_pct": (
            target_days / len(day_profit) * 100 if day_profit else 0.0
        ),
        "trades": len(trades),
        "daily_profit": day_profit,
        "trades_detail": trades,
    }


def main():
    candles = fetch_closed_candles_paginated(
        "BTCUSDT",
        "5m",
        WINDOW_30D_CANDLES,
    )
    candidates = find_candidates(candles)

    print("=" * 72)
    print("DAILY PROFIT TARGET AUDIT V1")
    print("=" * 72)
    print(f"Candles    : {len(candles)}")
    print(f"Candidates : {len(candidates)}")
    print(f"Start Pot  : {STARTING_POT_THB:.2f} THB")
    print("-" * 72)

    results = []

    for target in TARGETS:
        r = run_target(candles, candidates, target)
        results.append(r)

        print(
            f"TARGET +{target:>5.0f} THB | "
            f"Net={r['net_thb']:>8.2f} | "
            f"End={r['end_pot_thb']:>8.2f} | "
            f"TargetDays={r['target_days']:>2}/{r['days']:<2} | "
            f"Trades={r['trades']:<3}"
        )

    out = {
        "audit": "DAILY_PROFIT_TARGET_AUDIT_V1",
        "candles": len(candles),
        "candidates": len(candidates),
        "starting_pot_thb": STARTING_POT_THB,
        "round_trip_cost": ROUND_TRIP_COST,
        "targets": results,
    }

    out_path = Path(__file__).with_suffix(".json")
    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("-" * 72)
    print(f"Saved      : {out_path.name}")


if __name__ == "__main__":
    main()
