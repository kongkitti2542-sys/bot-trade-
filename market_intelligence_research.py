from collections import Counter, defaultdict
from statistics import median
from datetime import datetime
from research_data_cache import load_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 240
FEE_RATE = 0.0005
OOS_BOUNDARY = datetime.fromisoformat("2026-07-21T10:05:00+00:00")


def percentile(values, p):
    if not values:
        return None

    values = sorted(values)
    index = (len(values) - 1) * p / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower

    if lower == upper:
        return values[lower]

    return values[lower] * (1 - weight) + values[upper] * weight


def build_feature_rows(candles):
    engine = IncrementalFeatures()
    rows = []

    for candle in candles:
        features = engine.update(candle)

        if features["ema200"] is None:
            continue

        rows.append({
            "time": candle["time"],
            "high": candle["high"],
            "low": candle["low"],
            "features": features,
            "regime": detect_regime(features),
        })

    return rows


def describe_distribution(rows):
    atr_pct = []
    bb_width = []
    rsi = []
    relative_volume = []
    ema200_distance = []
    ema20_50_distance = []

    for row in rows:
        f = row["features"]

        atr_pct.append(f["atr14"] / f["close"])
        bb_width.append(f["bollinger"]["width"])
        rsi.append(f["rsi14"])
        relative_volume.append(f["relative_volume"])
        ema200_distance.append(
            (f["close"] - f["ema200"]) / f["close"]
        )
        ema20_50_distance.append(
            abs(f["ema20"] - f["ema50"]) / f["close"]
        )

    distributions = {
        "atr_pct": atr_pct,
        "bb_width": bb_width,
        "rsi": rsi,
        "relative_volume": relative_volume,
        "ema200_distance": ema200_distance,
        "ema20_50_distance": ema20_50_distance,
    }

    print()
    print("FEATURE DISTRIBUTIONS")
    print("=" * 72)

    for name, values in distributions.items():
        print()
        print(name)
        print(
            f"P10={percentile(values,10):.6f}  "
            f"P25={percentile(values,25):.6f}  "
            f"MED={percentile(values,50):.6f}  "
            f"P75={percentile(values,75):.6f}  "
            f"P90={percentile(values,90):.6f}"
        )


