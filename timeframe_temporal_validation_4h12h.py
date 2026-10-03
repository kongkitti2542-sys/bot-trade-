from collections import OrderedDict

from research_data_cache import load_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


# ============================================================
# RESEARCH ONLY
# Temporal validation of timeframes for THB 1,000 capital.
# Does NOT modify Core files.
# ============================================================

STARTING_CAPITAL_THB = 1000.0
REFERENCE_USDTHB = 33.58
STARTING_CAPITAL_USDT = STARTING_CAPITAL_THB / REFERENCE_USDTHB

FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0002
HOLD_HOURS = 12

# Existing research boundaries.
# Recent is NOT a clean final holdout because it was used
# by previous research work.
DISCOVERY_END = "2026-05-01T00:00:00+00:00"
VALIDATION_END = "2026-07-21T10:05:00+00:00"

TIMEFRAMES = OrderedDict([
    ("5m", 5),
    ("15m", 15),
    ("30m", 30),
    ("1h", 60),
    ("4h", 240),
])


def aggregate_candles(candles, minutes):
    if minutes == 5:
        return list(candles)

    bucket_seconds = minutes * 60
    result = []
    current_bucket = None
    current = None

    for candle in candles:
        ts = candle["time"]
        epoch = int(ts.timestamp())
        bucket_epoch = epoch - (epoch % bucket_seconds)

        if current_bucket != bucket_epoch:
            if current is not None:
                result.append(current)

            current_bucket = bucket_epoch
            current = {
                "time": ts.replace(second=0, microsecond=0),
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
        else:
            current["high"] = max(current["high"], candle["high"])
            current["low"] = min(current["low"], candle["low"])
            current["close"] = candle["close"]
            current["volume"] += candle["volume"]

    if current is not None:
        result.append(current)

    return result


def parse_time(value):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hold_bars(minutes):
    return (HOLD_HOURS * 60) // minutes


def apply_cost(entry, exit_price, size, side):
    entry_exec = (
        entry * (1 + SLIPPAGE_RATE)
        if side == "BUY"
        else entry * (1 - SLIPPAGE_RATE)
    )

    exit_exec = (
        exit_price * (1 - SLIPPAGE_RATE)
        if side == "BUY"
        else exit_price * (1 + SLIPPAGE_RATE)
    )

    if side == "BUY":
        gross = (exit_exec - entry_exec) * size
    else:
        gross = (entry_exec - exit_exec) * size

    entry_fee = entry_exec * size * FEE_RATE
    exit_fee = exit_exec * size * FEE_RATE

    fees = entry_fee + exit_fee

    slippage = (
        abs(entry_exec - entry) * size
        + abs(exit_exec - exit_price) * size
    )

    return gross - fees, gross, fees, slippage


def run_period(candles, timeframe_minutes, period_start, period_end):
    capital = STARTING_CAPITAL_USDT
    position = None
    trades = []

    feature_engine = IncrementalFeatures()
    max_hold = hold_bars(timeframe_minutes)

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        # Manage an existing position first.
        if position is not None:
            position["bars_held"] += 1

            stopped = False

            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "STOP_LOSS"
                    stopped = True
            else:
                if candle["high"] >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "STOP_LOSS"
                    stopped = True

            timed_out = (
                not stopped
                and position["bars_held"] >= max_hold
            )

            if stopped or timed_out:
                if timed_out:
                    exit_price = candle["close"]
                    exit_reason = "TIME_EXIT"

                net, gross, fees, slip = apply_cost(
                    position["entry_price"],
                    exit_price,
                    position["position_size"],
                    position["side"],
                )

                capital += net

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": candle_time,
                    "side": position["side"],
                    "net": net,
                    "gross": gross,
                    "fees": fees,
                    "slippage": slip,
                    "exit_reason": exit_reason,
                })

                position = None
                continue

            continue

        # Only open new positions inside this period.
        if candle_time < period_start or candle_time >= period_end:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision,
            features,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            continue

        position = {
            "side": decision["signal"],
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "bars_held": 0,
        }

    # Do not count an open position as realized performance.
    # The position may remain open across the period boundary.
    return summarize(trades)


