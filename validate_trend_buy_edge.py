from collections import deque
from datetime import datetime

from backtest_data_100k import get_historical_candles_100k, validate_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk
from capital_config import STARTING_CAPITAL_USDT

OOS_BOUNDARY = datetime.fromisoformat("2026-07-21T10:05:00+00:00")
HISTORY_SIZE = 250
MAX_HOLD_BARS = 240

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002

FEATURES = {
    "price_vs_ema200_pct": ("high",),
    "ema50_vs_ema200_pct": ("high",),
    "ema20_vs_ema50_pct": ("high",),
    "price_vs_ema50_pct": ("high",),
    "ema50_buffer_pct": ("high",),
    "pullback_depth_pct": ("low",),
    "atr_pct": ("high",),
}

def pct_diff(a, b):
    if a is None or b in (None, 0):
        return None
    return (a - b) / b * 100.0


def snapshot(features, candles):
    close = features["close"]
    ema20 = features["ema20"]
    ema50 = features["ema50"]
    ema200 = features["ema200"]

    recent = candles[-6:-1] if len(candles) >= 6 else []
    current = candles[-1] if candles else None

    if not recent or current is None:
        return {}

    pullback_low = min(c["low"] for c in recent)

    return {
        "price_vs_ema200_pct": pct_diff(close, ema200),
        "ema50_vs_ema200_pct": pct_diff(ema50, ema200),
        "ema20_vs_ema50_pct": pct_diff(ema20, ema50),
        "price_vs_ema50_pct": pct_diff(close, ema50),
        "ema50_buffer_pct": pct_diff(pullback_low, ema50),
        "pullback_depth_pct": pct_diff(pullback_low, ema20),
        "atr_pct": (
            features["atr14"] / close * 100.0
            if features["atr14"] is not None and close
            else None
        ),
    }


def percentile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None

    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)

    if lo == hi:
        return values[lo]

    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def gross_trade(position, exit_price):
    if position["side"] == "BUY":
        return (exit_price - position["entry_price"]) * position["position_size"]
    return (position["entry_price"] - exit_price) * position["position_size"]


