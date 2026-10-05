"""Research-only MONEY_MAKER_01 Entry Quality Gate V2.

Purpose:
- Research whether a stricter entry-quality gate can improve the probability
  of profitable MONEY_MAKER_01 trades and grow Pot after costs.
- Evaluation horizon is fixed at 10 bars, based on Fixed Horizon Evolution V4.
- Uses true sequential Pot compounding.
- Reuses ONE candle snapshot per window across every variant for fair comparison.

Locked MONEY_MAKER_01 base conditions:
- ATR expansion >= 1.25x
- candle range >= ATR
- bullish candle
- higher close
- relative volume >= 1.50
- close > EMA50
- entry at next candle open

V2 adds only pre-declared quality gates based on information available at
the signal candle:
- candle body/range strength
- close location inside the signal candle
- minimum distance above EMA50
- relative-volume strength
- ATR expansion strength

No AI, Profit Lock, Giveback, execution, production change, or hindsight.
This file is research only.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOWS
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
WINDOWS = {**WINDOWS, "1D": 288}
WINDOW_NAMES = ("1D", "7D", "30D")

EMA_PERIOD = 50
BASE_ATR_EXPANSION = 1.25
BASE_RV_THRESHOLD = 1.50
CANDLE_RANGE_ATR_MIN = 1.0

# Pre-declared research grid.
# The baseline is included unchanged. Other variants add quality gates only.
VARIANTS = (
    {
        "name": "BASELINE",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY_50",
        "min_body_ratio": 0.50,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY_60",
        "min_body_ratio": 0.60,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY_70",
        "min_body_ratio": 0.70,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "CLOSE_LOC_70",
        "min_body_ratio": 0.00,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "EMA50_DIST_010",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.0010,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "EMA50_DIST_020",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.0020,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "RV_1.80",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.80,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "ATR_1.30",
        "min_body_ratio": 0.00,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": 1.30,
    },
    {
        "name": "BODY60_CLOSE70",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY60_EMA010",
        "min_body_ratio": 0.60,
        "min_close_location": 0.00,
        "min_ema50_distance": 0.0010,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY60_CLOSE70_EMA010",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.0010,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY60_CLOSE70_RV180",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": 1.80,
        "min_atr_expansion": BASE_ATR_EXPANSION,
    },
    {
        "name": "BODY60_CLOSE70_ATR130",
        "min_body_ratio": 0.60,
        "min_close_location": 0.70,
        "min_ema50_distance": 0.00,
        "min_relative_volume": BASE_RV_THRESHOLD,
        "min_atr_expansion": 1.30,
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

OUTPUT_FILE = Path(
    "money_machine_v2/research/money_maker_01_entry_quality_gate_v2.json"
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

    if end < start:
        return candidates

    for i in range(start, end + 1):
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

        body_ratio = (
            abs(candles[i]["close"] - candles[i]["open"]) / candle_range
        )
        close_location = (
            candles[i]["close"] - candles[i]["low"]
        ) / candle_range
        ema50_distance = (candles[i]["close"] / ema50[i]) - 1.0

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
                "ema50_distance": ema50_distance,
                "body_ratio": body_ratio,
                "close_location": close_location,
                "bullish": bullish,
                "higher_close": higher_close,
            },
        })

    return candidates


def apply_quality_gate(candidates, variant):
    passed = []

    for candidate in candidates:
        f = candidate["features"]

        if f["body_ratio"] < variant["min_body_ratio"]:
            continue
        if f["close_location"] < variant["min_close_location"]:
            continue
        if f["ema50_distance"] < variant["min_ema50_distance"]:
            continue
        if f["relative_volume"] < variant["min_relative_volume"]:
            continue
        if f["atr_expansion_ratio"] < variant["min_atr_expansion"]:
            continue

        passed.append(candidate)

    return passed


def index_candidates(candles, candidates):
    index = {c["time"]: i for i, c in enumerate(candles)}
    rows = []

    for candidate in candidates:
        entry_index = index.get(candidate["entry_time"])
        if entry_index is None:
            continue
        rows.append({
            "candidate": candidate,
            "entry_index": entry_index,
        })

    return sorted(rows, key=lambda row: row["candidate"]["entry_time"])


def select_non_overlapping(records):
    selected = []
    active_exit = None
    skipped_overlap = 0

    for record in records:
        entry_index = record["entry_index"]

        if active_exit is not None and entry_index < active_exit:
            skipped_overlap += 1
            continue

        selected.append(record)
        active_exit = entry_index + EVALUATION_HORIZON

    return selected, skipped_overlap


def get_dynamic_position_value(candidate, pot_thb):
    if pot_thb <= 0:
        raise RuntimeError(f"NON_POSITIVE_POT_BEFORE_TRADE: pot={pot_thb}")

    decision = {
        "signal": "BUY",
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
        capital=pot_thb / REFERENCE_USDTHB,
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
    gross_return = (
        exit_price - candidate["entry"]
    ) / candidate["entry"]
    gross_pnl = position_value * gross_return
    cost = position_value * ROUND_TRIP_COST
    return gross_pnl, cost, gross_pnl - cost


def daily_summary(trades):
    daily = {}
    for trade in trades:
        day = trade["entry_time"][:10]
        daily[day] = daily.get(day, 0.0) + trade["net_pnl_thb"]

    values = list(daily.values())
    positive = [v for v in values if v > 0]

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
        "negative_days": sum(1 for v in values if v < 0),
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


def simulate(selected, candles):
    trades = []
    pot = STARTING_POT_THB

    for number, record in enumerate(selected, start=1):
        candidate = record["candidate"]
        entry_index = record["entry_index"]
        exit_index = entry_index + EVALUATION_HORIZON

        if exit_index >= len(candles):
            raise RuntimeError(
                f"HORIZON_EXIT_OUT_OF_RANGE: entry_index={entry_index}, "
                f"exit_index={exit_index}, candles={len(candles)}"
            )

        pot_before = pot
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
                f"NON_POSITIVE_POT_AFTER_TRADE: trade={number}, pot={pot}"
            )

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": exit_candle["time"].isoformat(),
            "holding_bars": EVALUATION_HORIZON,
            "entry_price": candidate["entry"],
            "exit_price": exit_candle["close"],
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
        "win_rate_pct": (
            len(wins) / len(trades) * 100.0 if trades else 0.0
        ),
        "profit_factor": (
            gross_profit / gross_loss if gross_loss > 0 else None
        ),
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT_THB,
        "return_pct": (pot / STARTING_POT_THB - 1.0) * 100.0,
        "daily_summary": daily_summary(trades),
        "trades_detail": trades,
    }


def run_window(candles, base_candidates, variant):
    gated = apply_quality_gate(base_candidates, variant)
    records = index_candidates(candles, gated)
    selected, skipped_overlap = select_non_overlapping(records)

    if not selected:
        return {
            "candles": len(candles),
            "first_candle": candles[0]["time"].isoformat(),
            "last_candle": candles[-1]["time"].isoformat(),
            "base_candidates": len(base_candidates),
            "gate_pass_candidates": len(gated),
            "selected_entries": 0,
            "skipped_overlap": skipped_overlap,
            "result": None,
        }

    result = simulate(selected, candles)

    return {
        "candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "base_candidates": len(base_candidates),
        "gate_pass_candidates": len(gated),
        "selected_entries": len(selected),
        "skipped_overlap": skipped_overlap,
        "result": result,
    }


def main():
    print("=" * 72)
    print("MONEY_MAKER_01 ENTRY QUALITY GATE V2")
    print("=" * 72)
    print(f"Symbol              : {SYMBOL}")
    print(f"Interval            : {INTERVAL}")
    print(f"Windows             : {list(WINDOW_NAMES)}")
    print(f"Evaluation Horizon  : {EVALUATION_HORIZON} bars")
    print(f"Starting Pot        : {STARTING_POT_THB:.2f} THB")
    print(f"Round-trip Cost     : {ROUND_TRIP_COST * 100:.4f}%")
    print("Position Size       : DYNAMIC FROM CURRENT POT")
    print("Compounding         : PROFIT + LOSS -> NEXT POT")
    print("Entry Overlap       : BLOCKED")
    print("Lookahead           : BLOCKED")
    print("AI                  : NOT USED")
    print("Profit Lock         : NOT USED")
    print("Giveback            : NOT USED")
    print("Production Changed  : NO")
    print("=" * 72)

    # IMPORTANT: fetch each window exactly once, then reuse that snapshot for
    # every variant. This removes the V1 fairness issue caused by repeated
    # live fetches at different moments.
    candle_snapshots = {}
    base_candidates = {}

    for window_name in WINDOW_NAMES:
        candle_count = WINDOWS[window_name]
        candles = fetch_closed_candles_paginated(
            SYMBOL, INTERVAL, candle_count
        )

        if len(candles) != candle_count:
            raise RuntimeError(
                f"INVALID_RESEARCH_WINDOW: {window_name}: "
                f"expected={candle_count}, actual={len(candles)}"
            )

        candle_snapshots[window_name] = candles
        base_candidates[window_name] = calculate_base_candidates(candles)

        print(
            f"SNAPSHOT {window_name}: candles={len(candles)} | "
            f"base_candidates={len(base_candidates[window_name])}"
        )

    results = {}

    for variant in VARIANTS:
        print()
        print("-" * 72)
        print(f"VARIANT: {variant['name']}")

        variant_windows = {}

        for window_name in WINDOW_NAMES:
            result = run_window(
                candle_snapshots[window_name],
                base_candidates[window_name],
                variant,
            )
            variant_windows[window_name] = result

            summary = result["result"]
            if summary is None:
                print(
                    f"{window_name}: "
                    f"gate_pass={result['gate_pass_candidates']} "
                    f"selected=0"
                )
                continue

            d = summary["daily_summary"]
            print(
                f"{window_name}: "
                f"N={summary['trades']} | "
                f"WR={summary['win_rate_pct']:.2f}% | "
                f"PF={summary['profit_factor']:.4f} | "
                f"Net={summary['net_profit_thb']:+.2f} THB | "
                f"Pot={summary['ending_pot_thb']:.2f} | "
                f"PosDays={d['positive_day_rate_pct']:.2f}%"
            )

        results[variant["name"]] = {
            "parameters": variant,
            "windows": variant_windows,
        }

    output = {
        "research_version": "MONEY_MAKER_01_ENTRY_QUALITY_GATE_V2",
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "windows": {name: WINDOWS[name] for name in WINDOW_NAMES},
            "starting_pot_thb": STARTING_POT_THB,
            "evaluation_horizon_bars": EVALUATION_HORIZON,
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
            "same_candle_snapshot_across_variants": True,
        },
        "base_conditions": {
            "atr_expansion": BASE_ATR_EXPANSION,
            "rv_threshold": BASE_RV_THRESHOLD,
            "ema_filter": "CLOSE_GT_EMA50",
            "candle_range_filter": "RANGE_GTE_ATR",
            "bullish": True,
            "higher_close": True,
        },
        "quality_features": {
            "body_ratio": "ABS(CLOSE-OPEN)/RANGE",
            "close_location": "(CLOSE-LOW)/RANGE",
            "ema50_distance": "CLOSE/EMA50-1",
        },
        "variants": results,
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