def summarize(trades):
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] < 0]

    gross_profit = sum(t["net"] for t in wins)
    gross_loss = abs(sum(t["net"] for t in losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            len(wins) / len(trades) * 100
            if trades else 0.0
        ),
        "gross": sum(t["gross"] for t in trades),
        "fees": sum(t["fees"] for t in trades),
        "slippage": sum(t["slippage"] for t in trades),
        "net": sum(t["net"] for t in trades),
        "pf": pf,
        "stop": sum(
            1 for t in trades
            if t["exit_reason"] == "STOP_LOSS"
        ),
        "time": sum(
            1 for t in trades
            if t["exit_reason"] == "TIME_EXIT"
        ),
    }


def main():
    print("=" * 120)
    print("TIMEFRAME TEMPORAL VALIDATION — THB 1,000")
    print("=" * 120)

    candles_5m = load_candles()

    discovery_start = candles_5m[0]["time"]
    discovery_end = parse_time(DISCOVERY_END)
    validation_end = parse_time(VALIDATION_END)
    recent_end = candles_5m[-1]["time"]

    periods = [
        ("DISCOVERY", discovery_start, discovery_end),
        ("VALIDATION", discovery_end, validation_end),
        ("RECENT*", validation_end, recent_end),
    ]

    print(f"Source candles : {len(candles_5m):,}")
    print(f"Capital        : THB {STARTING_CAPITAL_THB:,.2f}")
    print(f"Capital USDT   : {STARTING_CAPITAL_USDT:.8f}")
    print(f"Fee            : {FEE_RATE * 100:.3f}% each side")
    print(f"Slippage       : {SLIPPAGE_RATE * 100:.3f}% each side")
    print(f"Hold horizon   : {HOLD_HOURS} hours")
    print()

    for tf, minutes in TIMEFRAMES.items():
        candles = aggregate_candles(candles_5m, minutes)

        print()
        print("=" * 120)
        print(f"TIMEFRAME: {tf} | {len(candles):,} candles | {hold_bars(minutes)} bars = {HOLD_HOURS}h")
        print("=" * 120)

        print(
            f"{'Period':<12}"
            f"{'Trades':>8}"
            f"{'Wins':>7}"
            f"{'Loss':>7}"
            f"{'WR':>8}"
            f"{'Gross':>12}"
            f"{'Fees':>11}"
            f"{'Slip':>11}"
            f"{'Net':>12}"
            f"{'PF':>8}"
            f"{'SL':>7}"
            f"{'Time':>7}"
        )
        print("-" * 120)

        for label, start, end in periods:
            result = run_period(
                candles,
                minutes,
                start,
                end,
            )

            pf = (
                f"{result['pf']:.3f}"
                if result["pf"] is not None
                else "N/A"
            )

            print(
                f"{label:<12}"
                f"{result['trades']:>8}"
                f"{result['wins']:>7}"
                f"{result['losses']:>7}"
                f"{result['win_rate']:>7.2f}%"
                f"{result['gross']:>12.3f}"
                f"{result['fees']:>11.3f}"
                f"{result['slippage']:>11.3f}"
                f"{result['net']:>12.3f}"
                f"{pf:>8}"
                f"{result['stop']:>7}"
                f"{result['time']:>7}"
            )

    print()
    print("=" * 120)
    print("IMPORTANT")
    print("=" * 120)
    print("* RECENT is not a clean final holdout.")
    print("* All results are research only.")
    print("* No Core files were modified.")
    print("* Net includes fee + slippage stress.")
    print("* No timeframe was selected using validation results.")
    print("* Positive results do not prove future profitability.")


if __name__ == "__main__":
    main()
