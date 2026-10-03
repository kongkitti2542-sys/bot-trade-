from datetime import timedelta

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
TIME_EXIT_BARS = 3          # 4H x 3 = 12H
SESSION_BARS = 6            # 4H x 6 = 24H


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


def close_trade(position, candle, exit_price, exit_reason):
    net, gross, fees, slippage = apply_cost(
        position["entry_price"],
        exit_price,
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


def run_session(session_candles):
    capital = STARTING_CAPITAL_USDT
    position = None
    trades = []

    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(session_candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        # Existing position is managed first.
        if position is not None:
            position["bars_held"] += 1
            trade = None

            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    trade = close_trade(
                        position,
                        candle,
                        position["stop_loss"],
                        "STOP_LOSS",
                    )
            else:
                if candle["high"] >= position["stop_loss"]:
                    trade = close_trade(
                        position,
                        candle,
                        position["stop_loss"],
                        "STOP_LOSS",
                    )

            if trade is None and position["bars_held"] >= TIME_EXIT_BARS:
                trade = close_trade(
                    position,
                    candle,
                    candle["close"],
                    "TIME_EXIT",
                )

            if trade is not None:
                capital += trade["net"]
                trades.append(trade)
                position = None

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
            "entry_time": candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "bars_held": 0,
        }

    # Session boundary:
    # Any remaining position is forcibly closed at the final session candle.
    if position is not None and session_candles:
        candle = session_candles[-1]

        trade = close_trade(
            position,
            candle,
            candle["close"],
            "SESSION_END",
        )

        capital += trade["net"]
        trades.append(trade)

    return capital, trades


def summarize_session(session_number, session_start, session_end, capital, trades):
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] < 0]

    net = sum(t["net"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    slippage = sum(t["slippage"] for t in trades)

    gross_profit = sum(t["net"] for t in wins)
    gross_loss = abs(sum(t["net"] for t in losses))

    pf = gross_profit / gross_loss if gross_loss > 0 else None

    return {
        "session": session_number,
        "start": session_start,
        "end": session_end,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "net": net,
        "ending_capital": capital,
        "fees": fees,
        "slippage": slippage,
        "pf": pf,
        "stop": sum(t["exit_reason"] == "STOP_LOSS" for t in trades),
        "time": sum(t["exit_reason"] == "TIME_EXIT" for t in trades),
        "session_end": sum(t["exit_reason"] == "SESSION_END" for t in trades),
    }


def main():
    candles_5m = load_candles()
    candles = aggregate_4h(candles_5m)

    # Each session contains exactly 6 x 4H candles.
    # Capital is reset to the same starting capital for each session.
    session_size = SESSION_BARS

    results = []

    for start_index in range(0, len(candles) - session_size + 1, session_size):
        session_candles = candles[
            start_index:start_index + session_size
        ]

        if len(session_candles) != session_size:
            continue

        capital, trades = run_session(session_candles)

        result = summarize_session(
            len(results) + 1,
            session_candles[0]["time"],
            session_candles[-1]["time"],
            capital,
            trades,
        )

        results.append(result)

    profitable = [r for r in results if r["net"] > 0]
    losing = [r for r in results if r["net"] < 0]

    total_net = sum(r["net"] for r in results)
    total_fees = sum(r["fees"] for r in results)
    total_slippage = sum(r["slippage"] for r in results)
    total_trades = sum(r["trades"] for r in results)

    session_pf_profit = sum(r["net"] for r in profitable)
    session_pf_loss = abs(sum(r["net"] for r in losing))
    session_pf = (
        session_pf_profit / session_pf_loss
        if session_pf_loss > 0
        else None
    )

    print("=" * 120)
    print("4H / 12H — TRUE 24H SESSION RESEARCH V2")
    print("=" * 120)
    print(f"Source 5m candles : {len(candles_5m):,}")
    print(f"4H candles        : {len(candles):,}")
    print(f"Capital / session : THB {STARTING_CAPITAL_THB:,.2f}")
    print(f"Capital USDT      : {STARTING_CAPITAL_USDT:.8f}")
    print(f"Fee               : {FEE_RATE * 100:.3f}% each side")
    print(f"Slippage          : {SLIPPAGE_RATE * 100:.3f}% each side")
    print("Time Exit         : 12 hours")
    print("Session           : 24 hours")
    print()
    print(f"Sessions          : {len(results)}")
    print(f"Profitable        : {len(profitable)}")
    print(f"Losing            : {len(losing)}")
    print(
        f"Session Win Rate  : "
        f"{len(profitable) / len(results) * 100 if results else 0:.2f}%"
    )
    print(f"Total trades      : {total_trades}")
    print(f"Total Net P/L     : {total_net:.6f} USDT")
    print(f"Total Fees        : {total_fees:.6f} USDT")
    print(f"Total Slippage    : {total_slippage:.6f} USDT")
    print(
        f"Session PF        : "
        f"{session_pf:.3f}" if session_pf is not None
        else "Session PF        : N/A"
    )
    print()
    print(
        f"{'Session':>7} "
        f"{'Start':<20} "
        f"{'End':<20} "
        f"{'Trades':>7} "
        f"{'Net':>10} "
        f"{'PF':>7} "
        f"{'SL':>5} "
        f"{'Time':>5} "
        f"{'End':>5}"
    )
    print("-" * 120)

    for r in results:
        pf = f"{r['pf']:.3f}" if r["pf"] is not None else "N/A"

        print(
            f"{r['session']:>7} "
            f"{str(r['start']):<20} "
            f"{str(r['end']):<20} "
            f"{r['trades']:>7} "
            f"{r['net']:>10.4f} "
            f"{pf:>7} "
            f"{r['stop']:>5} "
            f"{r['time']:>5} "
            f"{r['session_end']:>5}"
        )

    print("=" * 120)
    print("IMPORTANT")
    print("=" * 120)
    print("Each session is exactly 24 hours / 6 x 4H candles.")
    print("No position is allowed to cross a session boundary.")
    print("Any remaining position is closed at SESSION_END.")
    print("Capital is reset to THB 1,000 for every session.")
    print("This is research only. Core files are not modified.")
    print("=" * 120)


if __name__ == "__main__":
    main()
