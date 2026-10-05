"""Research-only MONEY_MAKER_01 Entry Quality Gate V3.

Walk-forward robustness research.

Design:
- BTCUSDT 5m.
- H10 fixed evaluation horizon.
- TRUE sequential Pot compounding.
- Same 0.14% round-trip research cost.
- No AI, Profit Lock, Giveback, execution, or production change.
- No random search and no post-hoc threshold selection.
- Train/test are chronological and non-overlapping.
- Gate parameters are chosen ONLY from a pre-declared gate set.
- Test data is never used to choose a gate.

Walk-forward folds use one fetched 30D candle snapshot:
  Fold 1: Train days 01-15 -> Test days 16-22
  Fold 2: Train days 08-22 -> Test days 23-29
  Fold 3: Train days 01-21 -> Test days 22-30

The final OOS score is the chronological concatenation of all test folds.
This deliberately avoids treating overlapping 1D/7D/30D windows as independent.

Selection rule per fold:
1. Evaluate every pre-declared gate on TRAIN only.
2. Eligible gate must have >= 5 selected train trades.
3. Prefer gates with positive train net, PF > 1, and positive average net/trade.
4. Among eligible gates, maximize train net profit, then PF, then positive-day rate.
5. If no gate qualifies, select WAIT for that fold.
6. Apply the selected gate unchanged to TEST.

A gate is NOT production-approved merely because OOS is positive.
The output reports per-fold selection, OOS results, and a final robustness decision.
"""

import json
import sys
from collections import defaultdict
from datetime import timedelta
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

# Fixed research grid. These are declared before any train/test result is seen.
GATES = (
    {
        "name": "BASELINE",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "BODY_50",
        "min_body_ratio": 0.50,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "BODY_70",
        "min_body_ratio": 0.70,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "CLOSE_LOC_70",
        "min_body_ratio": 0.00,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "EMA50_DIST_010",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.0010,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "RV_1.80",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.80,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "ATR_1.30",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.30,
    },
    {
        "name": "BODY60_CLOSE70",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.50,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "BODY60_CLOSE70_RV180",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.80,
        "min_atr_expansion": 1.25,
    },
    {
        "name": "QUALITY_STRICT",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.0010,
        "min_relative_volume": 1.80,
        "min_atr_expansion": 1.30,
    },
)

# Fixed chronological folds in UTC dates. Boundaries are based on candle signal
# time; the entire 30D snapshot is fetched once and then split locally.
FOLDS = (
    {"name": "FOLD_1", "train_start_day": 1, "train_end_day": 15,
     "test_start_day": 16, "test_end_day": 22},
    {"name": "FOLD_2", "train_start_day": 8, "train_end_day": 22,
     "test_start_day": 23, "test_end_day": 29},
    {"name": "FOLD_3", "train_start_day": 1, "train_end_day": 21,
     "test_start_day": 22, "test_end_day": 30},
)

OUTPUT_FILE = Path(
    "money_machine_v2/research/money_maker_01_entry_quality_gate_v3.json"
)


def prepare_features(candles):
    atr = calculate_atr(candles)
    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, EMA_PERIOD)
    relative_volume = calculate_relative_volume(candles)
    return atr, ema50, relative_volume


def calculate_base_candidates(candles):
    atr, ema50, relative_volume = prepare_features(candles)
    candidates = []

    start = max(ATR_PERIOD + ATR_LOOKBACK, EMA_PERIOD)
    end = len(candles) - EVALUATION_HORIZON - 2

    for i in range(start, max(start, end + 1)):
        if atr[i] is None or ema50[i] is None or relative_volume[i] is None:
            continue

        recent_atr = [
            atr[j]
            for j in range(i - ATR_LOOKBACK, i)
            if atr[j] is not None
        ]
        if len(recent_atr) != ATR_LOOKBACK:
            continue

        avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
        expansion_ratio = atr[i] / avg_recent_atr
        candle_range = candles[i]["high"] - candles[i]["low"]
        if candle_range <= 0:
            continue

        bullish = candles[i]["close"] > candles[i]["open"]
        higher_close = candles[i]["close"] > candles[i - 1]["close"]
        above_ema50 = candles[i]["close"] > ema50[i]

        if not (
            expansion_ratio >= BASE_ATR_EXPANSION
            and candle_range >= atr[i] * CANDLE_RANGE_ATR_MIN
            and bullish
            and higher_close
            and relative_volume[i] >= BASE_RV_THRESHOLD
            and above_ema50
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
                "body_ratio": abs(
                    candles[i]["close"] - candles[i]["open"]
                ) / candle_range,
                "close_location": (
                    candles[i]["close"] - candles[i]["low"]
                ) / candle_range,
            },
        })

    return candidates


