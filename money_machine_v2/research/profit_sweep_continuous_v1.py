"""Continuous Profit Sweep V1 — research only.

Purpose:
- Test the approved new capital-management idea over one continuous historical path.
- Compare A: Fixed 20-bar exit vs B: TP 3%, fallback Fixed 20.
- Start Trading Pot at 1,500 THB and Reserve at 0.
- Positive net P/L is swept entirely to Reserve.
- Negative net P/L reduces Trading Pot.
- Reserve never replenishes Trading Pot.
- Position sizing uses the current Trading Pot.
- Net P/L includes the locked 0.14% round-trip research cost.
- Real Risk Engine.
- Overlap blocked.
- Full-history candidate detection.
- Locked universe: SOLUSDT 30m, ETHUSDT 15m, SOLUSDT 15m.
- Up to 100,000 closed candles per market.
- No AI, regime, giveback, Profit Lock, or production changes.

Important:
- This is a single continuous chronological simulation per market/strategy.
- It does NOT reset capital at 1D/7D/30D windows.
- 1D/7D/30D are reported as separate trailing diagnostic summaries over
  the continuous equity path.
- Research only; no production approval.
"""

import json
import sys
from datetime import timedelta
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

OUTPUT_FILE = Path(
    "money_machine_v2/research/profit_sweep_continuous_v1.json"
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
    resolved = []

    for record in records:
        x = resolve_exit(record, candles, mode)
        idx = x["exit_index"]

        resolved.append({
            "candidate": record["candidate"],
            "entry_index": record["entry_index"],
            "fallback_index": record["fallback_index"],
            "exit_index": idx,
            "exit_time": candles[idx]["time"],
            "exit_price": x["exit_price"],
            "exit_type": x["exit_type"],
        })

    return resolved


def simulate_continuous(records):
    trading_pot = STARTING_POT_THB
    reserve = 0.0

    active_exit_time = None
    trades = []
    skipped_overlap = 0
    risk_rejected = 0
    pot_floor = trading_pot
    peak_equity = STARTING_POT_THB
    max_equity_drawdown = 0.0

    for row in records:
        c = row["candidate"]

        if active_exit_time is not None and c["entry_time"] < active_exit_time:
            skipped_overlap += 1
            continue

        if trading_pot <= 0:
            break

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
            risk_rejected += 1
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

        pot_floor = min(pot_floor, trading_pot)

        equity = trading_pot + reserve
        peak_equity = max(peak_equity, equity)
        drawdown = (
            (equity - peak_equity) / peak_equity
            if peak_equity > 0 else 0.0
        )
        max_equity_drawdown = min(max_equity_drawdown, drawdown)

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
            "total_equity_after_thb": equity,
        })

        active_exit_time = row["exit_time"]

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": trades,
        "summary": {
            "starting_trading_pot_thb": STARTING_POT_THB,
            "ending_trading_pot_thb": trading_pot,
            "reserve_thb": reserve,
            "total_equity_thb": trading_pot + reserve,
            "total_net_profit_thb": trading_pot + reserve - STARTING_POT_THB,
            "reserve_return_pct": reserve / STARTING_POT_THB * 100.0,
            "trading_pot_return_pct": (
                trading_pot / STARTING_POT_THB - 1.0
            ) * 100.0,
            "total_return_pct": (
                (trading_pot + reserve) / STARTING_POT_THB - 1.0
            ) * 100.0,
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": (
                len(wins) / len(trades) * 100.0
                if trades else 0.0
            ),
            "profit_factor": (
                gross_profit / gross_loss
                if gross_loss > 0 else None
            ),
            "tp3_hits": sum(
                t["exit_type"] == "TP3" for t in trades
            ),
            "fixed_horizon_exits": sum(
                t["exit_type"] == "FIXED_HORIZON"
                for t in trades
            ),
            "skipped_overlap": skipped_overlap,
            "risk_rejected": risk_rejected,
            "lowest_trading_pot_thb": pot_floor,
            "max_total_equity_drawdown_pct": (
                max_equity_drawdown * 100.0
            ),
        },
    }