def simulate_strategy_trades(rows):
    """
    Research reconstruction only.

    Uses the existing Features -> Regime -> Strategy -> Risk chain.
    Does not modify any Core module.
    """

    capital = STARTING_CAPITAL
    position = None
    trades = []
    risk_rejections = 0

    for row in rows:
        f = row["features"]
        regime = row["regime"]
        candle_time = row["time"]

        if position is not None:
            position["bars_held"] += 1

            exit_price = None
            exit_reason = None

            if position["side"] == "BUY":
                if row["low"] <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "STOP_LOSS"
            else:
                if row["high"] >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "STOP_LOSS"

            if exit_price is None and position["bars_held"] >= MAX_HOLD_BARS:
                exit_price = f["close"]
                exit_reason = "TIME_EXIT"

            if exit_price is not None:
                if position["side"] == "BUY":
                    gross_pnl = (
                        exit_price - position["entry_price"]
                    ) * position["position_size"]
                else:
                    gross_pnl = (
                        position["entry_price"] - exit_price
                    ) * position["position_size"]

                entry_fee = (
                    position["entry_price"]
                    * position["position_size"]
                    * FEE_RATE
                )

                exit_fee = (
                    exit_price
                    * position["position_size"]
                    * FEE_RATE
                )

                net_pnl = gross_pnl - entry_fee - exit_fee

                capital += gross_pnl

                trade = {
                    "entry_time": position["entry_time"],
                    "exit_time": candle_time,
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "position_size": position["position_size"],
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "exit_reason": exit_reason,
                    "bars_held": position["bars_held"],
                    "score": position["score"],
                    "regime": position["regime"],
                    "rsi": position["rsi"],
                    "relative_volume": position["relative_volume"],
                    "atr_pct": position["atr_pct"],
                    "bb_width": position["bb_width"],
                    "ema200_distance": position["ema200_distance"],
                    "ema20_50_distance": position["ema20_50_distance"],
                    "structure": position["structure"],
                }

                trades.append(trade)
                position = None

            continue

        # Match the locked OOS reference boundary.
        if candle_time < OOS_BOUNDARY:
            continue

        decision = analyze_market(f, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision=decision,
            features=f,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            risk_rejections += 1
            continue

        position = {
            "entry_time": candle_time,
            "side": decision["signal"],
            "entry_price": f["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "score": decision["score"],
            "regime": regime,
            "rsi": f["rsi14"],
            "relative_volume": f["relative_volume"],
            "atr_pct": f["atr14"] / f["close"],
            "bb_width": f["bollinger"]["width"],
            "ema200_distance": (
                f["close"] - f["ema200"]
            ) / f["close"],
            "ema20_50_distance": (
                abs(f["ema20"] - f["ema50"])
                / f["close"]
            ),
            "structure": f["structure"]["structure"],
            "bars_held": 0,
        }

    return trades, risk_rejections


def summarize_numeric(trades, key, groups=5):
    values = sorted(t[key] for t in trades)

    if not values:
        return

    boundaries = []

    for i in range(groups + 1):
        index = int((len(values) - 1) * i / groups)
        boundaries.append(values[index])

    print()
    print(f"QUANTILE ANALYSIS: {key.upper()}")
    print("=" * 72)

    for i in range(groups):
        low = boundaries[i]
        high = boundaries[i + 1]

        if i == groups - 1:
            selected = [
                t for t in trades
                if low <= t[key] <= high
            ]
        else:
            selected = [
                t for t in trades
                if low <= t[key] < high
            ]

        if not selected:
            continue

        gross = sum(t["gross_pnl"] for t in selected)
        net = sum(t["net_pnl"] for t in selected)
        wins = sum(t["net_pnl"] > 0 for t in selected)

        print(
            f"Q{i + 1} "
            f"[{low:.6f}, {high:.6f}] "
            f"N={len(selected):4d} "
            f"W={wins:4d} "
            f"Gross={gross:9.4f} "
            f"Net={net:9.4f} "
            f"AvgNet={net / len(selected):9.5f}"
        )


def summarize_groups(trades, key):
    groups = defaultdict(list)

    for trade in trades:
        groups[trade[key]].append(trade)

    print()
    print(f"GROUP BY {key.upper()}")
    print("=" * 72)

    for group, items in sorted(groups.items(), key=lambda x: str(x[0])):
        gross = sum(t["gross_pnl"] for t in items)
        net = sum(t["net_pnl"] for t in items)
        wins = sum(t["net_pnl"] > 0 for t in items)

        print(
            f"{str(group):20s} "
            f"N={len(items):4d} "
            f"W={wins:4d} "
            f"Gross={gross:9.4f} "
            f"Net={net:9.4f} "
            f"AvgNet={net / len(items):9.5f}"
        )


def main():
    candles = load_candles()
    rows = build_feature_rows(candles)

    print("MARKET INTELLIGENCE RESEARCH V1")
    print("=" * 72)
    print(f"Candles:       {len(candles)}")
    print(f"Feature rows:  {len(rows)}")
    print(f"Dataset start: {rows[0]['time']}")
    print(f"Dataset end:   {rows[-1]['time']}")

    describe_distribution(rows)

    trades, risk_rejections = simulate_strategy_trades(rows)

    print()
    print("STRATEGY TRADE SAMPLE")
    print("=" * 72)
    print(f"Trades:            {len(trades)}")
    print(f"Risk rejections:   {risk_rejections}")

    if not trades:
        print("No trades.")
        return

    gross = sum(t["gross_pnl"] for t in trades)
    net = sum(t["net_pnl"] for t in trades)
    wins = sum(t["net_pnl"] > 0 for t in trades)

    print(f"Gross P/L:         {gross:.4f}")
    print(f"Net P/L after fee: {net:.4f}")
    print(f"Win rate:          {wins / len(trades) * 100:.2f}%")

    summarize_groups(trades, "regime")
    summarize_groups(trades, "side")
    summarize_groups(trades, "structure")
    summarize_groups(trades, "exit_reason")

    summarize_numeric(trades, "atr_pct")
    summarize_numeric(trades, "bb_width")
    summarize_numeric(trades, "rsi")
    summarize_numeric(trades, "relative_volume")
    summarize_numeric(trades, "ema200_distance")
    summarize_numeric(trades, "ema20_50_distance")


if __name__ == "__main__":
    main()
