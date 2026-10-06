"""MONEY_MAKER_01 TP3 CONTINUOUS HISTORY AUDIT V1 — research only.

Purpose:
- Test TP 3.00% with materially more historical data than the prior 1D/7D/30D snapshot.
- Keep the locked universe: SOLUSDT 30m, ETHUSDT 15m, SOLUSDT 15m.
- Use up to 100,000 closed candles per market as a historical discovery dataset.
- Preserve exact MONEY_MAKER_01 candidate logic by finding candidates on the FULL history
  before slicing any information window.
- Evaluate separate trailing 1D / 7D / 30D windows continuously across the full history.
- TP = 3.00%.
- If TP is not reached, use the VERIFIED MONEY_MAKER_01 fixed 20-bar horizon.
- Use real Risk Engine sizing and 0.14% round-trip research cost.
- Block overlapping positions.
- No AI, regime, giveback, Profit Lock, or production changes.

Important methodology:
- The 1D/7D/30D rows are rolling historical diagnostic windows, not one continuous
  compounded account across all overlapping windows.
- A trade is counted in a window only when its realized exit is at or before the
  window end. This prevents using future candles beyond the window end.
- Candidate detection is performed once on the full history, so indicator warm-up is
  not recomputed from each short window.
- This is research/discovery only; 100,000 candles are not a production approval.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
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

HORIZON_BARS = 20
TP_LEVEL = 0.03
CANDLE_LIMIT = 100_000

UNIVERSE = (
    ("SOLUSDT", "30m"),
    ("ETHUSDT", "15m"),
    ("SOLUSDT", "15m"),
)

WINDOW_DAYS = (1, 7, 30)

OUTPUT_FILE = Path(
    "money_machine_v2/research/"
    "money_maker_01_tp3_continuous_history_audit_v1.json"
)


def build_records(candles):
    index = {
        candle["time"]: i
        for i, candle in enumerate(candles)
    }

    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])
        fallback_index = index.get(candidate["planned_exit_time"])

        if entry_index is None or fallback_index is None:
            continue

        if fallback_index <= entry_index:
            continue

        rows.append(
            {
                "candidate": candidate,
                "entry_index": entry_index,
                "fallback_index": fallback_index,
            }
        )

    return sorted(
        rows,
        key=lambda row: row["candidate"]["entry_time"],
    )


def resolve_exit(record, candles):
    candidate = record["candidate"]
    entry_index = record["entry_index"]
    fallback_index = record["fallback_index"]

    entry = candidate["entry"]
    target = entry * (1.0 + TP_LEVEL)

    for i in range(entry_index, fallback_index + 1):
        if candles[i]["high"] >= target:
            return {
                "exit_index": i,
                "exit_price": target,
                "exit_type": "TP",
            }

    return {
        "exit_index": fallback_index,
        "exit_price": candles[fallback_index]["close"],
        "exit_type": "FIXED_HORIZON",
    }


def resolve_all(records, candles):
    resolved = []

    for record in records:
        outcome = resolve_exit(record, candles)
        exit_index = outcome["exit_index"]
        candidate = record["candidate"]

        resolved.append(
            {
                "candidate": candidate,
                "entry_index": record["entry_index"],
                "fallback_index": record["fallback_index"],
                "exit_index": exit_index,
                "exit_time": candles[exit_index]["time"],
                "exit_price": outcome["exit_price"],
                "exit_type": outcome["exit_type"],
            }
        )

    return resolved


def simulate_window(records, window_start, window_end):
    eligible = [
        row
        for row in records
        if window_start <= row["candidate"]["entry_time"] <= window_end
        and row["exit_time"] <= window_end
    ]

    pot = STARTING_POT_THB
    active_exit_time = None
    trades = []
    skipped_overlap = 0

    for row in eligible:
        candidate = row["candidate"]

        if (
            active_exit_time is not None
            and candidate["entry_time"] < active_exit_time
        ):
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

        position_value = (
            float(risk["position_value"])
            * REFERENCE_USDTHB
        )

        entry = candidate["entry"]
        exit_price = row["exit_price"]
        gross_return = (exit_price - entry) / entry
        gross_pnl = position_value * gross_return
        cost = position_value * ROUND_TRIP_COST
        net_pnl = gross_pnl - cost

        pot_before = pot
        pot += net_pnl

        trades.append(
            {
                "entry_time": candidate["entry_time"].isoformat(),
                "exit_time": row["exit_time"].isoformat(),
                "exit_type": row["exit_type"],
                "entry_price": entry,
                "exit_price": exit_price,
                "gross_return_pct": gross_return * 100.0,
                "position_value_thb": position_value,
                "gross_pnl_thb": gross_pnl,
                "cost_thb": cost,
                "net_pnl_thb": net_pnl,
                "pot_before_thb": pot_before,
                "pot_after_thb": pot,
            }
        )

        active_exit_time = row["exit_time"]

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    peak = STARTING_POT_THB
    max_dd = 0.0

    for trade in trades:
        peak = max(peak, trade["pot_after_thb"])
        dd = (trade["pot_after_thb"] - peak) / peak
        max_dd = min(max_dd, dd)

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "candidates_in_window": sum(
            1
            for r in records
            if window_start <= r["candidate"]["entry_time"] <= window_end
        ),
        "resolved_trades": len(trades),
        "tp_hits": sum(t["exit_type"] == "TP" for t in trades),
        "fallback_fixed_horizon": sum(
            t["exit_type"] == "FIXED_HORIZON"
            for t in trades
        ),
        "wins": len(wins),
        "losses": len(losses),
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT_THB,
        "return_pct": (pot / STARTING_POT_THB - 1.0) * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        ),
        "skipped_overlap": skipped_overlap,
    }


def summarize_windows(rows):
    summary = {}

    for days in WINDOW_DAYS:
        bucket = [
            row for row in rows
            if row["window_days"] == days
        ]

        nonempty = [
            row for row in bucket
            if row["resolved_trades"] > 0
        ]

        net_values = [
            row["net_profit_thb"]
            for row in nonempty
        ]

        positive = [
            value for value in net_values
            if value > 0
        ]

        summary[f"{days}D"] = {
            "windows_total": len(bucket),
            "windows_with_trades": len(nonempty),
            "positive_windows": len(positive),
            "positive_window_rate_pct": (
                len(positive) / len(nonempty) * 100.0
                if nonempty else 0.0
            ),
            "mean_net_profit_thb": (
                sum(net_values) / len(net_values)
                if net_values else 0.0
            ),
            "best_window_net_profit_thb": (
                max(net_values)
                if net_values else 0.0
            ),
            "worst_window_net_profit_thb": (
                min(net_values)
                if net_values else 0.0
            ),
            "total_trade_observations": sum(
                row["resolved_trades"] for row in bucket
            ),
            "total_wins": sum(row["wins"] for row in bucket),
            "total_losses": sum(row["losses"] for row in bucket),
            "tp_hits": sum(row["tp_hits"] for row in bucket),
            "fallback_fixed_horizon": sum(
                row["fallback_fixed_horizon"] for row in bucket
            ),
        }

    return summary


def run_market(symbol, interval):
    print(f"\n{'-' * 72}")
    print(f"{symbol} {interval}")
    print(f"{'-' * 72}")

    candles = fetch_closed_candles_paginated(
        symbol,
        interval,
        CANDLE_LIMIT,
    )

    if len(candles) != CANDLE_LIMIT:
        raise RuntimeError(
            f"{symbol} {interval}: expected "
            f"{CANDLE_LIMIT:,} closed candles, got {len(candles):,}"
        )

    records = build_records(candles)
    resolved = resolve_all(records, candles)

    first_day = candles[0]["time"].date()
    last_day = candles[-1]["time"].date()

    rows = []

    anchor_day = first_day + timedelta(days=1)

    while anchor_day <= last_day:
        window_end = datetime(
            anchor_day.year,
            anchor_day.month,
            anchor_day.day,
            23,
            59,
            59,
            999999,
            tzinfo=timezone.utc,
        )

        for days in WINDOW_DAYS:
            window_start = window_end - timedelta(days=days)

            stats = simulate_window(
                resolved,
                window_start,
                window_end,
            )

            stats["symbol"] = symbol
            stats["interval"] = interval
            stats["window_days"] = days
            rows.append(stats)

        anchor_day += timedelta(days=1)

    return {
        "symbol": symbol,
        "interval": interval,
        "candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "candidates_found": len(records),
        "resolved_candidates": len(resolved),
        "window_summary": summarize_windows(rows),
        "rolling_windows": rows,
    }


def main():
    print("=" * 72)
    print("MONEY_MAKER_01 TP3 CONTINUOUS HISTORY AUDIT V1")
    print("=" * 72)
    print("TP              : 3.00%")
    print("History         : up to 100,000 closed candles / market")
    print("Windows         : rolling 1D / 7D / 30D")
    print("Universe        : SOL30m / ETH15m / SOL15m")
    print("Fallback        : VERIFIED 20-BAR FIXED HORIZON")
    print("Risk            : REAL Risk Engine")
    print("Cost            : 0.14% round trip")
    print("Overlap         : BLOCKED")
    print("AI              : NOT USED")
    print("Profit Lock     : NOT USED")
    print("Production      : NOT CHANGED")
    print("=" * 72)

    results = []

    for symbol, interval in UNIVERSE:
        print(f"\nRunning {symbol} {interval}...")

        row = run_market(symbol, interval)
        results.append(row)

        for window_name, summary in row["window_summary"].items():
            print(
                f"{window_name}: "
                f"windows={summary['windows_total']} "
                f"with_trades={summary['windows_with_trades']} "
                f"positive={summary['positive_window_rate_pct']:.2f}% "
                f"mean_net={summary['mean_net_profit_thb']:+.2f}"
            )

    output = {
        "research": {
            "version": "MONEY_MAKER_01_TP3_CONTINUOUS_HISTORY_AUDIT_V1",
            "research_only": True,
            "historical_discovery_limit": CANDLE_LIMIT,
            "tp_pct": TP_LEVEL * 100.0,
            "fallback_exit_bars": HORIZON_BARS,
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100.0,
            "windows": [f"{d}D" for d in WINDOW_DAYS],
            "universe": [
                {"symbol": symbol, "interval": interval}
                for symbol, interval in UNIVERSE
            ],
            "candidate_detection_on_full_history": True,
            "window_type": "rolling_historical_diagnostic",
            "window_overlap_across_anchors": True,
            "ai_used": False,
            "regime_filter_used": False,
            "profit_lock_used": False,
            "giveback_used": False,
            "production_changed": False,
            "tax_included": False,
        },
        "results": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("SAVED")
    print("=" * 72)
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
