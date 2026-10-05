import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

OUTPUT_FILE = Path("money_machine_v2/research/paired_entry_exit_audit_v1.json")


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])
        fixed_exit_index = index.get(candidate["planned_exit_time"])

        if entry_index is None or fixed_exit_index is None:
            continue

        rows.append({
            "candidate": candidate,
            "entry_index": entry_index,
            "fixed_exit_index": fixed_exit_index,
        })

    return sorted(rows, key=lambda r: r["candidate"]["entry_time"])


def get_position_value(candidate, pot):
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
        capital=pot / REFERENCE_USDTHB,
        daily_pnl=0.0,
        open_positions=0,
    )

    if not risk.get("allowed"):
        return None

    return float(risk["position_value"]) * REFERENCE_USDTHB


def settle(candidate, exit_price, position_value):
    gross_return = (
        exit_price - candidate["entry"]
    ) / candidate["entry"]

    gross = position_value * gross_return
    cost = position_value * ROUND_TRIP_COST
    net = gross - cost

    return gross, cost, net


def select_entries(records):
    selected = []
    active_exit = None
    skipped = 0

    for record in records:
        if active_exit is not None and record["entry_index"] < active_exit:
            skipped += 1
            continue

        selected.append(record)
        active_exit = record["fixed_exit_index"]

    return selected, skipped


def oracle_exit(entry, candles):
    peak = entry

    for candle in candles:
        peak = max(peak, candle["high"])

        mfe = peak / entry - 1.0

        giveback = (
            (peak - candle["close"]) / peak
            if peak > 0
            else 0.0
        )

        if mfe >= 0.0030 and giveback >= 0.0020:
            return True

    return False


def simulate_fixed(records, candles):
    pot = STARTING_POT_THB
    trades = []

    for number, record in enumerate(records, 1):
        candidate = record["candidate"]

        position_value = get_position_value(candidate, pot)

        if position_value is None:
            continue

        exit_index = record["fixed_exit_index"]

        gross, cost, net = settle(
            candidate,
            candles[exit_index]["close"],
            position_value,
        )

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": candles[exit_index]["time"].isoformat(),
            "exit_reason": "FIXED_HORIZON",
            "holding_bars": exit_index - record["entry_index"],
            "net_pnl_thb": net,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "pot_before_thb": pot,
            "pot_after_thb": pot + net,
        })

        pot += net

    return trades, pot


def simulate_oracle(records, candles):
    pot = STARTING_POT_THB
    trades = []

    for number, record in enumerate(records, 1):
        candidate = record["candidate"]

        position_value = get_position_value(candidate, pot)

        if position_value is None:
            continue

        entry_index = record["entry_index"]
        fixed_exit_index = record["fixed_exit_index"]

        exit_index = fixed_exit_index
        exit_reason = "FIXED_HORIZON"

        for visible_index in range(
            entry_index + 1,
            fixed_exit_index + 1,
        ):
            visible = candles[
                entry_index + 1:visible_index + 1
            ]

            if oracle_exit(candidate["entry"], visible):
                exit_index = visible_index
                exit_reason = "PEAK_GIVEBACK"
                break

        gross, cost, net = settle(
            candidate,
            candles[exit_index]["close"],
            position_value,
        )

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": candles[exit_index]["time"].isoformat(),
            "exit_reason": exit_reason,
            "holding_bars": exit_index - entry_index,
            "net_pnl_thb": net,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "pot_before_thb": pot,
            "pot_after_thb": pot + net,
        })

        pot += net

    return trades, pot


def main():
    print("=" * 72)
    print("PAIRED ENTRY / EXIT EFFECT AUDIT V1")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Candles      : {WINDOW_30D_CANDLES:,}")
    print(f"Starting Pot : {STARTING_POT_THB:.2f} THB")
    print("Entry set    : LOCKED")
    print("Opportunity  : BLOCKED")
    print("Lookahead    : BLOCKED")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)

    selected, skipped = select_entries(records)

    fixed_trades, fixed_pot = simulate_fixed(
        selected,
        candles,
    )

    oracle_trades, oracle_pot = simulate_oracle(
        selected,
        candles,
    )

    oracle_exits = sum(
        t["exit_reason"] == "PEAK_GIVEBACK"
        for t in oracle_trades
    )

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "candidates": len(records),
            "entry_set_locked": True,
            "opportunity_effect": "BLOCKED",
            "lookahead": False,
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
        },
        "entry_selection": {
            "selected_entries": len(selected),
            "skipped_overlap": skipped,
        },
        "fixed_horizon": {
            "trades": len(fixed_trades),
            "ending_pot_thb": fixed_pot,
            "net_profit_thb": fixed_pot - STARTING_POT_THB,
        },
        "sequential_oracle": {
            "trades": len(oracle_trades),
            "ending_pot_thb": oracle_pot,
            "net_profit_thb": oracle_pot - STARTING_POT_THB,
            "oracle_exits": oracle_exits,
            "fixed_exits": len(oracle_trades) - oracle_exits,
        },
        "effect": {
            "exit_effect_thb": oracle_pot - fixed_pot,
            "oracle_better": oracle_pot > fixed_pot,
            "same_entry_count": len(fixed_trades) == len(oracle_trades),
        },
        "fixed_trades": fixed_trades,
        "oracle_trades": oracle_trades,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("RESULT")
    print("-" * 72)
    print(
        f"Fixed Horizon : {fixed_pot:.2f} THB "
        f"({fixed_pot - STARTING_POT_THB:+.2f})"
    )
    print(
        f"Oracle Exit   : {oracle_pot:.2f} THB "
        f"({oracle_pot - STARTING_POT_THB:+.2f})"
    )
    print(
        f"Exit Effect   : {oracle_pot - fixed_pot:+.2f} THB"
    )
    print(f"Same Entries  : {len(fixed_trades) == len(oracle_trades)}")
    print(f"Oracle Exits  : {oracle_exits}")
    print(f"Saved         : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