def trailing_summary(trades, days):
    if not trades:
        return {
            "days": days,
            "windows_with_trades": 0,
        }

    timestamps = [t["exit_time"] for t in trades]
    end_time = trades[-1]["exit_time"]
    start_time = end_time - timedelta(days=days)

    window = [
        t for t in trades
        if start_time <= t["exit_time"] <= end_time
    ]

    wins = [t["net_pnl_thb"] for t in window if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in window if t["net_pnl_thb"] < 0]

    return {
        "days": days,
        "window_start": start_time,
        "window_end": end_time,
        "trades": len(window),
        "wins": len(wins),
        "losses": len(losses),
        "net_profit_thb": sum(t["net_pnl_thb"] for t in window),
        "tp3_hits": sum(t["exit_type"] == "TP3" for t in window),
        "fixed_horizon_exits": sum(
            t["exit_type"] == "FIXED_HORIZON"
            for t in window
        ),
    }


def run_market(symbol, interval):
    print(f"\n{'-' * 72}")
    print(f"{symbol} {interval}")
    print(f"{'-' * 72}")

    candles = fetch_closed_candles_paginated(
        symbol, interval, CANDLE_LIMIT
    )

    if len(candles) != CANDLE_LIMIT:
        raise RuntimeError(
            f"{symbol} {interval}: expected {CANDLE_LIMIT:,}, "
            f"got {len(candles):,}"
        )

    records = build_records(candles)

    result = {
        "symbol": symbol,
        "interval": interval,
        "candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "candidates_found": len(records),
        "strategies": {},
    }

    for name, mode in (
        ("A_FIXED_20", "FIXED_20"),
        ("B_TP3_FALLBACK_20", "TP3_FALLBACK_20"),
    ):
        resolved = resolve_all(records, candles, mode)
        sim = simulate_continuous(resolved)

        result["strategies"][name] = {
            "summary": sim["summary"],
            "trailing_1D": trailing_summary(sim["trades"], 1),
            "trailing_7D": trailing_summary(sim["trades"], 7),
            "trailing_30D": trailing_summary(sim["trades"], 30),
            "trades": sim["trades"],
        }

        s = sim["summary"]

        print(
            f"{name}: "
            f"trades={s['trades']} "
            f"reserve={s['reserve_thb']:+.2f} "
            f"pot={s['ending_trading_pot_thb']:.2f} "
            f"equity={s['total_equity_thb']:.2f} "
            f"PF={s['profit_factor']}"
        )

    return result


def main():
    print("=" * 72)
    print("CONTINUOUS PROFIT SWEEP BACKTEST V1")
    print("=" * 72)
    print("Trading Pot       : 1,500 THB")
    print("Positive Net P/L  : Sweep to Reserve")
    print("Reserve replenish : NO")
    print("A                 : Fixed 20 bars")
    print("B                 : TP 3% + Fixed 20 fallback")
    print("Cost              : 0.14% round trip")
    print("Risk              : REAL Risk Engine")
    print("Overlap           : BLOCKED")
    print("History           : 100,000 closed candles / market")
    print("Universe           : SOL30m / ETH15m / SOL15m")
    print("=" * 72)

    results = []

    for symbol, interval in UNIVERSE:
        results.append(run_market(symbol, interval))

    output = {
        "research": {
            "version": "PROFIT_SWEEP_CONTINUOUS_V1",
            "research_only": True,
            "starting_trading_pot_thb": STARTING_POT_THB,
            "starting_reserve_thb": 0.0,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100.0,
            "tp_pct": TP_LEVEL * 100.0,
            "fallback_bars": HORIZON_BARS,
            "history_limit": CANDLE_LIMIT,
            "continuous_path": True,
            "windows": ["1D", "7D", "30D"],
            "profit_sweep": "positive_net_pnl_to_reserve",
            "reserve_replenishes_trading_pot": False,
            "ai_used": False,
            "production_changed": False,
            "tax_included": False,
        },
        "results": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("SAVED")
    print("=" * 72)
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