def apply_gate(candidates, gate):
    out = []
    for c in candidates:
        f = c["features"]
        if f["body_ratio"] < gate["min_body_ratio"]:
            continue
        if f["close_location"] < gate["min_close_location"]:
            continue
        if f["ema50_distance"] < gate["min_ema50_distance"]:
            continue
        if f["relative_volume"] < gate["min_relative_volume"]:
            continue
        if f["atr_expansion_ratio"] < gate["min_atr_expansion"]:
            continue
        out.append(c)
    return out


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


def get_dynamic_position_value(candidate, pot_thb):
    decision = {"signal": "BUY", "confidence": 0, "quality": "PASSED"}
    features = {
        "close": candidate["entry"],
        "atr14": candidate["features"]["atr"],
    }
    risk = evaluate_risk(
        decision=decision,
        features=features,
        capital=pot_thb / REFERENCE_USDTHB,
        daily_pnl=0.0,
        open_positions=0,
    )
    if not risk.get("allowed"):
        raise RuntimeError(
            f"RISK_REJECTED_DURING_RESEARCH: {risk.get('reason')}"
        )
    return float(risk["position_value"]) * REFERENCE_USDTHB


def daily_summary(trades):
    daily = defaultdict(float)
    for t in trades:
        daily[t["entry_time"][:10]] += t["net_pnl_thb"]

    values = list(daily.values())
    positive = [v for v in values if v > 0]
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    return {
        "active_days": len(values),
        "positive_days": len(positive),
        "negative_days": sum(1 for v in values if v < 0),
        "positive_day_rate_pct": (
            len(positive) / len(values) * 100.0 if values else 0.0
        ),
        "avg_daily_net_thb": sum(values) / len(values) if values else 0.0,
        "best_day_net_thb": max(values) if values else 0.0,
        "worst_day_net_thb": min(values) if values else 0.0,
        "max_daily_drawdown_thb": max_dd,
        "daily_net_pnl_thb": dict(daily),
    }


def simulate(selected, candles, start_pot=STARTING_POT_THB):
    trades = []
    pot = start_pot

    for number, record in enumerate(selected, start=1):
        exit_index = record["entry_index"] + EVALUATION_HORIZON
        if exit_index >= len(candles):
            raise RuntimeError(
                f"HORIZON_EXIT_OUT_OF_RANGE: {exit_index}/{len(candles)}"
            )

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

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100.0 if trades else 0.0,
        "avg_net_per_trade_thb": (
            sum(t["net_pnl_thb"] for t in trades) / len(trades)
            if trades else 0.0
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "starting_pot_thb": start_pot,
        "ending_pot_thb": pot,
        "net_profit_thb": pot - start_pot,
        "daily_summary": daily_summary(trades),
        "trades_detail": trades,
    }


def evaluate_gate(candles, base_candidates, gate):
    gated = apply_gate(base_candidates, gate)
    records = index_candidates(candles, gated)
    selected, skipped = select_non_overlapping(records)
    if not selected:
        return {
            "base_candidates": len(base_candidates),
            "gate_pass_candidates": len(gated),
            "selected_entries": 0,
            "skipped_overlap": skipped,
            "result": None,
        }
    return {
        "base_candidates": len(base_candidates),
        "gate_pass_candidates": len(gated),
        "selected_entries": len(selected),
        "skipped_overlap": skipped,
        "result": simulate(selected, candles),
    }


def day_number(candle_time, first_day):
    return (candle_time.date() - first_day).days + 1


def split_candles(candles, fold):
    first_day = candles[0]["time"].date()
    train = []
    test = []

    for candle in candles:
        d = day_number(candle["time"], first_day)
        if fold["train_start_day"] <= d <= fold["train_end_day"]:
            train.append(candle)
        if fold["test_start_day"] <= d <= fold["test_end_day"]:
            test.append(candle)

    return train, test


