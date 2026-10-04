import json
from pathlib import Path

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from money_machine_v2.research.profit_lock_reconcile import (
    simulate_exit,
    calculate_gross_return,
)
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

TRIGGER = 0.0030
LOCK = 0.0020

OUTPUT_FILE = Path(
    "money_machine_v2/research/profit_lock_attribution_audit_v1.json"
)


def main():
    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    index = {
        candle["time"]: i
        for i, candle in enumerate(candles)
    }

    candidates = find_candidates(candles)

    records = []

    for candidate in candidates:
        entry_index = index[candidate["entry_time"]]
        fixed_exit_index = index[candidate["planned_exit_time"]]

        records.append(
            {
                "candidate": candidate,
                "entry_index": entry_index,
                "fixed_exit_index": fixed_exit_index,
            }
        )

    pot = STARTING_POT_THB
    active_exit_time = None
    rows = []

    for number, record in enumerate(records, start=1):
        candidate = record["candidate"]
        entry_time = candidate["entry_time"]

        if (
            active_exit_time is not None
            and entry_time < active_exit_time
        ):
            continue

        capital_usdt = pot / REFERENCE_USDTHB

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
            capital=capital_usdt,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk.get("allowed"):
            continue

        position_value_thb = (
            float(risk["position_value"])
            * REFERENCE_USDTHB
        )

        entry = candidate["entry"]
        entry_index = record["entry_index"]
        fixed_exit_index = record["fixed_exit_index"]

        peak_price = entry
        peak_index = entry_index

        for i in range(entry_index, fixed_exit_index + 1):
            if candles[i]["high"] > peak_price:
                peak_price = candles[i]["high"]
                peak_index = i

        mfe = (peak_price / entry) - 1.0

        exit_result = simulate_exit(
            candidate=candidate,
            entry_index=entry_index,
            fixed_exit_index=fixed_exit_index,
            candles=candles,
            trigger=TRIGGER,
            lock=LOCK,
        )

        if exit_result is None:
            continue

        exit_index = exit_result["exit_index"]
        exit_price = exit_result["exit_price"]

        gross_return = calculate_gross_return(
            candidate["signal"],
            entry,
            exit_price,
        )

        gross_pnl = position_value_thb * gross_return
        cost = position_value_thb * ROUND_TRIP_COST
        net_pnl = gross_pnl - cost

        pot_before = pot
        pot += net_pnl

        trigger_hit = mfe >= TRIGGER
        lock_exit = exit_result["exit_type"] == "PROFIT_LOCK"

        rows.append(
            {
                "trade_number": len(rows) + 1,
                "entry_time": entry_time.isoformat(),
                "exit_time": candles[exit_index]["time"].isoformat(),
                "entry": entry,
                "peak_price": peak_price,
                "peak_time": candles[peak_index]["time"].isoformat(),
                "mfe_pct": mfe * 100.0,
                "trigger_pct": TRIGGER * 100.0,
                "lock_pct": LOCK * 100.0,
                "trigger_hit": trigger_hit,
                "exit_type": exit_result["exit_type"],
                "exit_price": exit_price,
                "gross_return_pct": gross_return * 100.0,
                "position_value_thb": position_value_thb,
                "gross_pnl_thb": gross_pnl,
                "cost_thb": cost,
                "net_pnl_thb": net_pnl,
                "pot_before_thb": pot_before,
                "pot_after_thb": pot,
                "giveback_from_mfe_pct": (
                    (mfe - gross_return) * 100.0
                ),
            }
        )

        active_exit_time = candles[exit_index]["time"]

    summary = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "candles": len(candles),
        "resolved_candidates": len(candidates),
        "executed_trades": len(rows),
        "starting_pot_thb": STARTING_POT_THB,
        "trigger_pct": TRIGGER * 100.0,
        "lock_pct": LOCK * 100.0,
        "round_trip_cost_pct": ROUND_TRIP_COST * 100.0,
        "trigger_hits": sum(
            1 for r in rows if r["trigger_hit"]
        ),
        "profit_lock_exits": sum(
            1 for r in rows
            if r["exit_type"] == "PROFIT_LOCK"
        ),
        "fallback_exits": sum(
            1 for r in rows
            if r["exit_type"] == "FIXED_FALLBACK"
        ),
        "positive_net_trades": sum(
            1 for r in rows
            if r["net_pnl_thb"] > 0
        ),
        "negative_net_trades": sum(
            1 for r in rows
            if r["net_pnl_thb"] < 0
        ),
        "gross_pnl_thb": sum(
            r["gross_pnl_thb"] for r in rows
        ),
        "cost_thb": sum(
            r["cost_thb"] for r in rows
        ),
        "net_pnl_thb": sum(
            r["net_pnl_thb"] for r in rows
        ),
        "ending_pot_thb": pot,
        "average_mfe_pct": (
            sum(r["mfe_pct"] for r in rows) / len(rows)
            if rows else 0.0
        ),
        "average_giveback_pct": (
            sum(r["giveback_from_mfe_pct"] for r in rows)
            / len(rows)
            if rows else 0.0
        ),
    }

    output = {
        "summary": summary,
        "trades": rows,
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
    print("PROFIT LOCK ATTRIBUTION AUDIT V1")
    print("=" * 72)
    print(f"Candles             : {len(candles)}")
    print(f"Candidates          : {len(candidates)}")
    print(f"Executed trades     : {len(rows)}")
    print(f"Trigger             : {TRIGGER * 100:.2f}%")
    print(f"Lock                : {LOCK * 100:.2f}%")
    print(f"Trigger hits        : {summary['trigger_hits']}")
    print(f"Profit Lock exits   : {summary['profit_lock_exits']}")
    print(f"Fallback exits      : {summary['fallback_exits']}")
    print(f"Gross P/L           : {summary['gross_pnl_thb']:.4f} THB")
    print(f"Cost                : {summary['cost_thb']:.4f} THB")
    print(f"Net P/L             : {summary['net_pnl_thb']:.4f} THB")
    print(f"Ending Pot          : {summary['ending_pot_thb']:.4f} THB")
    print(f"Average MFE         : {summary['average_mfe_pct']:.4f}%")
    print(f"Average Giveback    : {summary['average_giveback_pct']:.4f}%")
    print("=" * 72)
    print("Saved:", OUTPUT_FILE)
    print("=" * 72)


if __name__ == "__main__":
    main()
