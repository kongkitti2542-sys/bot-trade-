import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB


STARTING_POT_THB = 1500.0
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

BIG_WINNER_MFE = 0.01
GIVEBACK_LEVELS = [0.002, 0.003, 0.005]

OUTPUT_FILE = Path(
    "money_machine_v2/research/"
    "big_winner_giveback_exit_impact_v1.json"
)


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
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

    return sorted(
        rows,
        key=lambda r: r["candidate"]["entry_time"],
    )


def select_entries(records):
    selected = []
    active_exit = None
    skipped = 0

    for record in records:
        if active_exit is not None and record["entry_index"] < active_exit:
            skipped += 1
            continue

        selected.append(record)
        active_exit = record["fixed_exit_index"]

    return selected, skipped


def get_position_value(candidate, pot):
    decision = {
        "signal": candidate["signal"],
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
        capital=pot / REFERENCE_USDTHB,
        daily_pnl=0.0,
        open_positions=0,
    )

    if not risk.get("allowed"):
        return None

    return float(risk["position_value"]) * REFERENCE_USDTHB


def prepare_entries(selected):
    pot = STARTING_POT_THB
    prepared = []

    for record in selected:
        position_value = get_position_value(
            record["candidate"],
            pot,
        )

        if position_value is None:
            continue

        prepared.append({
            **record,
            "position_value_thb": position_value,
        })

    return prepared


def settle(candidate, exit_price, position_value):
    gross_return = (
        exit_price - candidate["entry"]
    ) / candidate["entry"]

    gross = position_value * gross_return
    cost = position_value * ROUND_TRIP_COST
    net = gross - cost

    return gross, cost, net


def find_giveback_exit(
    candidate,
    candles,
    entry_index,
    fixed_exit_index,
    giveback_level,
):
    entry = float(candidate["entry"])
    peak = entry

    for visible_index in range(
        entry_index + 1,
        fixed_exit_index + 1,
    ):
        candle = candles[visible_index]

        peak = max(
            peak,
            float(candle["high"]),
        )

        mfe = peak / entry - 1.0

        giveback = (
            (peak - float(candle["close"])) / peak
            if peak > 0
            else 0.0
        )

        if (
            mfe >= BIG_WINNER_MFE
            and giveback >= giveback_level
        ):
            return {
                "exit_index": visible_index,
                "reason": "BIG_WINNER_GIVEBACK",
                "mfe_pct": mfe * 100.0,
                "giveback_pct": giveback * 100.0,
                "peak": peak,
            }

    return {
        "exit_index": fixed_exit_index,
        "reason": "FIXED_HORIZON",
        "mfe_pct": None,
        "giveback_pct": None,
        "peak": peak,
    }


def simulate(prepared, candles, giveback_level=None):
    pot = STARTING_POT_THB
    trades = []

    for number, record in enumerate(prepared, 1):
        candidate = record["candidate"]
        position_value = record["position_value_thb"]

        if giveback_level is None:
            exit_index = record["fixed_exit_index"]
            reason = "FIXED_HORIZON"
            mfe = None
            giveback = None
        else:
            decision = find_giveback_exit(
                candidate,
                candles,
                record["entry_index"],
                record["fixed_exit_index"],
                giveback_level,
            )

            exit_index = decision["exit_index"]
            reason = decision["reason"]
            mfe = decision["mfe_pct"]
            giveback = decision["giveback_pct"]

        exit_price = float(
            candles[exit_index]["close"]
        )

        gross, cost, net = settle(
            candidate,
            exit_price,
            position_value,
        )

        trades.append({
            "trade_number": number,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": candles[exit_index]["time"].isoformat(),
            "exit_reason": reason,
            "holding_bars": (
                exit_index - record["entry_index"]
            ),
            "position_value_thb": position_value,
            "exit_price": exit_price,
            "mfe_at_exit_pct": mfe,
            "giveback_at_exit_pct": giveback,
            "gross_pnl_thb": gross,
            "cost_thb": cost,
            "net_pnl_thb": net,
        })

        pot += net

    return trades, pot


def summarize(trades, ending_pot):
    exits = sum(
        t["exit_reason"] == "BIG_WINNER_GIVEBACK"
        for t in trades
    )

    return {
        "trades": len(trades),
        "giveback_exits": exits,
        "fixed_exits": len(trades) - exits,
        "ending_pot_thb": ending_pot,
        "net_profit_thb": (
            ending_pot - STARTING_POT_THB
        ),
        "win_rate_pct": (
            sum(t["net_pnl_thb"] > 0 for t in trades)
            / len(trades)
            * 100.0
            if trades else 0.0
        ),
    }


def main():
    print("=" * 72)
    print("BIG WINNER GIVEBACK EXIT IMPACT V1")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Candles      : {WINDOW_30D_CANDLES:,}")
    print(f"Big Winner   : MFE >= {BIG_WINNER_MFE * 100:.2f}%")
    print("Entry Set    : LOCKED BY FIXED HORIZON")
    print("Position     : FROZEN PER ENTRY")
    print("Opportunity  : BLOCKED")
    print("Lookahead    : BLOCKED")
    print("Profit Lock  : NOT USED")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)
    selected, skipped = select_entries(records)
    prepared = prepare_entries(selected)

    fixed_trades, fixed_pot = simulate(
        prepared,
        candles,
        None,
    )

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "big_winner_mfe_pct": BIG_WINNER_MFE * 100.0,
            "entry_set_locked": True,
            "opportunity_effect": "BLOCKED",
            "lookahead": False,
            "position_size_policy": "FROZEN_PER_ENTRY",
            "profit_lock_used": False,
            "round_trip_cost_pct": (
                ROUND_TRIP_COST * 100.0
            ),
        },
        "entry_selection": {
            "candidates": len(records),
            "selected_entries": len(selected),
            "prepared_entries": len(prepared),
            "skipped_overlap": skipped,
        },
        "fixed_horizon": {
            **summarize(
                fixed_trades,
                fixed_pot,
            ),
            "trades_detail": fixed_trades,
        },
        "giveback_strategies": {},
    }

    for level in GIVEBACK_LEVELS:
        key = f"{level * 100:.2f}%"

        trades, pot = simulate(
            prepared,
            candles,
            level,
        )

        row = summarize(trades, pot)

        row["exit_effect_vs_fixed_thb"] = (
            pot - fixed_pot
        )

        row["better_than_fixed"] = (
            pot > fixed_pot
        )

        row["trades_detail"] = trades

        output["giveback_strategies"][key] = row

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("RESULT")
    print("-" * 72)

    print(
        f"Fixed Horizon : "
        f"{fixed_pot:.2f} THB "
        f"({fixed_pot - STARTING_POT_THB:+.2f})"
    )

    for level, row in output[
        "giveback_strategies"
    ].items():
        print(
            f"Giveback {level} : "
            f"{row['ending_pot_thb']:.2f} THB "
            f"({row['net_profit_thb']:+.2f}) "
            f"effect={row['exit_effect_vs_fixed_thb']:+.2f} "
            f"exits={row['giveback_exits']}"
        )

    print(f"Saved        : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
