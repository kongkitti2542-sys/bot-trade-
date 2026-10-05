"""Research-only MONEY_MAKER_01 Entry Quality Gate V4.

Walk-forward robustness with live-compatible indicator context and one continuous
OOS Pot across chronological test folds.

This version is a methodology correction of V3, not a production change.

Rules:
- BTCUSDT 5m, one 30D closed-candle snapshot.
- H10 evaluation.
- Features are calculated ONCE on the full snapshot before train/test splitting,
  so EMA50/ATR/relative-volume state at a fold boundary has prior-candle context.
- Gate selection uses TRAIN only.
- Test folds are chronological and non-overlapping.
- Selected TEST entries from all folds are merged chronologically and simulated
  through ONE continuous Pot. Profit/loss flows into the next trade.
- Same predeclared gate grid as V3; no new threshold is introduced after seeing
  results.
- No AI, Profit Lock, Giveback, execution, or production change.
- No random search and no post-hoc threshold selection.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL
from validate_atr_expansion_ema50 import (
    ATR_PERIOD,
    ATR_LOOKBACK,
    FEE_PER_SIDE,
    SLIPPAGE_PER_SIDE,
    calculate_atr,
    calculate_ema,
    calculate_relative_volume,
)
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE
EVALUATION_HORIZON = 10
CANDLE_COUNT = 8640

BASE_ATR_EXPANSION = 1.25
BASE_RV_THRESHOLD = 1.50
CANDLE_RANGE_ATR_MIN = 1.0
EMA_PERIOD = 50
MIN_TRAIN_TRADES = 5

GATES = (
    {"name": "BASELINE", "min_body_ratio": 0.00, "min_close_location": 0.00, "min_ema50_distance": 0.0000, "min_relative_volume": 1.50, "min_atr_expansion": 1.25},
    {"name": "BODY_50", "min_body_ratio": 0.50, "min_close_location": 0.00, "min_ema50_distance": 0.0000, "min_relative_volume": 1.50, "min_atr_expansion": 1.25},
    {"name": "BODY_70", "min_body_ratio": 0.70, "min_close_location": 0.00, "min_ema50_distance": 0.0000, "min_relative_volume": 1.50, "min_atr_expansion": 1.25},
    {"name": "CLOSE_LOC_70", "min_body_ratio": 0.00, "min_close_location": 0.70, "min_ema50_distance": 0.0000, "min_relative_volume": 1.50, "min_atr_expansion": 1.25},
    {"name": "EMA50_DIST_010", "min_body_ratio": 0.00, "min_close_location": 0.00, "min_ema50_distance": 0.0010, "min_relative_volume": 1.50, "min_atr_expansion": 1.25},
    {"name": "RV_1.80", "min_body_ratio": 0.00, "min_close_location": 0.00, "min_ema50_distance": 0.0000, "min_relative_volume": 1.80, "min_atr_expansion": 1.25},
    {"name": "ATR_1.30", "min_body_ratio": 0.00, "min_close_location": 0.00, "min_ema50_distance": 0.0000, "min_relative_volume": 1.50, "min_atr_expansion": 1.30},
    {"name": "BODY60_CLOSE70", "min_body_ratio": 0.60, "min_close_location": 0.70, "min_ema50_distance": 0.0000, "min_relative_volume": 1.50, "min_atr_expansion": 1.25},
    {"name": "BODY60_CLOSE70_RV180", "min_body_ratio": 0.60, "min_close_location": 0.70, "min_ema50_distance": 0.0000, "min_relative_volume": 1.80, "min_atr_expansion": 1.25},
    {"name": "QUALITY_STRICT", "min_body_ratio": 0.60, "min_close_location": 0.70, "min_ema50_distance": 0.0010, "min_relative_volume": 1.80, "min_atr_expansion": 1.30},
)

FOLDS = (
    {"name": "FOLD_1", "train_start_day": 1, "train_end_day": 15, "test_start_day": 16, "test_end_day": 20},
    {"name": "FOLD_2", "train_start_day": 1, "train_end_day": 20, "test_start_day": 21, "test_end_day": 25},
    {"name": "FOLD_3", "train_start_day": 1, "train_end_day": 25, "test_start_day": 26, "test_end_day": 30},
)

OUTPUT_FILE = Path("money_machine_v2/research/money_maker_01_entry_quality_gate_v4.json")


def prepare_features(candles):
    atr = calculate_atr(candles)
    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, EMA_PERIOD)
    relative_volume = calculate_relative_volume(candles)
    return atr, ema50, relative_volume


def calculate_base_candidates(candles):
    atr, ema50, relative_volume = prepare_features(candles)
    return build_base_candidates(candles, atr, ema50, relative_volume)


def build_base_candidates(candles, atr, ema50, relative_volume):
    candidates = []
    start = max(ATR_PERIOD + ATR_LOOKBACK, EMA_PERIOD)
    end = len(candles) - EVALUATION_HORIZON - 2

    for i in range(start, max(start, end + 1)):
        if atr[i] is None or ema50[i] is None or relative_volume[i] is None:
            continue

        recent_atr = [atr[j] for j in range(i - ATR_LOOKBACK, i) if atr[j] is not None]
        if len(recent_atr) != ATR_LOOKBACK:
            continue

        avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
        expansion_ratio = atr[i] / avg_recent_atr
        candle_range = candles[i]["high"] - candles[i]["low"]
        if candle_range <= 0:
            continue

        if not (
            expansion_ratio >= BASE_ATR_EXPANSION
            and candle_range >= atr[i] * CANDLE_RANGE_ATR_MIN
            and candles[i]["close"] > candles[i]["open"]
            and candles[i]["close"] > candles[i - 1]["close"]
            and relative_volume[i] >= BASE_RV_THRESHOLD
            and candles[i]["close"] > ema50[i]
        ):
            continue

        candidates.append({
            "signal_time": candles[i]["time"],
            "entry_time": candles[i + 1]["time"],
            "entry": candles[i + 1]["open"],
            "features": {
                "atr": atr[i],
                "atr_expansion_ratio": expansion_ratio,
                "candle_range": candle_range,
                "relative_volume": relative_volume[i],
                "ema50": ema50[i],
                "ema50_distance": (candles[i]["close"] / ema50[i]) - 1.0,
                "body_ratio": abs(candles[i]["close"] - candles[i]["open"]) / candle_range,
                "close_location": (candles[i]["close"] - candles[i]["low"]) / candle_range,
            },
        })

    return candidates


def apply_gate(candidates, gate):
    return [
        c for c in candidates
        if c["features"]["body_ratio"] >= gate["min_body_ratio"]
        and c["features"]["close_location"] >= gate["min_close_location"]
        and c["features"]["ema50_distance"] >= gate["min_ema50_distance"]
        and c["features"]["relative_volume"] >= gate["min_relative_volume"]
        and c["features"]["atr_expansion_ratio"] >= gate["min_atr_expansion"]
    ]


def index_candidates(candles, candidates):
    index = {c["time"]: i for i, c in enumerate(candles)}
    rows = []
    for candidate in candidates:
        idx = index.get(candidate["entry_time"])
        if idx is not None:
            rows.append({"candidate": candidate, "entry_index": idx})
    return sorted(rows, key=lambda x: x["candidate"]["entry_time"])


def select_non_overlapping(records):
    selected = []
    active_exit = None
    skipped = 0
    for record in records:
        idx = record["entry_index"]
        if active_exit is not None and idx < active_exit:
            skipped += 1
            continue
        selected.append(record)
        active_exit = idx + EVALUATION_HORIZON
    return selected, skipped


def day_number(candle_time, first_day):
    return (candle_time.date() - first_day).days + 1


def get_dynamic_position_value(candidate, pot_thb):
    decision = {"signal": "BUY", "confidence": 0, "quality": "PASSED"}
    features = {"close": candidate["entry"], "atr14": candidate["features"]["atr"]}
    risk = evaluate_risk(
        decision=decision,
        features=features,
        capital=pot_thb / REFERENCE_USDTHB,
        daily_pnl=0.0,
        open_positions=0,
    )
    if not risk.get("allowed"):
        raise RuntimeError(f"RISK_REJECTED_DURING_RESEARCH: {risk.get('reason')}")
    return float(risk["position_value"]) * REFERENCE_USDTHB


def summarize_trades(trades, start_pot):
    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    daily = defaultdict(float)
    for t in trades:
        daily[t["entry_time"][:10]] += t["net_pnl_thb"]

    values = list(daily.values())
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    ending_pot = start_pot + sum(t["net_pnl_thb"] for t in trades)

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100.0 if trades else 0.0,
        "avg_net_per_trade_thb": sum(t["net_pnl_thb"] for t in trades) / len(trades) if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "starting_pot_thb": start_pot,
        "ending_pot_thb": ending_pot,
        "net_profit_thb": ending_pot - start_pot,
        "daily_summary": {
            "active_days": len(values),
            "positive_days": sum(1 for v in values if v > 0),
            "negative_days": sum(1 for v in values if v < 0),
            "positive_day_rate_pct": sum(1 for v in values if v > 0) / len(values) * 100.0 if values else 0.0,
            "avg_daily_net_thb": sum(values) / len(values) if values else 0.0,
            "best_day_net_thb": max(values) if values else 0.0,
            "worst_day_net_thb": min(values) if values else 0.0,
            "max_daily_drawdown_thb": max_dd,
            "daily_net_pnl_thb": dict(daily),
        },
        "trades_detail": trades,
    }


def simulate(selected, candles, start_pot=STARTING_POT_THB):
    trades = []
    pot = start_pot
    index = {c["time"]: i for i, c in enumerate(candles)}

    for number, record in enumerate(selected, start=1):
        entry_index = record["entry_index"]
        exit_index = entry_index + EVALUATION_HORIZON
        if exit_index >= len(candles):
            continue

        candidate = record["candidate"]
        pot_before = pot
        position_value = get_dynamic_position_value(candidate, pot_before)
        exit_price = candles[exit_index]["close"]
        gross_return = (exit_price - candidate["entry"]) / candidate["entry"]
        gross = position_value * gross_return
        cost = position_value * ROUND_TRIP_COST
        net = gross - cost
        pot += net

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": candles[exit_index]["time"].isoformat(),
            "entry_price": candidate["entry"],
            "exit_price": exit_price,
            "holding_bars": EVALUATION_HORIZON,
            "pot_before_thb": pot_before,
            "position_value_thb": position_value,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "net_pnl_thb": net,
            "pot_after_thb": pot,
        })

    return summarize_trades(trades, start_pot)


def evaluate_gate_from_candidates(candles, base_candidates, gate):
    gated = apply_gate(base_candidates, gate)
    selected, skipped = select_non_overlapping(index_candidates(candles, gated))
    result = simulate(selected, candles) if selected else None
    return {
        "base_candidates": len(base_candidates),
        "gate_pass_candidates": len(gated),
        "selected_entries": len(selected),
        "skipped_overlap": skipped,
        "result": result,
    }


def split_candidates(candidates, first_day, fold, which):
    if which == "train":
        start_day, end_day = fold["train_start_day"], fold["train_end_day"]
    else:
        start_day, end_day = fold["test_start_day"], fold["test_end_day"]

    return [
        c for c in candidates
        if start_day <= day_number(c["signal_time"], first_day) <= end_day
    ]


def select_gate(train_results):
    eligible = []
    for gate_name, data in train_results.items():
        result = data["result"]
        if result is None or result["trades"] < MIN_TRAIN_TRADES:
            continue
        if result["net_profit_thb"] <= 0:
            continue
        if result["profit_factor"] is None or result["profit_factor"] <= 1:
            continue
        if result["avg_net_per_trade_thb"] <= 0:
            continue
        eligible.append((gate_name, data))

    if not eligible:
        return {"selected_gate": None, "selection_reason": "NO_GATE_MET_TRAIN_CRITERIA"}

    eligible.sort(
        key=lambda item: (
            item[1]["result"]["net_profit_thb"],
            item[1]["result"]["profit_factor"],
            item[1]["result"]["daily_summary"]["positive_day_rate_pct"],
        ),
        reverse=True,
    )

    return {
        "selected_gate": eligible[0][0],
        "selection_reason": "BEST_ELIGIBLE_TRAIN_NET_THEN_PF_THEN_POSITIVE_DAY_RATE",
        "eligible_gates": [
            {
                "name": name,
                "net_profit_thb": data["result"]["net_profit_thb"],
                "profit_factor": data["result"]["profit_factor"],
                "trades": data["result"]["trades"],
                "positive_day_rate_pct": data["result"]["daily_summary"]["positive_day_rate_pct"],
            }
            for name, data in eligible
        ],
    }


def simulate_oos_continuous(selected_by_fold, candles):
    merged = []
    for fold_name, records in selected_by_fold:
        for record in records:
            merged.append((record["candidate"]["entry_time"], fold_name, record))

    merged.sort(key=lambda x: x[0])
    trades = []
    pot = STARTING_POT_THB
    last_exit_index = -1

    for number, (_, fold_name, record) in enumerate(merged, start=1):
        entry_index = record["entry_index"]
        exit_index = entry_index + EVALUATION_HORIZON
        if entry_index < last_exit_index:
            raise RuntimeError("OOS_OVERLAP_DETECTED_DURING_CONTINUOUS_SIMULATION")
        if exit_index >= len(candles):
            raise RuntimeError("OOS_EXIT_OUT_OF_RANGE")

        candidate = record["candidate"]
        pot_before = pot
        position_value = get_dynamic_position_value(candidate, pot_before)
        exit_price = candles[exit_index]["close"]
        gross_return = (exit_price - candidate["entry"]) / candidate["entry"]
        gross = position_value * gross_return
        cost = position_value * ROUND_TRIP_COST
        net = gross - cost
        pot += net
        last_exit_index = exit_index

        trades.append({
            "trade_number": number,
            "fold": fold_name,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": candles[exit_index]["time"].isoformat(),
            "entry_price": candidate["entry"],
            "exit_price": exit_price,
            "holding_bars": EVALUATION_HORIZON,
            "pot_before_thb": pot_before,
            "position_value_thb": position_value,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "net_pnl_thb": net,
            "pot_after_thb": pot,
        })

    return summarize_trades(trades, STARTING_POT_THB)


def main():
    print("=" * 72)
    print("MONEY_MAKER_01 ENTRY QUALITY GATE V4")
    print("WALK-FORWARD ROBUSTNESS - CONTINUOUS OOS POT")
    print("=" * 72)
    print(f"Symbol              : {SYMBOL}")
    print(f"Interval            : {INTERVAL}")
    print(f"Candles             : {CANDLE_COUNT}")
    print(f"Evaluation Horizon  : {EVALUATION_HORIZON} bars")
    print(f"Starting Pot        : {STARTING_POT_THB:.2f} THB")
    print(f"Round-trip Cost     : {ROUND_TRIP_COST * 100:.4f}%")
    print("Features             : FULL SNAPSHOT BEFORE SPLIT")
    print("Selection            : TRAIN ONLY")
    print("OOS Pot              : ONE CONTINUOUS ACCOUNT")
    print("Test Leakage         : BLOCKED")
    print("Production Changed   : NO")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(SYMBOL, INTERVAL, CANDLE_COUNT)
    if len(candles) != CANDLE_COUNT:
        raise RuntimeError(f"INVALID_RESEARCH_WINDOW: expected={CANDLE_COUNT}, actual={len(candles)}")

    # Critical V4 correction: indicators are computed once on the full
    # chronological snapshot, then candidates are split by time.
    all_candidates = calculate_base_candidates(candles)
    first_day = candles[0]["time"].date()

    print(
        f"Snapshot: {candles[0]['time']} -> {candles[-1]['time']} | "
        f"base_candidates={len(all_candidates)}"
    )

    fold_outputs = []
    selected_by_fold = []

    for fold in FOLDS:
        train_candidates = split_candidates(all_candidates, first_day, fold, "train")
        test_candidates = split_candidates(all_candidates, first_day, fold, "test")

        train_results = {
            gate["name"]: evaluate_gate_from_candidates(candles, train_candidates, gate)
            for gate in GATES
        }

        selection = select_gate(train_results)
        selected_name = selection["selected_gate"]
        selected_test_records = []

        if selected_name is not None:
            selected_gate = next(g for g in GATES if g["name"] == selected_name)
            gated_test = apply_gate(test_candidates, selected_gate)
            selected_test_records, test_skipped = select_non_overlapping(
                index_candidates(candles, gated_test)
            )
            test_preview = {
                "base_candidates": len(test_candidates),
                "gate_pass_candidates": len(gated_test),
                "selected_entries": len(selected_test_records),
                "skipped_overlap": test_skipped,
            }
        else:
            test_preview = {
                "base_candidates": len(test_candidates),
                "gate_pass_candidates": 0,
                "selected_entries": 0,
                "skipped_overlap": 0,
            }

        fold_outputs.append({
            "fold": fold,
            "train_period": (
                candles[min(i for i, c in enumerate(candles) if day_number(c["time"], first_day) == fold["train_start_day"])]["time"].isoformat(),
                candles[max(i for i, c in enumerate(candles) if day_number(c["time"], first_day) == fold["train_end_day"])]["time"].isoformat(),
            ),
            "test_period": (
                candles[min(i for i, c in enumerate(candles) if day_number(c["time"], first_day) == fold["test_start_day"])]["time"].isoformat(),
                candles[max(i for i, c in enumerate(candles) if day_number(c["time"], first_day) == fold["test_end_day"])]["time"].isoformat(),
            ),
            "train_base_candidates": len(train_candidates),
            "test_base_candidates": len(test_candidates),
            "train_gate_results": train_results,
            "selection": selection,
            "test_selected_entries_preview": test_preview,
        })
        selected_by_fold.append((fold["name"], selected_test_records))

        print(
            f"{fold['name']}: selected_gate={selected_name or 'WAIT'} | "
            f"test_entries={len(selected_test_records)}"
        )

    oos = simulate_oos_continuous(selected_by_fold, candles)
    positive_folds = 0

    # Evaluate each fold's selected test trades independently only for fold
    # diagnostics; the official OOS Pot remains the continuous result above.
    for fold_name, records in selected_by_fold:
        if not records:
            continue
        fold_result = simulate(records, candles)
        if fold_result["net_profit_thb"] > 0:
            positive_folds += 1

    decision_ok = (
        oos["trades"] >= 15
        and oos["profit_factor"] is not None
        and oos["profit_factor"] > 1
        and oos["net_profit_thb"] > 0
        and positive_folds >= 2
    )

    output = {
        "research_version": "MONEY_MAKER_01_ENTRY_QUALITY_GATE_V4",
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": CANDLE_COUNT,
            "evaluation_horizon_bars": EVALUATION_HORIZON,
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "position_size_policy": "DYNAMIC_FROM_CURRENT_POT",
            "pot_compounding": "PROFIT_AND_LOSS_FLOW_TO_NEXT_TRADE",
            "entry_overlap": "BLOCKED",
            "lookahead_blocked": True,
            "ai_used": False,
            "profit_lock_used": False,
            "giveback_used": False,
            "production_changed": False,
            "execution": "NONE",
            "walk_forward": True,
            "test_selection_leakage": False,
            "feature_context_policy": "FULL_30D_SNAPSHOT_BEFORE_SPLIT",
            "oos_pot_policy": "ONE_CONTINUOUS_ACCOUNT_ACROSS_TEST_FOLDS",
        },
        "gate_grid": list(GATES),
        "folds": fold_outputs,
        "oos_summary": {
            "folds": len(FOLDS),
            "positive_test_folds": positive_folds,
            "combined_oos": oos,
        },
        "decision": {
            "status": "ROBUSTNESS_PASS_CANDIDATE" if decision_ok else "ROBUSTNESS_FAIL_RESEARCH_ONLY",
            "production_change": False,
            "reason": (
                "Requires >=15 OOS trades, PF > 1, positive continuous OOS Pot, "
                "and at least 2 positive test folds."
            ),
        },
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 72)
    print("OOS RESULT")
    print("=" * 72)
    print(f"Trades              : {oos['trades']}")
    print(f"Win Rate            : {oos['win_rate_pct']:.2f}%")
    print(f"Profit Factor       : {oos['profit_factor']:.4f}" if oos["profit_factor"] is not None else "Profit Factor       : N/A")
    print(f"Ending Pot          : {oos['ending_pot_thb']:.2f} THB")
    print(f"Net Profit          : {oos['net_profit_thb']:+.2f} THB")
    print(f"Positive Test Folds : {positive_folds}/{len(FOLDS)}")
    print(f"Decision             : {'ROBUSTNESS_PASS_CANDIDATE' if decision_ok else 'ROBUSTNESS_FAIL_RESEARCH_ONLY'}")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
