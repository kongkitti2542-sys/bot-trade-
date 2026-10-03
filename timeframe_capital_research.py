from datetime import timedelta
from collections import OrderedDict

from research_data_cache import load_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


# ============================================================
# RESEARCH ONLY
# Compare BTCUSDT timeframes for THB 1,000 starting capital.
# Does NOT modify Core files.
# ============================================================

STARTING_CAPITAL_THB = 1000.0
REFERENCE_USDTHB = 33.58
STARTING_CAPITAL_USDT = STARTING_CAPITAL_THB / REFERENCE_USDTHB

FEE_RATE = 0.0005          # Futures taker, each side
SLIPPAGE_RATE = 0.0002     # 0.02% each side
HOLD_HOURS = 20

TIMEFRAMES = OrderedDict([
    ("5m", 5),
    ("15m", 15),
    ("30m", 30),
    ("1h", 60),
    ("4h", 240),
])


def aggregate_candles(candles, minutes):
    """Aggregate 5m closed candles into UTC-aligned timeframe candles."""
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
                "time": ts.replace(
                    second=0,
                    microsecond=0,
                ),
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


def hold_bars(minutes):
    total_minutes = HOLD_HOURS * 60
    return total_minutes // minutes


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


def run_backtest(candles, timeframe_minutes):
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

        # ----------------------------------------------------
        # Manage existing position using current closed candle
        # ----------------------------------------------------
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

            if not stopped and position["bars_held"] >= max_hold:
                exit_price = candle["close"]
                exit_reason = "TIME_EXIT"

            if stopped or position["bars_held"] >= max_hold:
                net_pnl, gross_pnl, fees, slippage = apply_cost(
                    position["entry_price"],
                    exit_price,
                    position["position_size"],
                    position["side"],
                )

                capital += net_pnl

                trades.append({
                    "side": position["side"],
                    "entry_time": position["entry_time"],
                    "exit_time": candle_time,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "position_size": position["position_size"],
                    "net_pnl": net_pnl,
                    "gross_pnl": gross_pnl,
                    "fees": fees,
                    "slippage": slippage,
                    "exit_reason": exit_reason,
                    "regime": position["regime"],
                    "score": position["score"],
                })

                position = None
                continue

            continue

        # ----------------------------------------------------
        # New entry
        # ----------------------------------------------------
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
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
        }

    # Dataset-end position is not counted as realized result.
    dataset_end = 0.0

    if position is not None:
        last = candles[-1]

        if position["side"] == "BUY":
            raw = (last["close"] - position["entry_price"]) * position["position_size"]
        else:
            raw = (position["entry_price"] - last["close"]) * position["position_size"]

        dataset_end = raw

    realized = trades

    wins = [t for t in realized if t["net_pnl"] > 0]
    losses = [t for t in realized if t["net_pnl"] < 0]

    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    total_fees = sum(t["fees"] for t in realized)
    total_slippage = sum(t["slippage"] for t in realized)
    gross_before_cost = sum(t["gross_pnl"] for t in realized)
    net_pnl = sum(t["net_pnl"] for t in realized)

    return {
        "capital": STARTING_CAPITAL_USDT + net_pnl,
        "net_pnl": net_pnl,
        "gross": gross_before_cost,
        "fees": total_fees,
        "slippage": total_slippage,
        "trades": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            len(wins) / len(realized) * 100
            if realized else 0.0
        ),
        "pf": profit_factor,
        "stop": sum(
            1 for t in realized
            if t["exit_reason"] == "STOP_LOSS"
        ),
        "time": sum(
            1 for t in realized
            if t["exit_reason"] == "TIME_EXIT"
        ),
        "dataset_end": dataset_end,
    }


def main():
    print("=" * 110)
    print("TIMEFRAME × THB 1,000 PROFITABILITY RESEARCH")
    print("=" * 110)

    candles_5m = load_candles()

    print(f"Source candles : {len(candles_5m):,}")
    print(f"Capital        : THB {STARTING_CAPITAL_THB:,.2f}")
    print(f"Reference FX   : {REFERENCE_USDTHB:.2f} THB/USD")
    print(f"Capital USDT   : {STARTING_CAPITAL_USDT:.8f}")
    print(f"Fee            : {FEE_RATE * 100:.3f}% each side")
    print(f"Slippage       : {SLIPPAGE_RATE * 100:.3f}% each side")
    print(f"Hold horizon   : {HOLD_HOURS} hours")
    print()

    print(
        f"{'TF':<6}"
        f"{'Bars':>7}"
        f"{'Candles':>10}"
        f"{'Trades':>8}"
        f"{'Wins':>7}"
        f"{'Loss':>7}"
        f"{'WR':>8}"
        f"{'Gross':>12}"
        f"{'Fees':>11}"
        f"{'Slip':>11}"
        f"{'Net':>12}"
        f"{'PF':>8}"
        f"{'End':>12}"
    )
    print("-" * 110)

    for label, minutes in TIMEFRAMES.items():
        candles = aggregate_candles(candles_5m, minutes)

        if len(candles) < 300:
            print(f"{label:<6} insufficient candles: {len(candles)}")
            continue

        result = run_backtest(candles, minutes)

        pf = (
            f"{result['pf']:.3f}"
            if result["pf"] is not None
            else "N/A"
        )

        print(
            f"{label:<6}"
            f"{hold_bars(minutes):>7}"
            f"{len(candles):>10,}"
            f"{result['trades']:>8}"
            f"{result['wins']:>7}"
            f"{result['losses']:>7}"
            f"{result['win_rate']:>7.2f}%"
            f"{result['gross']:>12.3f}"
            f"{result['fees']:>11.3f}"
            f"{result['slippage']:>11.3f}"
            f"{result['net_pnl']:>12.3f}"
            f"{pf:>8}"
            f"{result['capital']:>12.3f}"
        )

    print("-" * 110)
    print()
    print("Research only.")
    print("No Core files were modified.")
    print("Net P/L includes fee + slippage stress.")
    print("Starting capital is THB 1,000 converted to USDT for the existing risk model.")
    print("Do not interpret this run as proof of future profitability.")


if __name__ == "__main__":
    main()
