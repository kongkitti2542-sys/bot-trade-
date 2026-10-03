from datetime import timedelta
from collections import defaultdict

from research_data_cache import load_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

STARTING_CAPITAL_THB = 1000.0
REFERENCE_USDTHB = 33.58
STARTING_CAPITAL_USDT = STARTING_CAPITAL_THB / REFERENCE_USDTHB

FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0002

TIMEFRAME_MINUTES = 240
MAX_HOLD_BARS = 3          # 4H x 3 = 12H
SESSION_HOURS = 24
SESSION_SECONDS = SESSION_HOURS * 3600


def aggregate_4h(candles):
    result = []
    bucket_seconds = TIMEFRAME_MINUTES * 60
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


def apply_cost(entry, exit_price, size, side):
    if side == "BUY":
        entry_exec = entry * (1 + SLIPPAGE_RATE)
        exit_exec = exit_price * (1 - SLIPPAGE_RATE)
        gross = (exit_exec - entry_exec) * size
    else:
        entry_exec = entry * (1 - SLIPPAGE_RATE)
        exit_exec = exit_price * (1 + SLIPPAGE_RATE)
        gross = (entry_exec - exit_exec) * size

    entry_fee = entry_exec * size * FEE_RATE
    exit_fee = exit_exec * size * FEE_RATE
    fees = entry_fee + exit_fee

    slippage = (
        abs(entry_exec - entry) * size
        + abs(exit_exec - exit_price) * size
    )

    return gross - fees, gross, fees, slippage


def close_position(position, candle, exit_reason):
    net, gross, fees, slippage = apply_cost(
        position["entry_price"],
        candle["close"] if exit_reason == "TIME_EXIT"
        else position["stop_loss"],
        position["position_size"],
        position["side"],
    )

    return {
        "entry_time": position["entry_time"],
        "exit_time": candle["time"],
        "side": position["side"],
        "net": net,
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "exit_reason": exit_reason,
    }


def run():
    candles_5m = load_candles()
    candles = aggregate_4h(candles_5m)

    feature_engine = IncrementalFeatures()

    trades = []
    sessions = defaultdict(lambda: {
        "trades": 0,
        "net": 0.0,
        "fees": 0.0,
        "slippage": 0.0,
    })

    position = None

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        # Existing position is always managed first.
        if position is not None:
            position["bars_held"] += 1

            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    trade = close_position(
                        position, candle, "STOP_LOSS"
                    )
                    position = None
                else:
                    trade = None
            else:
                if candle["high"] >= position["stop_loss"]:
                    trade = close_position(
                        position, candle, "STOP_LOSS"
                    )
                    position = None
                else:
                    trade = None

            if position is not None and position["bars_held"] >= MAX_HOLD_BARS:
                trade = close_position(
                    position, candle, "TIME_EXIT"
                )
                position = None

            if trade is not None:
                trades.append(trade)
                session_key = trade["entry_time"].replace(
                    minute=0, second=0, microsecond=0
                )
                session_epoch = int(session_key.timestamp())
                session_start = (
                    session_epoch // SESSION_SECONDS
                ) * SESSION_SECONDS

                from datetime import datetime, timezone
                session_dt = datetime.fromtimestamp(
                    session_start, tz=timezone.utc
                )

                sessions[session_dt]["trades"] += 1
                sessions[session_dt]["net"] += trade["net"]
                sessions[session_dt]["fees"] += trade["fees"]
                sessions[session_dt]["slippage"] += trade["slippage"]

            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision,
            features,
            capital=STARTING_CAPITAL_USDT,
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

    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] < 0]

    gross_profit = sum(t["net"] for t in wins)
    gross_loss = abs(sum(t["net"] for t in losses))
    pf = gross_profit / gross_loss if gross_loss else None

    print("=" * 100)
    print("4H / 12H — 24H SESSION RESEARCH")
    print("=" * 100)
    print(f"Source 5m candles : {len(candles_5m):,}")
    print(f"4H candles        : {len(candles):,}")
    print(f"Capital THB       : {STARTING_CAPITAL_THB:.2f}")
    print(f"Capital USDT      : {STARTING_CAPITAL_USDT:.8f}")
    print(f"Fee               : {FEE_RATE * 100:.3f}% each side")
    print(f"Slippage          : {SLIPPAGE_RATE * 100:.3f}% each side")
    print(f"Time Exit         : {MAX_HOLD_BARS * 4} hours")
    print(f"Session           : {SESSION_HOURS} hours")
    print()
    print(f"Trades            : {len(trades)}")
    print(f"Wins              : {len(wins)}")
    print(f"Losses            : {len(losses)}")
    print(f"Win Rate          : {(len(wins)/len(trades)*100) if trades else 0:.2f}%")
    print(f"Net P/L           : {sum(t['net'] for t in trades):.6f} USDT")
    print(f"Fees              : {sum(t['fees'] for t in trades):.6f} USDT")
    print(f"Slippage          : {sum(t['slippage'] for t in trades):.6f} USDT")
    print(f"PF                : {pf:.3f}" if pf is not None else "PF                : N/A")
    print(f"STOP LOSS         : {sum(t['exit_reason']=='STOP_LOSS' for t in trades)}")
    print(f"TIME EXIT         : {sum(t['exit_reason']=='TIME_EXIT' for t in trades)}")
    print()
    print("NOTE: This is a research session model only.")
    print("It does not modify Core and does not represent live execution.")
    print("=" * 100)


if __name__ == "__main__":
    run()
