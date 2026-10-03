from datetime import datetime

from market_intelligence_formula_v1 import (
    build_feature_rows,
    calculate_metrics,
)
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk
from research_data_cache import load_candles


FEE_RATE = 0.0005
MAX_HOLD_BARS = 240

DISCOVERY_START = datetime.fromisoformat(
    "2025-10-18T00:00:00+00:00"
)
DISCOVERY_END = datetime.fromisoformat(
    "2026-05-01T00:00:00+00:00"
)

VALIDATION_START = DISCOVERY_END
VALIDATION_END = datetime.fromisoformat(
    "2026-07-21T10:05:00+00:00"
)


def state(rank):
    if rank < 33:
        return "LOW"
    if rank <= 66:
        return "MID"
    return "HIGH"


def net_pnl(trade):
    entry = trade["entry_price"]
    exit_price = trade["exit_price"]
    size = trade["position_size"]

    if trade["side"] == "BUY":
        gross = (exit_price - entry) * size
    else:
        gross = (entry - exit_price) * size

    fees = (
        entry * size * FEE_RATE
        + exit_price * size * FEE_RATE
    )

    return gross - fees


def run_period(candles, start, end):
    feature_rows = build_feature_rows(candles)
    row_by_time = {
        row["time"]: (index, row)
        for index, row in enumerate(feature_rows)
    }

    engine = IncrementalFeatures()

    capital = 1000.0
    position = None
    trades = []
    risk_rejections = 0

    for index, candle in enumerate(candles):
        features = engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        if candle_time >= end:
            break

        if position is not None:
            position["bars_held"] += 1

            if position["side"] == "BUY":
                stop_hit = candle["low"] <= position["stop_loss"]
            else:
                stop_hit = candle["high"] >= position["stop_loss"]

            if stop_hit:
                exit_price = position["stop_loss"]
                exit_reason = "STOP_LOSS"
            elif position["bars_held"] >= MAX_HOLD_BARS:
                exit_price = candle["close"]
                exit_reason = "TIME_EXIT"
            else:
                continue

            if position["side"] == "BUY":
                pnl = (
                    exit_price - position["entry_price"]
                ) * position["position_size"]
            else:
                pnl = (
                    position["entry_price"] - exit_price
                ) * position["position_size"]

            trade = {
                "entry_time": position["entry_time"],
                "exit_time": candle_time,
                "side": position["side"],
                "entry_price": position["entry_price"],
                "exit_price": exit_price,
                "position_size": position["position_size"],
                "pnl": pnl,
                "net": 0.0,
                "exit_reason": exit_reason,
                "vol_state": position["vol_state"],
                "volume_state": position["volume_state"],
            }

            trade["net"] = net_pnl(trade)

            trades.append(trade)
            capital += pnl
            position = None
            continue

        if candle_time < start:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision=decision,
            features=features,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            risk_rejections += 1
            continue

        if candle_time not in row_by_time:
            continue

        feature_index, _ = row_by_time[candle_time]

        metrics = calculate_metrics(
            feature_rows,
            feature_index,
        )

        position = {
            "entry_time": candle_time,
            "side": decision["signal"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "bars_held": 0,
            "vol_state": state(metrics["volatility_rank"]),
            "volume_state": state(metrics["volume_rank"]),
        }

    return trades, risk_rejections


def summarize(group):
    if not group:
        return (0, 0, 0, 0.0, 0.0, 0.0)

    gross = sum(t["pnl"] for t in group)
    net = sum(t["net"] for t in group)

    wins = sum(t["pnl"] > 0 for t in group)
    losses = sum(t["pnl"] < 0 for t in group)

    gross_profit = sum(
        t["pnl"] for t in group if t["pnl"] > 0
    )

    gross_loss = -sum(
        t["pnl"] for t in group if t["pnl"] < 0
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    return len(group), wins, losses, gross, net, pf


def print_period(name, trades):
    print()
    print("=" * 92)
    print(name)
    print("=" * 92)

    total = summarize(trades)

    print(
        f"ALL             N={total[0]:3d} "
        f"W={total[1]:3d} L={total[2]:3d} "
        f"Gross={total[3]:+.4f} "
        f"Net={total[4]:+.4f} "
        f"PF={total[5]:.3f}"
    )

    print("-" * 92)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                t for t in trades
                if t["vol_state"] == vol
                and t["volume_state"] == volume
            ]

            result = summarize(group)

            print(
                f"V={vol:<4} VOL={volume:<4} "
                f"N={result[0]:3d} "
                f"W={result[1]:3d} "
                f"L={result[2]:3d} "
                f"Gross={result[3]:+.4f} "
                f"Net={result[4]:+.4f} "
                f"PF={result[5]:.3f}"
            )

    print()
    print("HIGH × MID BY DIRECTION")

    group = [
        t for t in trades
        if t["vol_state"] == "HIGH"
        and t["volume_state"] == "MID"
    ]

    for side in ("BUY", "SELL"):
        side_group = [
            t for t in group
            if t["side"] == side
        ]

        result = summarize(side_group)

        print(
            f"{side:<4} "
            f"N={result[0]:3d} "
            f"W={result[1]:3d} "
            f"L={result[2]:3d} "
            f"Gross={result[3]:+.4f} "
            f"Net={result[4]:+.4f} "
            f"PF={result[5]:.3f}"
        )


def main():
    candles = load_candles()

    discovery, discovery_rej = run_period(
        candles,
        DISCOVERY_START,
        DISCOVERY_END,
    )

    validation, validation_rej = run_period(
        candles,
        VALIDATION_START,
        VALIDATION_END,
    )

    print("=" * 92)
    print("VOLATILITY × VOLUME — DISCOVERY vs VALIDATION")
    print("=" * 92)
    print("State definition is LOCKED:")
    print("Vol Rank    <33 LOW | 33-66 MID | >66 HIGH")
    print("Volume Rank <33 LOW | 33-66 MID | >66 HIGH")
    print()
    print(f"Discovery risk rejections: {discovery_rej}")
    print(f"Validation risk rejections: {validation_rej}")

    print_period("DISCOVERY", discovery)
    print_period("VALIDATION", validation)

    print()
    print("=" * 92)
    print("RESEARCH ONLY")
    print("No Core files modified.")
    print("No thresholds selected from P/L.")
    print("=" * 92)


if __name__ == "__main__":
    main()