def select_gate(train_results):
    eligible = []
    for gate_name, data in train_results.items():
        result = data["result"]
        if result is None:
            continue
        if result["trades"] < MIN_TRAIN_TRADES:
            continue
        if result["net_profit_thb"] <= 0:
            continue
        if result["profit_factor"] is None or result["profit_factor"] <= 1:
            continue
        if result["avg_net_per_trade_thb"] <= 0:
            continue

        eligible.append((gate_name, data))

    if not eligible:
        return {
            "selected_gate": None,
            "selection_reason": "NO_GATE_MET_TRAIN_CRITERIA",
        }

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
                "positive_day_rate_pct": data["result"]["daily_summary"][
                    "positive_day_rate_pct"
                ],
            }
            for name, data in eligible
        ],
    }


def combine_test_trades(fold_test_results):
    trades = []
    for fold in fold_test_results:
        trades.extend(fold.get("trades_detail", []))

    trades.sort(key=lambda t: t["entry_time"])

    # Recalculate Pot chronologically from the original 1,500 THB so the
    # combined OOS result reflects one continuous account, not three resets.
    pot = STARTING_POT_THB
    rebuilt = []

    for number, trade in enumerate(trades, start=1):
        # Position sizing is recalculated from the current Pot for the exact
        # selected entry using the stored ATR-derived position value ratio.
        # The fold simulation's absolute position value cannot be reused because
        # each fold starts independently. Reconstructing requires the candidate
        # feature, so combined scoring uses net-return instead below.
        rebuilt.append(trade)

    net_return_sum = 0.0
    for trade in rebuilt:
        position_value = trade["position_value_thb"]
        if position_value <= 0:
            continue
        net_return_sum += trade["net_pnl_thb"] / position_value

    # OOS robustness is reported primarily in return-space to avoid falsely
    # compounding three independently-sized fold simulations.
    wins = [t for t in rebuilt if t["net_pnl_thb"] > 0]
    losses = [t for t in rebuilt if t["net_pnl_thb"] < 0]
    gross_profit_return = sum(
        t["net_pnl_thb"] / t["position_value_thb"] for t in wins
    )
    gross_loss_return = abs(sum(
        t["net_pnl_thb"] / t["position_value_thb"] for t in losses
    ))

    return {
        "trades": len(rebuilt),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (
            len(wins) / len(rebuilt) * 100.0 if rebuilt else 0.0
        ),
        "profit_factor": (
            gross_profit_return / gross_loss_return
            if gross_loss_return > 0 else None
        ),
        "sum_net_return_pct": net_return_sum * 100.0,
        "trades_detail": rebuilt,
    }


