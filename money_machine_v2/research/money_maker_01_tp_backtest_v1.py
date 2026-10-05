"""MONEY_MAKER_01 TP BACKTEST V1 — research only.

Purpose:
- Test real realized TP exits, not TP reach/MFE only.
- Locked entry logic: MONEY_MAKER_01 via safe research adapter.
- Locked universe: SOLUSDT 30m, ETHUSDT 15m, SOLUSDT 15m.
- Separate information windows: 1D, 7D, 30D.
- TP levels are research diagnostics only.
- If TP is not reached, fallback is the VERIFIED MONEY_MAKER_01 fixed horizon:
  20 bars from entry.
- Dynamic Pot sizing uses the existing Risk Engine at each selected entry.
- Cost: existing fee + slippage assumption = 0.14% round trip.
- No AI, no regime filter, no Profit Lock, no giveback, no production changes.
"""

import json
import sys
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

TP_LEVELS = (
    0.005,
    0.0075,
    0.010,
    0.015,
    0.020,
    0.030,
)

UNIVERSE = (
    ("SOLUSDT", "30m"),
    ("ETHUSDT", "15m"),
    ("SOLUSDT", "15m"),
)

WINDOW_DAYS = (1, 7, 30)

INTERVAL_MINUTES = {
    "15m": 15,
    "30m": 30,
}

OUTPUT_FILE = Path(
    "money_machine_v2/research/"
    "money_maker_01_tp_backtest_v1.json"
)


def candles_for_window(interval, days):
    minutes = INTERVAL_MINUTES[interval]
    return int(days * 24 * 60 / minutes)


def gross_return(entry, exit_price):
    return (exit_price - entry) / entry


def build_records(candles):
    index = {
        candle["time"]: i
        for i, candle in enumerate(candles)
    }

    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])
        fallback_index = index.get(
            candidate["planned_exit_time"]
        )

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


def evaluate_tp_exit(
    record,
    candles,
    tp_level,
):
    candidate = record["candidate"]
    entry_index = record["entry_index"]
    fallback_index = record["fallback_index"]

    entry = candidate["entry"]
    target = entry * (1.0 + tp_level)

    for i in range(
        entry_index,
        fallback_index + 1,
    ):
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


def simulate(records, candles, tp_level):
    pot = STARTING_POT_THB
    active_exit_time = None

    trades = []
    skipped_overlap = 0
    risk_rejected = 0

    for record in records:
        candidate = record["candidate"]

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
            risk_rejected += 1
            continue

        position_value = (
            float(risk["position_value"])
            * REFERENCE_USDTHB
        )

        outcome = evaluate_tp_exit(
            record,
            candles,
            tp_level,
        )

        entry = candidate["entry"]
        exit_price = outcome["exit_price"]

        gr = gross_return(
            entry,
            exit_price,
        )

        gross_pnl = position_value * gr
        cost = position_value * ROUND_TRIP_COST
        net_pnl = gross_pnl - cost

        pot_before = pot
        pot += net_pnl

        exit_index = outcome["exit_index"]
        exit_time = candles[exit_index]["time"]

        trades.append(
            {
                "entry_time": (
                    candidate["entry_time"].isoformat()
                ),
                "exit_time": exit_time.isoformat(),
                "exit_type": outcome["exit_type"],
                "entry_price": entry,
                "exit_price": exit_price,
                "holding_bars": (
                    exit_index
                    - record["entry_index"]
                ),
                "position_value_thb": position_value,
                "gross_return_pct": gr * 100,
                "gross_pnl_thb": gross_pnl,
                "cost_thb": cost,
                "net_pnl_thb": net_pnl,
                "pot_before_thb": pot_before,
                "pot_after_thb": pot,
            }
        )

        active_exit_time = exit_time

    wins = [
        t["net_pnl_thb"]
        for t in trades
        if t["net_pnl_thb"] > 0
    ]

    losses = [
        t["net_pnl_thb"]
        for t in trades
        if t["net_pnl_thb"] < 0
    ]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    peak_pot = STARTING_POT_THB
    max_dd = 0.0

    for trade in trades:
        peak_pot = max(
            peak_pot,
            trade["pot_after_thb"],
        )
        dd = (
            trade["pot_after_thb"] - peak_pot
        ) / peak_pot
        max_dd = min(max_dd, dd)

    realized_returns = [
        t["gross_return_pct"]
        for t in trades
    ]

    return {
        "tp_level_pct": tp_level * 100,
        "trades": len(trades),
        "tp_hits": sum(
            t["exit_type"] == "TP"
            for t in trades
        ),
        "fallback_fixed_horizon": sum(
            t["exit_type"] == "FIXED_HORIZON"
            for t in trades
        ),
        "tp_hit_rate_pct": (
            sum(t["exit_type"] == "TP" for t in trades)
            / len(trades)
            * 100
            if trades
            else 0.0
        ),
        "wins": len(wins),
        "losses": len(losses),
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT_THB,
        "return_pct": (
            (pot / STARTING_POT_THB) - 1.0
        ) * 100,
        "max_drawdown_pct": max_dd * 100,
        "biggest_winner_thb": max(
            wins,
            default=0.0,
        ),
        "average_winner_thb": (
            sum(wins) / len(wins)
            if wins
            else 0.0
        ),
        "average_loser_thb": (
            sum(losses) / len(losses)
            if losses
            else 0.0
        ),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        ),
        "realized_trade_ge_1pct": sum(
            r >= 1.0
            for r in realized_returns
        ),
        "realized_trade_ge_1_5pct": sum(
            r >= 1.5
            for r in realized_returns
        ),
        "realized_trade_ge_2pct": sum(
            r >= 2.0
            for r in realized_returns
        ),
        "skipped_overlap": skipped_overlap,
        "risk_rejected": risk_rejected,
        "trades_detail": trades,
    }


