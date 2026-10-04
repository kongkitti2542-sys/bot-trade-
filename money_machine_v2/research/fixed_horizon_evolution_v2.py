"""Research-only Fixed Horizon Evolution V2.

Purpose:
- Test whether the Fixed Horizon Evolution V1 result is robust across
  the locked Research Standard V1 windows: 7D and 30D.
- Keep MONEY_MAKER_01 entry logic unchanged.
- Keep entry selection locked to Fixed Horizon 20 inside each window.
- Freeze position value per entry so horizon comparisons isolate horizon.

No production changes. AI, Profit Lock and Giveback are not used.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOWS
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

ENTRY_LOCK_HORIZON = 20
HORIZONS = (10, 15, 20, 25, 30)
WINDOW_NAMES = ("7D", "30D")

OUTPUT_FILE = Path(
    "money_machine_v2/research/fixed_horizon_evolution_v2.json"
)


def build_records(candles):
    index = {candle["time"]: i for i, candle in enumerate(candles)}
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

    return sorted(rows, key=lambda row: row["candidate"]["entry_time"])


def select_entries(records):
    selected = []
    active_exit = None
    skipped_overlap = 0

    for record in records:
        if active_exit is not None and record["entry_index"] < active_exit:
            skipped_overlap += 1
            continue

        selected.append(record)
        active_exit = record["fixed_exit_index"]

    return selected, skipped_overlap


def get_position_value(candidate):
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
        capital=STARTING_POT_THB / REFERENCE_USDTHB,
        daily_pnl=0.0,
        open_positions=0,
    )

    if not risk.get("allowed"):
        return None

    return float(risk["position_value"]) * REFERENCE_USDTHB


def prepare_entries(selected):
    prepared = []

    for record in selected:
        position_value = get_position_value(record["candidate"])
        if position_value is None:
            continue

        prepared.append({
            **record,
            "position_value_thb": position_value,
        })

    return prepared


def settle(candidate, exit_price, position_value):
    gross_return = (exit_price - candidate["entry"]) / candidate["entry"]
    gross_pnl = position_value * gross_return
    cost = position_value * ROUND_TRIP_COST
    return gross_pnl, cost, gross_pnl - cost


def summarize(trades):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "avg_net_per_trade_thb": 0.0,
            "profit_factor": None,
        }

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100.0,
        "avg_net_per_trade_thb": sum(t["net_pnl_thb"] for t in trades) / len(trades),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
    }


def simulate(prepared, candles, horizon):
    trades = []
    pot = STARTING_POT_THB

    for number, record in enumerate(prepared, start=1):
        candidate = record["candidate"]
        exit_index = record["entry_index"] + horizon

        if exit_index >= len(candles):
            raise RuntimeError(
                f"HORIZON_EXIT_OUT_OF_RANGE: horizon={horizon}, "
                f"entry_index={record['entry_index']}, "
                f"exit_index={exit_index}, candles={len(candles)}"
            )

        exit_candle = candles[exit_index]
        gross, cost, net = settle(
            candidate,
            exit_candle["close"],
            record["position_value_thb"],
        )

        pot_before = pot
        pot += net

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": exit_candle["time"].isoformat(),
            "holding_bars": horizon,
            "entry_price": candidate["entry"],
            "exit_price": exit_candle["close"],
            "position_value_thb": record["position_value_thb"],
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "net_pnl_thb": net,
            "pot_before_thb": pot_before,
            "pot_after_thb": pot,
            "exit_reason": f"FIXED_HORIZON_{horizon}",
        })

    return {
        **summarize(trades),
        "horizon_bars": horizon,
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT_THB,
        "trades_detail": trades,
    }


def run_window(window_name, candle_count):
    print()
    print("=" * 72)
    print(f"WINDOW: {window_name}")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL, INTERVAL, candle_count
    )

    if len(candles) != candle_count:
        raise RuntimeError(
            f"INVALID_RESEARCH_WINDOW: window={window_name}, "
            f"expected={candle_count}, actual={len(candles)}"
        )

    records = build_records(candles)
    selected, skipped_overlap = select_entries(records)
    prepared = prepare_entries(selected)

    if len(prepared) != len(selected):
        raise RuntimeError(
            f"POSITION_PREPARATION_MISMATCH: window={window_name}, "
            f"selected={len(selected)}, prepared={len(prepared)}"
        )

    print(f"Candles              : {len(candles):,}")
    print(f"Period               : {candles[0]['time']} -> {candles[-1]['time']}")
    print(f"Candidates            : {len(records)}")
    print(f"Selected entries      : {len(selected)}")
    print(f"Prepared entries      : {len(prepared)}")
    print(f"Skipped overlap       : {skipped_overlap}")

    if not prepared:
        raise RuntimeError(f"NO_PREPARED_ENTRIES: window={window_name}")

    horizons = {}
    for horizon in HORIZONS:
        result = simulate(prepared, candles, horizon)
        horizons[str(horizon)] = result

        print(
            f"H{horizon:02d}: "
            f"WR={result['win_rate_pct']:.2f}% | "
            f"PF={result['profit_factor']:.4f} | "
            f"Net={result['net_profit_thb']:+.2f} THB | "
            f"Pot={result['ending_pot_thb']:.2f} THB"
        )

    return {
        "window": window_name,
        "candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "entry_selection": {
            "candidates": len(records),
            "selected_entries": len(selected),
            "prepared_entries": len(prepared),
            "skipped_overlap": skipped_overlap,
        },
        "horizons": horizons,
    }


def main():
    print("=" * 72)
    print("FIXED HORIZON EVOLUTION V2")
    print("=" * 72)
    print(f"Symbol              : {SYMBOL}")
    print(f"Interval            : {INTERVAL}")
    print(f"Windows             : {list(WINDOW_NAMES)}")
    print(f"Entry Lock Horizon  : {ENTRY_LOCK_HORIZON} bars")
    print(f"Test Horizons       : {list(HORIZONS)}")
    print(f"Starting Pot        : {STARTING_POT_THB:.2f} THB")
    print(f"Round-trip Cost     : {ROUND_TRIP_COST * 100:.4f}%")
    print("Entry Set            : LOCKED TO FIXED HORIZON 20")
    print("Position Size        : FROZEN PER ENTRY")
    print("Opportunity Effect   : BLOCKED")
    print("Lookahead            : BLOCKED")
    print("AI                   : NOT USED")
    print("Profit Lock          : NOT USED")
    print("Giveback             : NOT USED")
    print("Production Changed   : NO")
    print("Execution            : NONE")
    print("=" * 72)

    window_results = {}
    for window_name in WINDOW_NAMES:
        window_results[window_name] = run_window(
            window_name,
            WINDOWS[window_name],
        )

    output = {
        "research_version": "FIXED_HORIZON_EVOLUTION_V2",
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "windows": {
                name: WINDOWS[name] for name in WINDOW_NAMES
            },
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "entry_set_policy": "LOCKED_TO_FIXED_HORIZON_20_PER_WINDOW",
            "position_size_policy": "FROZEN_PER_ENTRY",
            "opportunity_effect": "BLOCKED",
            "lookahead_blocked": True,
            "ai_used": False,
            "profit_lock_used": False,
            "giveback_used": False,
            "production_changed": False,
            "execution": "NONE",
        },
        "windows": window_results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print(f"Saved: {OUTPUT_FILE}")
    print("=" * 72)


if __name__ == "__main__":
    main()
