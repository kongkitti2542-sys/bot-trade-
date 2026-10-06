"""Profit Sweep Exit Comparison V1 — research only.

Compare:
A) VERIFIED fixed 20-bar exit
B) TP 3.00%, otherwise verified fixed 20-bar exit

Capital model:
- Starting trading pot: 1,500 THB.
- Each trade sizes from the CURRENT trading pot.
- Net positive P/L is swept entirely to Reserve.
- Therefore a winning trade restores trading pot to its pre-trade value.
- A losing trade reduces trading pot.
- Reserve is never used to replenish trading pot.
- Round-trip cost: 0.14%.
- Real Risk Engine sizing.
- Overlap blocked.
- Locked universe: SOLUSDT 30m, ETHUSDT 15m, SOLUSDT 15m.
- Up to 100,000 closed candles per market.
- Rolling 1D/7D/30D diagnostic windows.
- Candidate detection on full history.
- No AI, regime, giveback, Profit Lock, or production changes.

This research is designed to answer which exit creates more realizable
profit swept into Reserve under the new capital-management rule.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

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
    "profit_sweep_exit_comparison_v1.json"
)


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])
        fallback_index = index.get(candidate["planned_exit_time"])
        if entry_index is None or fallback_index is None:
            continue
        if fallback_index <= entry_index:
            continue
        rows.append({
            "candidate": candidate,
            "entry_index": entry_index,
            "fallback_index": fallback_index,
        })

    return sorted(rows, key=lambda r: r["candidate"]["entry_time"])


def resolve_exit(record, candles, mode):
    c = record["candidate"]
    entry_index = record["entry_index"]
    fallback_index = record["fallback_index"]

    if mode == "FIXED_20":
        return {
            "exit_index": fallback_index,
            "exit_price": candles[fallback_index]["close"],
            "exit_type": "FIXED_HORIZON",
        }

    target = c["entry"] * (1.0 + TP_LEVEL)
    for i in range(entry_index, fallback_index + 1):
        if candles[i]["high"] >= target:
            return {
                "exit_index": i,
                "exit_price": target,
                "exit_type": "TP3",
            }

    return {
        "exit_index": fallback_index,
        "exit_price": candles[fallback_index]["close"],
        "exit_type": "FIXED_HORIZON",
    }


def resolve_all(records, candles, mode):
    out = []
    for record in records:
        x = resolve_exit(record, candles, mode)
        out.append({
            "candidate": record["candidate"],
            "entry_index": record["entry_index"],
            "fallback_index": record["fallback_index"],
            "exit_index": x["exit_index"],
            "exit_time": candles[x["exit_index"]]["time"],
            "exit_price": x["exit_price"],
            "exit_type": x["exit_type"],
        })
    return out


def simulate_window(records, window_start, window_end):
    eligible = [
        r for r in records
        if window_start <= r["candidate"]["entry_time"] <= window_end
        and r["exit_time"] <= window_end
    ]

    trading_pot = STARTING_POT_THB
    reserve = 0.0
    active_exit_time = None
    trades = []
    skipped_overlap = 0

    for row in eligible:
        c = row["candidate"]

        if active_exit_time is not None and c["entry_time"] < active_exit_time:
            skipped_overlap += 1
            continue

        risk = evaluate_risk(
            decision={
                "signal": c["signal"],
                "confidence": 0,
                "quality": "PASSED",
            },
            features={
                "close": c["entry"],
                "atr14": c["features"]["atr"],
            },
            capital=trading_pot / REFERENCE_USDTHB,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk.get("allowed"):
            continue

        position_value = float(risk["position_value"]) * REFERENCE_USDTHB
        entry = c["entry"]
        exit_price = row["exit_price"]
        gross_return = (exit_price - entry) / entry
        gross_pnl = position_value * gross_return
        cost = position_value * ROUND_TRIP_COST
        net_pnl = gross_pnl - cost

        pot_before = trading_pot
        reserve_before = reserve

        if net_pnl > 0:
            reserve += net_pnl
        else:
            trading_pot += net_pnl

        trades.append({
            "entry_time": c["entry_time"].isoformat(),
            "exit_time": row["exit_time"].isoformat(),
            "exit_type": row["exit_type"],
            "entry_price": entry,
            "exit_price": exit_price,
            "gross_return_pct": gross_return * 100.0,
            "position_value_thb": position_value,
            "gross_pnl_thb": gross_pnl,
            "cost_thb": cost,
            "net_pnl_thb": net_pnl,
            "trading_pot_before_thb": pot_before,
            "trading_pot_after_thb": trading_pot,
            "reserve_before_thb": reserve_before,
            "reserve_after_thb": reserve,
        })

        active_exit_time = row["exit_time"]

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "candidates_in_window": sum(
            1 for r in records
            if window_start <= r["candidate"]["entry_time"] <= window_end
        ),
        "resolved_trades": len(trades),
        "tp3_hits": sum(t["exit_type"] == "TP3" for t in trades),
        "fixed_horizon_exits": sum(
            t["exit_type"] == "FIXED_HORIZON" for t in trades
        ),
        "wins": len(wins),
        "losses": len(losses),
        "starting_trading_pot_thb": STARTING_POT_THB,
        "ending_trading_pot_thb": trading_pot,
        "reserve_thb": reserve,
        "total_equity_thb": trading_pot + reserve,
        "net_total_profit_thb": trading_pot + reserve - STARTING_POT_THB,
        "reserve_return_pct": reserve / STARTING_POT_THB * 100.0,
        "profit_factor": (
            gross_profit / gross_loss if gross_loss > 0 else None
        ),
        "skipped_overlap": skipped_overlap,
    }


def summarize(rows):
    result = {}
    for days in WINDOW_DAYS:
        bucket = [r for r in rows if r["window_days"] == days]
        nonempty = [r for r in bucket if r["resolved_trades"] > 0]

        def avg(key):
            return (
                sum(r[key] for r in nonempty) / len(nonempty)
                if nonempty else 0.0
            )

        result[f"{days}D"] = {
            "windows_total": len(bucket),
            "windows_with_trades": len(nonempty),
            "mean_reserve_thb": avg("reserve_thb"),
            "mean_total_profit_thb": avg("net_total_profit_thb"),
            "best_reserve_thb": (
                max((r["reserve_thb"] for r in nonempty), default=0.0)
            ),
            "worst_reserve_thb": (
                min((r["reserve_thb"] for r in nonempty), default=0.0)
            ),
            "positive_reserve_windows": sum(
                r["reserve_thb"] > 0 for r in nonempty
            ),
            "positive_reserve_window_rate_pct": (
                sum(r["reserve_thb"] > 0 for r in nonempty)
                / len(nonempty) * 100.0
                if nonempty else 0.0
            ),
            "total_trade_observations": sum(
                r["resolved_trades"] for r in bucket
            ),
            "total_tp3_hits": sum(r["tp3_hits"] for r in bucket),
            "total_fixed_horizon_exits": sum(
                r["fixed_horizon_exits"] for r in bucket
            ),
        }
    return result


def run_market(symbol, interval):
    print(f"\n{'-' * 72}\n{symbol} {interval}\n{'-' * 72}")

    candles = fetch_closed_candles_paginated(
        symbol, interval, CANDLE_LIMIT
    )
    if len(candles) != CANDLE_LIMIT:
        raise RuntimeError(
            f"{symbol} {interval}: expected {CANDLE_LIMIT:,}, "
            f"got {len(candles):,}"
        )

    records = build_records(candles)
    first_day = candles[0]["time"].date()
    last_day = candles[-1]["time"].date()

    modes = {
        "A_FIXED_20": resolve_all(records, candles, "FIXED_20"),
        "B_TP3_FALLBACK_20": resolve_all(records, candles, "TP3_FALLBACK_20"),
    }

    output = {
        "symbol": symbol,
        "interval": interval,
        "candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "candidates_found": len(records),
        "strategies": {},
    }

    for name, resolved in modes.items():
        rows = []
        anchor_day = first_day + timedelta(days=1)

        while anchor_day <= last_day:
            window_end = datetime(
                anchor_day.year, anchor_day.month, anchor_day.day,
                23, 59, 59, 999999, tzinfo=timezone.utc
            )

            for days in WINDOW_DAYS:
                window_start = window_end - timedelta(days=days)
                stats = simulate_window(
                    resolved, window_start, window_end
                )
                stats["symbol"] = symbol
                stats["interval"] = interval
                stats["window_days"] = days
                rows.append(stats)

            anchor_day += timedelta(days=1)

        output["strategies"][name] = {
            "window_summary": summarize(rows),
            "rolling_windows": rows,
        }

    return output


def main():
    print("=" * 72)
    print("PROFIT SWEEP EXIT COMPARISON V1")
    print("=" * 72)
    print("A = Fixed 20 bars")
    print("B = TP 3% + Fixed 20 bars fallback")
    print("Trading Pot = 1,500 THB")
    print("Positive Net P/L -> Reserve")
    print("Reserve never replenishes Trading Pot")
    print("Cost = 0.14% round trip")
    print("Risk Engine = REAL")
    print("Overlap = BLOCKED")
    print("History = 100,000 closed candles / market")
    print("=" * 72)

    results = [
        run_market(symbol, interval)
        for symbol, interval in UNIVERSE
    ]

    output = {
        "research": {
            "version": "PROFIT_SWEEP_EXIT_COMPARISON_V1",
            "research_only": True,
            "starting_trading_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100.0,
            "tp_pct": TP_LEVEL * 100.0,
            "fallback_bars": HORIZON_BARS,
            "history_limit": CANDLE_LIMIT,
            "windows": [f"{d}D" for d in WINDOW_DAYS],
            "profit_sweep": "positive_net_pnl_to_reserve",
            "reserve_replenishes_trading_pot": False,
            "ai_used": False,
            "production_changed": False,
            "tax_included": False,
        },
        "results": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nSAVED")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
