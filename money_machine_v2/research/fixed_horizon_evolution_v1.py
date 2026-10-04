"""Research-only Fixed Horizon Evolution V1.

Purpose:
- Evolve the MONEY_MAKER_01 holding horizon without changing entry logic.
- Keep the entry set locked to the current Fixed Horizon 20 selection rule.
- Freeze position value per selected entry so horizon comparisons isolate exit-horizon effect.

Research Standard:
- BTCUSDT / 5m
- 8,640 closed candles
- Starting pot: 1,500 THB
- Round-trip research cost: 0.1400%
- Real Risk Manager
- Overlap blocked during entry selection
- AI NOT USED
- Profit Lock NOT USED
- Giveback NOT USED
- No production changes
- Execution NONE

This file does not modify MONEY_MAKER_01, Risk, Core, or any production file.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
)
from research_standard_v1 import (
    SYMBOL,
    INTERVAL,
    WINDOW_30D_CANDLES,
)
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import (
    find_candidates,
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

ENTRY_LOCK_HORIZON = 20
HORIZONS = (10, 15, 20, 25, 30)

OUTPUT_FILE = Path(
    "money_machine_v2/research/fixed_horizon_evolution_v1.json"
)


def build_records(candles):
    """Build resolved MONEY_MAKER_01 candidates."""
    index = {
        candle["time"]: i
        for i, candle in enumerate(candles)
    }

    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(
            candidate["entry_time"]
        )
        fixed_exit_index = index.get(
            candidate["planned_exit_time"]
        )

        if entry_index is None:
            continue

        if fixed_exit_index is None:
            continue

        rows.append(
            {
                "candidate": candidate,
                "entry_index": entry_index,
                "fixed_exit_index": fixed_exit_index,
            }
        )

    return sorted(
        rows,
        key=lambda row: row["candidate"]["entry_time"],
    )


def select_entries(records):
    """Lock the entry set using the current 20-bar rule."""
    selected = []
    active_exit = None
    skipped_overlap = 0

    for record in records:
        if (
            active_exit is not None
            and record["entry_index"] < active_exit
        ):
            skipped_overlap += 1
            continue

        selected.append(record)

        # Entry selection is locked to the existing 20-bar
        # MONEY_MAKER_01 fixed-horizon boundary.
        active_exit = record["fixed_exit_index"]

    return selected, skipped_overlap


def get_position_value(candidate):
    """Freeze position value using the real Risk Manager."""
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

    return (
        float(risk["position_value"])
        * REFERENCE_USDTHB
    )


def prepare_entries(selected):
    """Freeze one position value for every selected entry."""
    prepared = []

    for record in selected:
        position_value = get_position_value(
            record["candidate"]
        )

        if position_value is None:
            continue

        prepared.append(
            {
                **record,
                "position_value_thb": position_value,
            }
        )

    return prepared


def settle(candidate, exit_price, position_value):
    gross_return = (
        exit_price - candidate["entry"]
    ) / candidate["entry"]

    gross_pnl = position_value * gross_return
    cost = position_value * ROUND_TRIP_COST
    net_pnl = gross_pnl - cost

    return gross_pnl, cost, net_pnl


def summarize_trades(trades):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "avg_net_per_trade_thb": 0.0,
            "profit_factor": None,
        }

    wins = [
        trade["net_pnl_thb"]
        for trade in trades
        if trade["net_pnl_thb"] > 0
    ]

    losses = [
        trade["net_pnl_thb"]
        for trade in trades
        if trade["net_pnl_thb"] < 0
    ]

    total_net = sum(
        trade["net_pnl_thb"]
        for trade in trades
    )

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (
            len(wins) / len(trades) * 100.0
        ),
        "avg_net_per_trade_thb": (
            total_net / len(trades)
        ),
        "profit_factor": profit_factor,
    }


def simulate_horizon(prepared, candles, horizon):
    """Evaluate one horizon using identical entries and position values."""
    trades = []
    pot = STARTING_POT_THB

    for number, record in enumerate(
        prepared,
        start=1,
    ):
        candidate = record["candidate"]
        entry_index = record["entry_index"]
        position_value = record[
            "position_value_thb"
        ]

        exit_index = entry_index + horizon

        if exit_index >= len(candles):
            raise RuntimeError(
                "HORIZON_EXIT_OUT_OF_RANGE: "
                f"horizon={horizon}, "
                f"entry_index={entry_index}, "
                f"exit_index={exit_index}, "
                f"candles={len(candles)}"
            )

        exit_candle = candles[exit_index]

        gross_pnl, cost, net_pnl = settle(
            candidate,
            exit_candle["close"],
            position_value,
        )

        pot_before = pot
        pot += net_pnl

        trades.append(
            {
                "trade_number": number,
                "entry_time": candidate[
                    "entry_time"
                ].isoformat(),
                "exit_time": exit_candle[
                    "time"
                ].isoformat(),
                "holding_bars": horizon,
                "entry_price": candidate["entry"],
                "exit_price": exit_candle["close"],
                "position_value_thb": position_value,
                "gross_pnl_thb": gross_pnl,
                "cost_thb": cost,
                "net_pnl_thb": net_pnl,
                "pot_before_thb": pot_before,
                "pot_after_thb": pot,
                "exit_reason": f"FIXED_HORIZON_{horizon}",
            }
        )

    summary = summarize_trades(trades)

    return {
        **summary,
        "horizon_bars": horizon,
        "ending_pot_thb": pot,
        "net_profit_thb": (
            pot - STARTING_POT_THB
        ),
        "trades_detail": trades,
    }


def main():
    print("=" * 72)
    print("FIXED HORIZON EVOLUTION V1")
    print("=" * 72)
    print(f"Symbol              : {SYMBOL}")
    print(f"Interval            : {INTERVAL}")
    print(
        f"Research candles    : "
        f"{WINDOW_30D_CANDLES:,}"
    )
    print(
        f"Starting Pot        : "
        f"{STARTING_POT_THB:,.2f} THB"
    )
    print(
        f"Entry Lock Horizon  : "
        f"{ENTRY_LOCK_HORIZON} bars"
    )
    print(
        f"Test Horizons       : "
        f"{list(HORIZONS)}"
    )
    print(
        f"Round-trip Cost     : "
        f"{ROUND_TRIP_COST * 100:.4f}%"
    )
    print("Entry Set            : LOCKED")
    print("Position Size        : FROZEN PER ENTRY")
    print("Overlap              : BLOCKED")
    print("AI                   : NOT USED")
    print("Profit Lock          : NOT USED")
    print("Giveback             : NOT USED")
    print("Production Changed   : NO")
    print("Execution            : NONE")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    if len(candles) != WINDOW_30D_CANDLES:
        raise RuntimeError(
            "INVALID_RESEARCH_WINDOW: "
            f"expected={WINDOW_30D_CANDLES}, "
            f"actual={len(candles)}"
        )

    print(
        f"Candles              : {len(candles):,}"
    )
    print(
        f"Period               : "
        f"{candles[0]['time']} -> "
        f"{candles[-1]['time']}"
    )

    records = build_records(candles)

    print(
        f"MONEY_MAKER_01 candidates : "
        f"{len(records)}"
    )

    selected, skipped_overlap = select_entries(
        records
    )

    prepared = prepare_entries(selected)

    if len(prepared) != len(selected):
        raise RuntimeError(
            "POSITION_PREPARATION_MISMATCH: "
            f"selected={len(selected)}, "
            f"prepared={len(prepared)}"
        )

    print(
        f"Selected entries      : "
        f"{len(selected)}"
    )
    print(
        f"Prepared entries      : "
        f"{len(prepared)}"
    )
    print(
        f"Skipped overlap       : "
        f"{skipped_overlap}"
    )

    if not prepared:
        raise RuntimeError(
            "NO_PREPARED_ENTRIES"
        )

    results = {}

    for horizon in HORIZONS:
        result = simulate_horizon(
            prepared,
            candles,
            horizon,
        )

        results[str(horizon)] = result

        print()
        print(
            f"Horizon {horizon:>2} bars"
        )
        print("-" * 72)
        print(
            f"Trades       : {result['trades']}"
        )
        print(
            f"Win Rate     : "
            f"{result['win_rate_pct']:.2f}%"
        )
        print(
            f"Ending Pot   : "
            f"{result['ending_pot_thb']:.2f} THB"
        )
        print(
            f"Net Profit   : "
            f"{result['net_profit_thb']:+.2f} THB"
        )
        print(
            f"Avg Net/Trade: "
            f"{result['avg_net_per_trade_thb']:+.4f} THB"
        )
        print(
            f"Profit Factor: "
            f"{result['profit_factor']}"
        )

    output = {
        "research_version": "FIXED_HORIZON_EVOLUTION_V1",
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "first_candle": candles[
                0
            ]["time"].isoformat(),
            "last_candle": candles[
                -1
            ]["time"].isoformat(),
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": (
                ROUND_TRIP_COST * 100
            ),
            "entry_set_policy": (
                "LOCKED_TO_FIXED_HORIZON_20"
            ),
            "position_size_policy": (
                "FROZEN_PER_ENTRY"
            ),
            "opportunity_effect": "BLOCKED",
            "lookahead_blocked": True,
            "ai_used": False,
            "profit_lock_used": False,
            "giveback_used": False,
            "production_changed": False,
            "execution": "NONE",
        },
        "entry_selection": {
            "candidates": len(records),
            "selected_entries": len(selected),
            "prepared_entries": len(prepared),
            "skipped_overlap": skipped_overlap,
        },
        "horizons": results,
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
    print("=" * 72)
    print(
        f"Saved: {OUTPUT_FILE}"
    )
    print("=" * 72)


if __name__ == "__main__":
    main()
