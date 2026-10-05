"""Research-only Fixed Horizon Evolution V4.

Purpose:
- Test Fixed Horizon 10/15/20/25/30 with TRUE sequential Pot compounding.
- Each trade sizes from the current Pot immediately before that trade.
- Both profits and losses flow into Pot and become the next trade's capital base.
- Keep MONEY_MAKER_01 entry logic unchanged.
- Entry set remains locked to Fixed Horizon 20 per research window.
- Overlap remains blocked.

This version is intentionally different from V3:
V3 froze position value per entry to isolate horizon effect.
V4 uses dynamic position sizing from the current Pot to model
the user's intended compounding behavior.

Research only. No production changes.
AI, Profit Lock, Giveback and execution are not used.
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
WINDOWS = {**WINDOWS, "1D": 288}
WINDOW_NAMES = ("1D", "7D", "30D")

OUTPUT_FILE = Path(
    "money_machine_v2/research/fixed_horizon_evolution_v4.json"
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


def get_dynamic_position_value(candidate, pot_thb):
    if pot_thb <= 0:
        raise RuntimeError(
            f"NON_POSITIVE_POT_BEFORE_TRADE: pot={pot_thb}"
        )

    decision = {
        "signal": candidate["signal"],
        "confidence": 0,
        "quality": "PASSED",
    }
    features = {
        "close": candidate["entry"],
        "atr14": candidate["features"]["atr"],
    }

    capital_usdt = pot_thb / REFERENCE_USDTHB

    risk = evaluate_risk(
        decision=decision,
        features=features,
        capital=capital_usdt,
        daily_pnl=0.0,
        open_positions=0,
    )

    if not risk.get("allowed"):
        raise RuntimeError(
            "RISK_REJECTED_DURING_RESEARCH: "
            f"reason={risk.get('reason')}, pot_thb={pot_thb}"
        )

    return float(risk["position_value"]) * REFERENCE_USDTHB


def settle(candidate, exit_price, position_value):
    gross_return = (exit_price - candidate["entry"]) / candidate["entry"]
    gross_pnl = position_value * gross_return
    cost = position_value * ROUND_TRIP_COST
    return gross_pnl, cost, gross_pnl - cost


def summarize_daily(trades):
    daily = {}
    for trade in trades:
        day = trade["entry_time"][:10]
        daily[day] = daily.get(day, 0.0) + trade["net_pnl_thb"]

    values = list(daily.values())
    positive = [v for v in values if v > 0]
    negative = [v for v in values if v < 0]

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    return {
        "active_days": len(values),
        "positive_days": len(positive),
        "negative_days": len(negative),
        "flat_days": len(values) - len(positive) - len(negative),
        "positive_day_rate_pct": (
            len(positive) / len(values) * 100.0 if values else 0.0
        ),
        "avg_daily_net_thb": (
            sum(values) / len(values) if values else 0.0
        ),
        "best_day_net_thb": max(values) if values else 0.0,
        "worst_day_net_thb": min(values) if values else 0.0,
        "max_daily_drawdown_thb": max_drawdown,
        "daily_net_pnl_thb": daily,
    }


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
        "avg_net_per_trade_thb": (
            sum(t["net_pnl_thb"] for t in trades) / len(trades)
        ),
        "profit_factor": (
            gross_profit / gross_loss if gross_loss > 0 else None
        ),
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

        pot_before = pot

        # TRUE COMPOUNDING:
        # position value is calculated from the Pot that exists immediately
        # before this trade. Both profit and loss therefore affect the next trade.
        position_value = get_dynamic_position_value(candidate, pot_before)

        exit_candle = candles[exit_index]
        gross, cost, net = settle(
            candidate,
            exit_candle["close"],
            position_value,
        )

        pot += net

        if pot <= 0:
            raise RuntimeError(
                f"NON_POSITIVE_POT_AFTER_TRADE: "
                f"trade={number}, pot={pot}"
            )

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": exit_candle["time"].isoformat(),
            "holding_bars": horizon,
            "entry_price": candidate["entry"],
            "exit_price": exit_candle["close"],
            "pot_before_thb": pot_before,
            "position_value_thb": position_value,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "net_pnl_thb": net,
            "pot_after_thb": pot,
            "position_value_pct_of_pot": (
                position_value / pot_before * 100.0
            ),
            "exit_reason": f"FIXED_HORIZON_{horizon}",
        })

    return {
        **summarize(trades),
        "daily_summary": summarize_daily(trades),
        "horizon_bars": horizon,
        "starting_pot_thb": STARTING_POT_THB,
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT_THB,
        "return_pct": (
            (pot / STARTING_POT_THB - 1.0) * 100.0
        ),
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

    if not selected:
        raise RuntimeError(
            f"NO_SELECTED_ENTRIES: window={window_name}"
        )

    print(f"Candles              : {len(candles):,}")
    print(f"Period               : {candles[0]['time']} -> {candles[-1]['time']}")
    print(f"Candidates            : {len(records)}")
    print(f"Selected entries      : {len(selected)}")
    print(f"Skipped overlap       : {skipped_overlap}")
    print("Position Size         : DYNAMIC FROM CURRENT POT")

    horizons = {}

    for horizon in HORIZONS:
        result = simulate(selected, candles, horizon)
        horizons[str(horizon)] = result

        print(
            f"H{horizon:02d}: "
            f"WR={result['win_rate_pct']:.2f}% | "
            f"PF={result['profit_factor']:.4f} | "
            f"Net={result['net_profit_thb']:+.2f} THB | "
            f"Pot={result['ending_pot_thb']:.2f} THB | "
            f"Return={result['return_pct']:+.2f}%"
        )

    return {
        "window": window_name,
        "candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "entry_selection": {
            "candidates": len(records),
            "selected_entries": len(selected),
            "skipped_overlap": skipped_overlap,
        },
        "horizons": horizons,
    }


def main():
    print("=" * 72)
    print("FIXED HORIZON EVOLUTION V4 - TRUE POT COMPOUNDING")
    print("=" * 72)
    print(f"Symbol              : {SYMBOL}")
    print(f"Interval            : {INTERVAL}")
    print(f"Windows             : {list(WINDOW_NAMES)}")
    print("1D                   : 288 closed 5m candles")
    print(f"Entry Lock Horizon  : {ENTRY_LOCK_HORIZON} bars")
    print(f"Test Horizons       : {list(HORIZONS)}")
    print(f"Starting Pot        : {STARTING_POT_THB:.2f} THB")
    print(f"Round-trip Cost     : {ROUND_TRIP_COST * 100:.4f}%")
    print("Entry Set            : LOCKED TO FIXED HORIZON 20")
    print("Position Size        : DYNAMIC FROM CURRENT POT")
    print("Compounding          : PROFIT + LOSS -> NEXT POT")
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
        "research_version": "FIXED_HORIZON_EVOLUTION_V4",
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "windows": {
                name: WINDOWS[name] for name in WINDOW_NAMES
            },
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "entry_set_policy": "LOCKED_TO_FIXED_HORIZON_20_PER_WINDOW",
            "position_size_policy": "DYNAMIC_FROM_CURRENT_POT",
            "pot_compounding": "PROFIT_AND_LOSS_FLOW_TO_NEXT_TRADE",
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