def run_market_window(symbol, interval, days):
    candle_limit = candles_for_window(
        interval,
        days,
    )

    candles = fetch_closed_candles_paginated(
        symbol,
        interval,
        candle_limit,
    )

    if len(candles) != candle_limit:
        raise RuntimeError(
            f"{symbol} {interval} {days}D: "
            f"expected {candle_limit} closed candles, "
            f"got {len(candles)}"
        )

    records = build_records(candles)

    return {
        "symbol": symbol,
        "interval": interval,
        "window": f"{days}D",
        "candles": len(candles),
        "candidates": len(records),
        "tp_results": [
            simulate(
                records,
                candles,
                tp_level,
            )
            for tp_level in TP_LEVELS
        ],
    }


def main():
    print("=" * 72)
    print("MONEY_MAKER_01 TP BACKTEST V1")
    print("=" * 72)
    print("Entry          : LOCKED MONEY_MAKER_01")
    print("Fallback       : VERIFIED 20-BAR FIXED HORIZON")
    print("Cost           : 0.14% round trip")
    print("AI             : NOT USED")
    print("Profit Lock    : NOT USED")
    print("Windows        : 1D / 7D / 30D")
    print("Universe       : SOL30m / ETH15m / SOL15m")
    print("=" * 72)

    results = []

    for symbol, interval in UNIVERSE:
        for days in WINDOW_DAYS:
            print(
                f"\nRunning {symbol} {interval} {days}D..."
            )

            row = run_market_window(
                symbol,
                interval,
                days,
            )

            results.append(row)

            print(
                f"Candidates={row['candidates']} "
                f"Candles={row['candles']}"
            )

            for tp in row["tp_results"]:
                print(
                    f"TP={tp['tp_level_pct']:>4.2f}% "
                    f"N={tp['trades']:>2} "
                    f"Hit={tp['tp_hits']:>2} "
                    f"Net={tp['net_profit_thb']:+8.2f} "
                    f"PF={tp['profit_factor']}"
                )

    output = {
        "research": {
            "version": "MONEY_MAKER_01_TP_BACKTEST_V1",
            "research_only": True,
            "entry_locked": True,
            "fallback_exit": {
                "type": "FIXED_HORIZON",
                "bars": HORIZON_BARS,
                "source": "MONEY_MAKER_01",
            },
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": (
                ROUND_TRIP_COST * 100
            ),
            "tp_levels_pct": [
                level * 100
                for level in TP_LEVELS
            ],
            "windows": [
                f"{days}D"
                for days in WINDOW_DAYS
            ],
            "universe": [
                {
                    "symbol": symbol,
                    "interval": interval,
                }
                for symbol, interval in UNIVERSE
            ],
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
