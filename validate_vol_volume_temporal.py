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
VALIDATION_START = datetime.fromisoformat(
    "2026-05-01T00:00:00+00:00"
)
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


def summarize(label, trades):
    if not trades:
        print(f"{label:<30} N=  0")
        return

    gross = sum(t["pnl"] for t in trades)
    net = sum(t["net"] for t in trades)

    wins = sum(
        1 for t in trades
        if t["pnl"] > 0
    )

    losses = sum(
        1 for t in trades
        if t["pnl"] < 0
    )

    gross_profit = sum(
        t["pnl"] for t in trades
        if t["pnl"] > 0
    )

    gross_loss = -sum(
        t["pnl"] for t in trades
        if t["pnl"] < 0
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    print(
        f"{label:<30} "
        f"N={len(trades):3d} "
        f"W={wins:3d} "
        f"L={losses:3d} "
        f"WR={wins / len(trades) * 100:6.2f}% "
        f"Gross={gross:+9.4f} "
        f"Net={net:+9.4f} "
        f"PF={pf:.3f}"
    )


def main():
    candles = load_candles()

    feature_rows = build_feature_rows(candles)
    row_by_time = {
        row["time"]: (index, row)
        for index, row in enumerate(feature_rows)
    }

    # Build reference strategy trades independently.
    # We use the existing core research chain, but only retain
    # trades whose exits are completely before VALIDATION_END.
    engine = IncrementalFeatures()

    capital = 1000.0
    daily_pnl = 0.0
    position = None
    trades = []
    risk_rejections = 0

    for index, candle in enumerate(candles):
        features = engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        if candle_time >= VALIDATION_END:
            break

        if position is not None:
            position["bars_held"] += 1

            side = position["side"]

            if side == "BUY":
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

            if side == "BUY":
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
                "side": side,
                "entry_price": position["entry_price"],
                "exit_price": exit_price,
                "position_size": position["position_size"],
                "pnl": pnl,
                "exit_reason": exit_reason,
                "net": 0.0,
                "vol_state": position["vol_state"],
                "volume_state": position["volume_state"],
            }

            trade["net"] = net_pnl(trade)
            trades.append(trade)

            capital += pnl
            position = None
            continue

        if candle_time < VALIDATION_START:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision=decision,
            features=features,
            capital=capital,
            daily_pnl=daily_pnl,
            open_positions=0,
        )

        if not risk["allowed"]:
            risk_rejections += 1
            continue

        entry_time = candle_time

        if entry_time not in row_by_time:
            continue

        feature_index, _ = row_by_time[entry_time]
        metrics = calculate_metrics(
            feature_rows,
            feature_index,
        )

        position = {
            "entry_time": entry_time,
            "side": decision["signal"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "bars_held": 0,
            "vol_state": state(metrics["volatility_rank"]),
            "volume_state": state(metrics["volume_rank"]),
        }

    print("=" * 92)
    print("VOLATILITY × VOLUME TEMPORAL VALIDATION")
    print("=" * 92)
    print(
        f"Validation: "
        f"{VALIDATION_START.isoformat()} "
        f"→ {VALIDATION_END.isoformat()}"
    )
    print(f"Trades:          {len(trades)}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"Fee:             {FEE_RATE * 100:.2f}% / side")
    print()
    print("LOCKED STATE DEFINITION")
    print("Vol Rank:    <33 LOW | 33-66 MID | >66 HIGH")
    print("Volume Rank: <33 LOW | 33-66 MID | >66 HIGH")
    print()

    print("ALL DIRECTIONS")
    print("-" * 92)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                t for t in trades
                if t["vol_state"] == vol
                and t["volume_state"] == volume
            ]

            summarize(
                f"V={vol:<4} VOL={volume:<4}",
                group,
            )

    print()
    print("BUY")
    print("-" * 92)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                t for t in trades
                if t["vol_state"] == vol
                and t["volume_state"] == volume
                and t["side"] == "BUY"
            ]

            summarize(
                f"V={vol:<4} VOL={volume:<4}",
                group,
            )

    print()
    print("SELL")
    print("-" * 92)

    for vol in ("LOW", "MID", "HIGH"):
        for volume in ("LOW", "MID", "HIGH"):
            group = [
                t for t in trades
                if t["vol_state"] == vol
                and t["volume_state"] == volume
                and t["side"] == "SELL"
            ]

            summarize(
                f"V={vol:<4} VOL={volume:<4}",
                group,
            )

    print()
    print("=" * 92)
    print("RESEARCH ONLY")
    print("No Core files modified.")
    print("No thresholds selected from validation P/L.")
    print("=" * 92)


if __name__ == "__main__":
    main()