def run():
    candles = get_historical_candles_100k()

    valid, reason = validate_candles(candles)
    print("=" * 100)
    print("TREND_PULLBACK + BUY — EDGE VALIDATION")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 100)
    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {'valid' if valid else 'invalid'}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY.isoformat()}")
    print(f"Starting Pot:   ${STARTING_CAPITAL_USDT:.4f}")
    print("=" * 100)

    if not valid:
        return

    inc = IncrementalFeatures()
    history = deque(maxlen=HISTORY_SIZE)

    entries = []
    position = None

    for idx, candle in enumerate(candles):
        features = inc.update(candle)
        history.append(candle)

        if idx < 200 or features is None:
            continue

        if position is not None:
            position["bars_held"] += 1

            if candle["low"] <= position["stop_loss"]:
                exit_price = position["stop_loss"]
                pnl = gross_trade(position, exit_price)
                position["exit_price"] = exit_price
                position["gross_pnl"] = pnl
                position["exit_reason"] = "STOP_LOSS"
                entries.append(position)
                position = None
                continue

            if position["bars_held"] >= MAX_HOLD_BARS:
                exit_price = candle["close"]
                pnl = gross_trade(position, exit_price)
                position["exit_price"] = exit_price
                position["gross_pnl"] = pnl
                position["exit_reason"] = "TIME_EXIT"
                entries.append(position)
                position = None
                continue

            continue

        if candle["time"] < OOS_BOUNDARY:
            continue

        regime = detect_regime(features)
        decision = analyze_market(list(history), features, regime)

        if (
            decision.get("signal") != "BUY"
            or decision.get("setup") != "TREND_PULLBACK"
        ):
            continue

        risk = evaluate_risk(
            decision,
            features,
            capital=STARTING_CAPITAL_USDT,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk.get("allowed", False):
            continue

        entry_price = features["close"]
        stop_loss = risk.get("stop_loss", entry_price * 0.99)
        position_size = risk.get("position_size", 0.0)

        if position_size <= 0:
            continue

        entries.append({
            "entry_time": candle["time"],
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "position_size": position_size,
            "bars_held": 0,
            "side": "BUY",
            "setup": "TREND_PULLBACK",
            "features": snapshot(features, list(history)),
            "gross_pnl": None,
            "exit_price": None,
            "exit_reason": None,
        })

        position = entries.pop()

    return entries


def simulate(trades, threshold_map=None):
    selected = []

    for trade in trades:
        if threshold_map:
            ok = True

            for name, (direction, threshold) in threshold_map.items():
                value = trade["features"].get(name)

                if value is None:
                    ok = False
                    break

                if direction == "high" and value < threshold:
                    ok = False
                    break

                if direction == "low" and value > threshold:
                    ok = False
                    break

            if not ok:
                continue

        selected.append(trade)

    gross = sum(t["gross_pnl"] for t in selected)

    fees = sum(
        abs(t["entry_price"] * t["position_size"]) * FEE_PER_SIDE
        + abs(t["exit_price"] * t["position_size"]) * FEE_PER_SIDE
        for t in selected
    )

    slip = sum(
        abs(t["entry_price"] * t["position_size"]) * SLIPPAGE_PER_SIDE
        + abs(t["exit_price"] * t["position_size"]) * SLIPPAGE_PER_SIDE
        for t in selected
    )

    net = gross - fees - slip

    wins = sum(1 for t in selected if t["gross_pnl"] > 0)
    losses = sum(1 for t in selected if t["gross_pnl"] < 0)

    gross_wins = sum(t["gross_pnl"] for t in selected if t["gross_pnl"] > 0)
    gross_losses = abs(sum(t["gross_pnl"] for t in selected if t["gross_pnl"] < 0))

    pf = gross_wins / gross_losses if gross_losses else float("inf")

    return {
        "trades": len(selected),
        "wins": wins,
        "losses": losses,
        "gross": gross,
        "fees": fees,
        "slip": slip,
        "net": net,
        "pf": pf,
    }


def main():
    trades = run()

    if not trades:
        print("No candidate trades found.")
        return

    split = len(trades) // 2
    discovery = trades[:split]
    validation = trades[split:]

    print()
    print("=" * 100)
    print("TIME SPLIT")
    print("=" * 100)
    print(f"Discovery trades: {len(discovery)}")
    print(f"Validation trades: {len(validation)}")

    print()
    print("=" * 100)
    print("BASELINE")
    print("=" * 100)

    for label, data in [
        ("DISCOVERY", discovery),
        ("VALIDATION", validation),
        ("ALL", trades),
    ]:
        r = simulate(data)
        print(
            f"{label:10s} | "
            f"Trades {r['trades']:3d} | "
            f"Gross {r['gross']:+.6f} | "
            f"Net {r['net']:+.6f} | "
            f"PF {r['pf']:.4f}"
        )

    print()
    print("=" * 100)
    print("DISCOVERY THRESHOLDS — 75TH / 25TH PERCENTILE")
    print("=" * 100)

    thresholds = {}

    for name, (direction,) in FEATURES.items():
        values = [
            t["features"].get(name)
            for t in discovery
            if t["features"].get(name) is not None
        ]

        q = percentile(values, 0.75 if direction == "high" else 0.25)

        thresholds[name] = (direction, q)

        print(f"{name:28s} {direction:4s} threshold = {q:.6f}")

    print()
    print("=" * 100)
    print("SINGLE-FEATURE VALIDATION")
    print("=" * 100)

    for name, (direction, threshold) in thresholds.items():
        r = simulate(
            validation,
            {
                name: (direction, threshold)
            },
        )

        print(
            f"{name:28s} | "
            f"N {r['trades']:3d} | "
            f"Gross {r['gross']:+.6f} | "
            f"Net {r['net']:+.6f} | "
            f"PF {r['pf']:.4f}"
        )

    print()
    print("=" * 100)
    print("COMBINED TREND-STRENGTH TEST")
    print("=" * 100)

    combined_names = [
        "price_vs_ema200_pct",
        "ema50_vs_ema200_pct",
        "ema20_vs_ema50_pct",
    ]

    combined = {
        name: thresholds[name]
        for name in combined_names
    }

    r = simulate(validation, combined)

    print(
        f"Combined | "
        f"N {r['trades']:3d} | "
        f"Gross {r['gross']:+.6f} | "
        f"Fees {r['fees']:.6f} | "
        f"Slip {r['slip']:.6f} | "
        f"Net {r['net']:+.6f} | "
        f"PF {r['pf']:.4f}"
    )

    print()
    print("=" * 100)
    print("INTERPRETATION RULE")
    print("=" * 100)
    print("A feature is interesting only if its threshold is discovered")
    print("from the first half and remains useful on the unseen second half.")
    print("No Core strategy/risk file was modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
