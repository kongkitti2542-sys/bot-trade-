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

OUTPUT_FILE = Path(
    "money_machine_v2/research/sequential_oracle_audit_v1.json"
)


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    records = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])
        fixed_exit_index = index.get(candidate["planned_exit_time"])

        if entry_index is None or fixed_exit_index is None:
            continue

        records.append({
            "candidate": candidate,
            "entry_index": entry_index,
            "fixed_exit_index": fixed_exit_index,
        })

    records.sort(key=lambda r: r["candidate"]["entry_time"])
    return records


def oracle_decision(entry, visible_candles, entry_index):
    """
    Research Oracle.

    IMPORTANT:
    It receives only candles that have already closed.
    It cannot access candles after the latest visible candle.

    V1 deliberately uses a simple observable rule:
    - after entry, inspect each newly closed candle
    - track MFE from visible highs
    - if price has reached +0.30% from entry and subsequently
      gives back at least 0.20% from the observed peak,
      EXIT
    - otherwise HOLD
    - if fixed horizon is reached, EXIT

    This is a sequential replay mechanism, not hindsight.
    """

    peak_price = entry

    for candle in visible_candles:
        peak_price = max(peak_price, candle["high"])

        mfe = peak_price / entry - 1.0
        current_drawdown = (
            peak_price - candle["close"]
        ) / peak_price if peak_price > 0 else 0.0

        if mfe >= 0.0030 and current_drawdown >= 0.0020:
            return {
                "action": "EXIT",
                "reason": "PEAK_GIVEBACK",
                "peak_price": peak_price,
                "mfe_pct": mfe * 100.0,
                "giveback_pct": current_drawdown * 100.0,
                "visible_through": candle["time"],
            }

    return {
        "action": "HOLD",
        "reason": "NO_EXIT",
        "peak_price": peak_price,
        "mfe_pct": (
            peak_price / entry - 1.0
        ) * 100.0,
        "giveback_pct": 0.0,
        "visible_through": (
            visible_candles[-1]["time"]
            if visible_candles
            else None
        ),
    }


def simulate_trade(record, candles, pot):
    candidate = record["candidate"]
    entry_index = record["entry_index"]
    fixed_exit_index = record["fixed_exit_index"]

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

    position_value_thb = (
        float(risk["position_value"])
        * REFERENCE_USDTHB
    )

    # Sequential replay:
    # At each step, only candles through `visible_index`
    # are passed to the Oracle.
    exit_index = fixed_exit_index
    exit_price = candles[fixed_exit_index]["close"]
    exit_reason = "FIXED_HORIZON"

    decision_log = []

    for visible_index in range(
        entry_index + 1,
        fixed_exit_index + 1,
    ):
        visible_candles = candles[
            entry_index + 1:visible_index + 1
        ]

        oracle = oracle_decision(
            candidate["entry"],
            visible_candles,
            entry_index,
        )

        decision_log.append({
            "decision_time": candles[visible_index]["time"].isoformat(),
            "visible_through": (
                candles[visible_index]["time"].isoformat()
            ),
            "action": oracle["action"],
            "reason": oracle["reason"],
            "mfe_pct": oracle["mfe_pct"],
            "giveback_pct": oracle["giveback_pct"],
        })

        if oracle["action"] == "EXIT":
            exit_index = visible_index
            exit_price = candles[visible_index]["close"]
            exit_reason = oracle["reason"]
            break

    gross_return = (
        exit_price - candidate["entry"]
    ) / candidate["entry"]

    gross_pnl = position_value_thb * gross_return
    cost = position_value_thb * ROUND_TRIP_COST
    net_pnl = gross_pnl - cost

    return {
        "entry_time": candidate["entry_time"].isoformat(),
        "exit_time": candles[exit_index]["time"].isoformat(),
        "entry": candidate["entry"],
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_bars": exit_index - entry_index,
        "holding_minutes": (
            exit_index - entry_index
        ) * 5,
        "position_value_thb": position_value_thb,
        "gross_pnl_thb": gross_pnl,
        "cost_thb": cost,
        "net_pnl_thb": net_pnl,
        "pot_before_thb": pot,
        "pot_after_thb": pot + net_pnl,
        "decision_log": decision_log,
    }


def main():
    print("=" * 72)
    print("SEQUENTIAL ORACLE AUDIT V1")
    print("=" * 72)
    print(f"Symbol     : {SYMBOL}")
    print(f"Interval   : {INTERVAL}")
    print(f"Candles    : {WINDOW_30D_CANDLES:,}")
    print(f"Start Pot  : {STARTING_POT_THB:.2f} THB")
    print("Mode       : SEQUENTIAL / CLOSED CANDLES ONLY")
    print("Lookahead  : BLOCKED")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)

    print(f"Candles returned : {len(candles):,}")
    print(f"Candidates       : {len(records)}")

    pot = STARTING_POT_THB
    active_exit_index = None
    trades = []
    skipped_overlap = 0

    for record in records:
        entry_index = record["entry_index"]

        if (
            active_exit_index is not None
            and entry_index < active_exit_index
        ):
            skipped_overlap += 1
            continue

        trade = simulate_trade(
            record,
            candles,
            pot,
        )

        if trade is None:
            continue

        pot = trade["pot_after_thb"]
        active_exit_index = (
            entry_index
            + trade["holding_bars"]
        )

        trade["trade_number"] = len(trades) + 1
        trades.append(trade)

    wins = sum(
        t["net_pnl_thb"] > 0
        for t in trades
    )

    losses = sum(
        t["net_pnl_thb"] < 0
        for t in trades
    )

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "candidates": len(records),
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "lookahead": False,
            "decision_unit": "CLOSED_CANDLE",
        },
        "summary": {
            "trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": (
                wins / len(trades) * 100
                if trades else 0.0
            ),
            "ending_pot_thb": pot,
            "net_profit_thb": pot - STARTING_POT_THB,
            "return_pct": (
                (pot - STARTING_POT_THB)
                / STARTING_POT_THB
                * 100
            ),
            "skipped_overlap": skipped_overlap,
            "oracle_exits": sum(
                t["exit_reason"] != "FIXED_HORIZON"
                for t in trades
            ),
            "fixed_horizon_exits": sum(
                t["exit_reason"] == "FIXED_HORIZON"
                for t in trades
            ),
        },
        "trades": trades,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("RESULT")
    print("=" * 72)
    print(f"Trades       : {len(trades)}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    print(
        f"Win Rate     : {output['summary']['win_rate_pct']:.2f}%"
    )
    print(
        f"Oracle Exits : {output['summary']['oracle_exits']}"
    )
    print(
        f"Fixed Exits  : {output['summary']['fixed_horizon_exits']}"
    )
    print(
        f"Net Profit   : {output['summary']['net_profit_thb']:+.2f} THB"
    )
    print(
        f"End Pot      : {output['summary']['ending_pot_thb']:.2f} THB"
    )
    print(
        f"Return       : {output['summary']['return_pct']:+.4f}%"
    )
    print(
        f"Overlap Skip : {skipped_overlap}"
    )
    print("=" * 72)
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
