import json
from pathlib import Path

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

STARTING_POT = 1500.0
ROUND_TRIP_COST = 0.0014
HORIZON = 20

# Research grid only — NOT production rules.
GIVEBACKS = (
    0.0010,
    0.0015,
    0.0020,
    0.0025,
    0.0030,
    0.0040,
    0.0050,
)

OUTPUT = Path(
    "money_machine_v2/research/exit_optimization_audit_v1.json"
)


def gross_return(side, entry, exit_price):
    if side == "BUY":
        return (exit_price - entry) / entry
    return (entry - exit_price) / entry


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    records = []

    for candidate in find_candidates(candles):
        ei = index.get(candidate["entry_time"])
        xi = index.get(candidate["planned_exit_time"])

        if ei is None or xi is None:
            continue

        records.append({
            "candidate": candidate,
            "entry_index": ei,
            "fixed_exit_index": xi,
        })

    return sorted(
        records,
        key=lambda r: r["candidate"]["entry_time"],
    )


def simulate(records, candles, mode, giveback=0.0):
    pot = STARTING_POT
    active_exit = None
    trades = []
    skipped = 0

    for r in records:
        c = r["candidate"]
        ei = r["entry_index"]
        xi = r["fixed_exit_index"]

        if active_exit is not None and c["entry_time"] < active_exit:
            skipped += 1
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

        entry = c["entry"]
        peak = entry
        exit_index = xi
        exit_price = candles[xi]["close"]
        exit_type = "FIXED_HORIZON"

        if mode == "GIVEBACK":
            for i in range(ei, xi + 1):
                high = candles[i]["high"]

                if c["signal"] == "BUY":
                    peak = max(peak, high)
                    current_low = candles[i]["low"]

                    if peak > entry:
                        mfe = (peak - entry) / entry

                        if (
                            mfe >= giveback
                            and
                            (peak - current_low) / entry
                            >= giveback
                        ):
                            exit_index = i
                            exit_price = (
                                peak
                                - giveback * entry
                            )
                            exit_type = "GIVEBACK"
                            break

        elif mode == "ORACLE":
            peak_index = ei
            peak_price = entry

            for i in range(ei, xi + 1):
                if candles[i]["high"] > peak_price:
                    peak_price = candles[i]["high"]
                    peak_index = i

            exit_index = peak_index
            exit_price = peak_price
            exit_type = "ORACLE_PEAK"

        gr = gross_return(
            c["signal"],
            entry,
            exit_price,
        )

        gross = position_value * gr
        cost = position_value * ROUND_TRIP_COST
        net = gross - cost

        before = pot
        pot += net

        trades.append({
            "entry_time": c["entry_time"].isoformat(),
            "exit_time": candles[exit_index]["time"].isoformat(),
            "exit_type": exit_type,
            "gross_return_pct": gr * 100,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "net_pnl_thb": net,
            "pot_before_thb": before,
            "pot_after_thb": pot,
        })

        active_exit = candles[exit_index]["time"]

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    peak_pot = STARTING_POT
    max_dd = 0.0

    for t in trades:
        peak_pot = max(peak_pot, t["pot_after_thb"])
        dd = (t["pot_after_thb"] - peak_pot) / peak_pot
        max_dd = min(max_dd, dd)

    return {
        "mode": mode,
        "giveback_pct": giveback * 100,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "ending_pot_thb": pot,
        "net_profit_thb": pot - STARTING_POT,
        "return_pct": (pot / STARTING_POT - 1) * 100,
        "max_drawdown_pct": max_dd * 100,
        "biggest_winner_thb": max(wins, default=0.0),
        "average_winner_thb": (
            sum(wins) / len(wins) if wins else 0.0
        ),
        "average_loser_thb": (
            sum(losses) / len(losses) if losses else 0.0
        ),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        ),
        "skipped_overlap": skipped,
    }


def main():
    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)

    results = []

    results.append(
        simulate(records, candles, "FIXED_HORIZON")
    )

    results.append(
        simulate(records, candles, "ORACLE")
    )

    for gb in GIVEBACKS:
        results.append(
            simulate(
                records,
                candles,
                "GIVEBACK",
                gb,
            )
        )

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "resolved_candidates": len(records),
            "starting_pot_thb": STARTING_POT,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "research_only": True,
        },
        "results": results,
    }

    OUTPUT.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("EXIT OPTIMIZATION AUDIT V1")
    print("=" * 72)
    print(f"Candles     : {len(candles)}")
    print(f"Candidates  : {len(records)}")
    print()

    for r in results:
        gb = (
            f"{r['giveback_pct']:.2f}%"
            if r["mode"] == "GIVEBACK"
            else "-"
        )

        print(
            f"{r['mode']:<15} "
            f"GB={gb:<7} "
            f"N={r['trades']:>2} "
            f"Net={r['net_profit_thb']:+8.2f} "
            f"End={r['ending_pot_thb']:>8.2f} "
            f"BigWin={r['biggest_winner_thb']:+7.2f} "
            f"PF={r['profit_factor'] if r['profit_factor'] is not None else 'NA'} "
            f"DD={r['max_drawdown_pct']:.2f}%"
        )

    print("=" * 72)
    print("Saved:", OUTPUT)


if __name__ == "__main__":
    main()