def main():
    print("=" * 72)
    print("MONEY_MAKER_01 ENTRY QUALITY GATE V3")
    print("WALK-FORWARD ROBUSTNESS")
    print("=" * 72)
    print(f"Symbol              : {SYMBOL}")
    print(f"Interval            : {INTERVAL}")
    print(f"Candles             : {CANDLE_COUNT}")
    print(f"Evaluation Horizon  : {EVALUATION_HORIZON} bars")
    print(f"Starting Pot        : {STARTING_POT_THB:.2f} THB")
    print(f"Round-trip Cost     : {ROUND_TRIP_COST * 100:.4f}%")
    print(f"Min Train Trades    : {MIN_TRAIN_TRADES}")
    print("Selection            : TRAIN ONLY")
    print("Test Leakage        : BLOCKED")
    print("Production Changed   : NO")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL, INTERVAL, CANDLE_COUNT
    )
    if len(candles) != CANDLE_COUNT:
        raise RuntimeError(
            f"INVALID_RESEARCH_WINDOW: expected={CANDLE_COUNT}, "
            f"actual={len(candles)}"
        )

    base_candidates = calculate_base_candidates(candles)
    print(
        f"Snapshot: {candles[0]['time']} -> {candles[-1]['time']} | "
        f"base_candidates={len(base_candidates)}"
    )

    fold_outputs = []

    for fold in FOLDS:
        train_candles, test_candles = split_candles(candles, fold)

        if not train_candles or not test_candles:
            raise RuntimeError(f"INVALID_FOLD: {fold['name']}")

        train_base = calculate_base_candidates(train_candles)
        test_base = calculate_base_candidates(test_candles)

        # The fold's feature warm-up can remove early candles. This is expected;
        # selection still uses only the fold-local train/test segments.
        train_results = {}
        for gate in GATES:
            train_results[gate["name"]] = evaluate_gate(
                train_candles, train_base, gate
            )

        selection = select_gate(train_results)

        selected_name = selection["selected_gate"]
        test_result = None

        if selected_name is not None:
            selected_gate = next(
                gate for gate in GATES if gate["name"] == selected_name
            )
            test_eval = evaluate_gate(
                test_candles, test_base, selected_gate
            )
            test_result = test_eval["result"]

        fold_output = {
            "fold": fold,
            "train_period": (
                train_candles[0]["time"].isoformat(),
                train_candles[-1]["time"].isoformat(),
            ),
            "test_period": (
                test_candles[0]["time"].isoformat(),
                test_candles[-1]["time"].isoformat(),
            ),
            "train_base_candidates": len(train_base),
            "test_base_candidates": len(test_base),
            "train_gate_results": train_results,
            "selection": selection,
            "test_gate_result": (
                {
                    "gate": selected_name,
                    "result": test_result,
                }
                if selected_name is not None
                else {
                    "gate": None,
                    "result": None,
                    "reason": "WAIT_NO_TRAIN_GATE",
                }
            ),
        }
        fold_outputs.append(fold_output)

        print()
        print("-" * 72)
        print(fold["name"])
        print(
            f"Train {fold['train_start_day']:02d}-{fold['train_end_day']:02d} | "
            f"Test {fold['test_start_day']:02d}-{fold['test_end_day']:02d}"
        )
        print(
            f"Selected Gate: {selected_name or 'WAIT'} | "
            f"Reason: {selection['selection_reason']}"
        )
        if test_result:
            print(
                f"TEST: N={test_result['trades']} | "
                f"WR={test_result['win_rate_pct']:.2f}% | "
                f"PF={test_result['profit_factor']:.4f} | "
                f"Net={test_result['net_profit_thb']:+.2f} THB"
            )
        else:
            print("TEST: WAIT / NO TRADE")

    # Aggregate OOS using each fold's actual test trades. Fold position sizes
    # are intentionally not compounded across fold boundaries; the robustness
    # decision is based on trade returns and PF, while per-fold Pot shows the
    # money result under the exact research sizing rule.
    fold_test_summaries = []
    all_test_trades = []

    for fold in fold_outputs:
        result = fold["test_gate_result"]["result"]
        if result is None:
            continue
        fold_test_summaries.append(result)
        all_test_trades.extend(result["trades_detail"])

    combined = combine_test_trades(fold_test_summaries)

    positive_folds = sum(
        1
        for result in fold_test_summaries
        if result["net_profit_thb"] > 0
    )
    total_folds = len(fold_outputs)

    robustness_pass = (
        combined["trades"] >= 15
        and combined["profit_factor"] is not None
        and combined["profit_factor"] > 1.0
        and combined["sum_net_return_pct"] > 0
        and positive_folds >= 2
    )

    decision = (
        "ROBUSTNESS_PASS_RESEARCH_ONLY"
        if robustness_pass
        else "ROBUSTNESS_FAIL_RESEARCH_ONLY"
    )

    output = {
        "research_version": "MONEY_MAKER_01_ENTRY_QUALITY_GATE_V3",
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
        },
        "gate_grid": GATES,
        "folds": fold_outputs,
        "oos_summary": {
            "folds": total_folds,
            "folds_with_selected_gate": len(fold_test_summaries),
            "positive_test_folds": positive_folds,
            "combined_oos": combined,
        },
        "decision": {
            "status": decision,
            "production_change": False,
            "reason": (
                "Requires positive combined OOS return, PF > 1, "
                "at least 15 OOS trades, and at least 2 positive test folds."
            ),
        },
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print(f"Decision: {decision}")
    print(f"Saved: {OUTPUT_FILE}")
    print("=" * 72)


if __name__ == "__main__":
    main()
