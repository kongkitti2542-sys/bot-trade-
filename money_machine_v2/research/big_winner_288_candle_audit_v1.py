import json
from pathlib import Path

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT_THB = 1500.0
ROUND_TRIP_COST = 0.0014
CANDLES_PER_DAY = 288
OUTPUT_FILE = Path("money_machine_v2/research/big_winner_288_candle_audit_v1.json")


def gross_return(signal, entry, exit_price):
    if signal == "BUY":
        return (exit_price - entry) / entry
    return (entry - exit_price) / entry


def main():
    candles = fetch_closed_candles_paginated(
        SYMBOL, INTERVAL, WINDOW_30D_CANDLES
    )

    candidates = find_candidates(candles)
    index = {c["time"]: i for i, c in enumerate(candles)}

    records = []
    for c in candidates:
        ei = index.get(c["entry_time"])
        xi = index.get(c["planned_exit_time"])
        if ei is None or xi is None:
            continue

        risk = evaluate_risk(
            decision={"signal": c["signal"], "confidence": 0, "quality": "PASSED"},
            features={"close": c["entry"], "atr14": c["features"]["atr"]},
            capital=STARTING_POT_THB / REFERENCE_USDTHB,
            daily_pnl=0.0,
            open_positions=0,
        )
        if not risk.get("allowed"):
            continue

        records.append({
            "entry_index": ei,
            "exit_index": xi,
            "entry_time": c["entry_time"].isoformat(),
            "entry": c["entry"],
            "signal": c["signal"],
            "position_value_thb": float(risk["position_value"]) * REFERENCE_USDTHB,
        })

    records.sort(key=lambda x: x["entry_index"])

    windows = []
    for start in range(0, len(candles), CANDLES_PER_DAY):
        end = min(start + CANDLES_PER_DAY, len(candles))
        rows = [
            r for r in records
            if start <= r["entry_index"] < end
        ]

        trades = []
        for r in rows:
            highs = [c["high"] for c in candles[r["entry_index"]:r["exit_index"] + 1]]
            lows = [c["low"] for c in candles[r["entry_index"]:r["exit_index"] + 1]]

            if r["signal"] == "BUY":
                mfe = max(highs) / r["entry"] - 1
                exit_price = candles[r["exit_index"]]["close"]
            else:
                mfe = 1 - min(lows) / r["entry"]
                exit_price = candles[r["exit_index"]]["close"]

            gr = gross_return(r["signal"], r["entry"], exit_price)
            pv = r["position_value_thb"]
            gross = pv * gr
            cost = pv * ROUND_TRIP_COST
            net = gross - cost

            trades.append({
                "entry_time": r["entry_time"],
                "mfe_pct": mfe * 100,
                "gross_pnl_thb": gross,
                "cost_thb": cost,
                "net_pnl_thb": net,
            })

        wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
        losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]
        net = sum(t["net_pnl_thb"] for t in trades)

        windows.append({
            "window": len(windows) + 1,
            "start_time": candles[start]["time"].isoformat(),
            "end_time": candles[end - 1]["time"].isoformat(),
            "candles": end - start,
            "candidates": len(rows),
            "net_pnl_thb": net,
            "biggest_winner_thb": max(wins, default=0.0),
            "average_winner_thb": sum(wins) / len(wins) if wins else 0.0,
            "average_loser_thb": sum(losses) / len(losses) if losses else 0.0,
            "max_mfe_pct": max((t["mfe_pct"] for t in trades), default=0.0),
            "trades": trades,
        })

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "candles_per_window": CANDLES_PER_DAY,
            "windows": len(windows),
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
        },
        "windows": windows,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 72)
    print("BIG WINNER 288-CANDLE AUDIT V1")
    print("=" * 72)
    print(f"Candles  : {len(candles)}")
    print(f"Windows  : {len(windows)}")
    print(f"Candidates: {len(records)}")
    print()
    for w in windows:
        print(
            f"W{w['window']:02d} "
            f"N={w['candidates']:2d} "
            f"Net={w['net_pnl_thb']:+8.2f} "
            f"BigWin={w['biggest_winner_thb']:+7.2f} "
            f"AvgWin={w['average_winner_thb']:+7.2f} "
            f"MFE={w['max_mfe_pct']:.2f}%"
        )
    print("=" * 72)
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
