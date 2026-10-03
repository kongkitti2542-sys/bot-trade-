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

FIVE_MINUTES_PER_4H = 48
TIME_EXIT_BARS = 3
SESSION_BARS = 6


def aggregate_4h(candles):
    """
    Aggregate Binance 5m OPEN-time candles into complete UTC 4H candles.

    A complete 4H bucket contains exactly 48 x 5m candles.
    Partial buckets at the beginning/end are discarded.
    """
    buckets = {}

    for candle in candles:
        ts = candle["time"]

        bucket_hour = (ts.hour // 4) * 4
        bucket_start = ts.replace(
            hour=bucket_hour,
            minute=0,
            second=0,
            microsecond=0,
        )

        buckets.setdefault(bucket_start, []).append(candle)

    result = []

    for bucket_start in sorted(buckets):
        bucket = buckets[bucket_start]

        if len(bucket) != FIVE_MINUTES_PER_4H:
            continue

        bucket = sorted(bucket, key=lambda x: x["time"])

        expected_times = [
            bucket_start + timedelta(minutes=5 * i)
            for i in range(FIVE_MINUTES_PER_4H)
        ]

        actual_times = [c["time"] for c in bucket]

        if actual_times != expected_times:
            continue

        result.append(
            {
                "time": bucket_start,
                "open": bucket[0]["open"],
                "high": max(c["high"] for c in bucket),
                "low": min(c["low"] for c in bucket),
                "close": bucket[-1]["close"],
                "volume": sum(c["volume"] for c in bucket),
            }
        )

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

    net = gross - fees

    return net, gross, fees, slippage


def close_trade(position, candle, exit_price, exit_reason):
    net, gross, fees, slippage = apply_cost(
        entry=position["entry_price"],
        exit_price=exit_price,
        size=position["position_size"],
        side=position["side"],
    )

    return {
        "entry_time": position["entry_time"],
        "exit_time": candle["time"],
        "side": position["side"],
        "entry_price": position["entry_price"],
        "exit_price": exit_price,
        "position_size": position["position_size"],
        "gross_pnl": gross,
        "fees": fees,
        "slippage": slippage,
        "net_pnl": net,
        "exit_reason": exit_reason,
    }


def build_feature_rows(candles):
    """
    Run IncrementalFeatures continuously across the entire 4H history.
    This is intentionally outside the session loop.
    """
    feature_engine = IncrementalFeatures()
    rows = []

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        rows.append(
            {
                "index": index,
                "candle": candle,
                "features": features,
            }
        )

    return rows


def run_session(session_rows, starting_capital):
    capital = starting_capital
    position = None
    trades = []

    for row in session_rows:
        candle = row["candle"]
        features = row["features"]
        global_index = row["index"]

        # Features must have enough history for EMA200.
        if global_index < 200:
            continue

        # -----------------------------------------------------
        # Existing position
        # -----------------------------------------------------
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

            elif position["side"] == "SELL":
                if candle["high"] >= position["stop_loss"]:
                    trade = close_trade(
                        position,
                        candle,
                        position["stop_loss"],
                        "STOP_LOSS",
                    )

            if (
                trade is None
                and position["bars_held"] >= TIME_EXIT_BARS
            ):
                trade = close_trade(
                    position,
                    candle,
                    candle["close"],
                    "TIME_EXIT",
                )

            if trade is not None:
                capital += trade["net_pnl"]
                trades.append(trade)
                position = None

            continue

        # -----------------------------------------------------
        # New signal
        # -----------------------------------------------------
        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        # RESEARCH ONLY: V2-A BUY-only hypothesis.
        # Core strategy.py is intentionally unchanged.
        if decision["signal"] == "SELL":
            continue

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
            continue

        position = {
            "side": decision["signal"],
            "entry_time": candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "bars_held": 0,
        }

    # ---------------------------------------------------------
    # Session boundary: force close
    # ---------------------------------------------------------
    if position is not None:
        candle = session_rows[-1]["candle"]

        trade = close_trade(
            position,
            candle,
            candle["close"],
            "SESSION_END",
        )

        capital += trade["net_pnl"]
        trades.append(trade)

    return capital, trades


def summarize_trades(trades):
    gross = sum(t["gross_pnl"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    slippage = sum(t["slippage"] for t in trades)
    net = sum(t["net_pnl"] for t in trades)

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]

    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))

    if gross_loss == 0:
        pf = float("inf") if gross_profit > 0 else 0.0
    else:
        pf = gross_profit / gross_loss

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            len(wins) / len(trades) * 100
            if trades
            else 0.0
        ),
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "pf": pf,
    }


def main():
    print("=" * 72)
    print("4H / 12H TIME EXIT — 24H SESSION RESEARCH V3")
    print("=" * 72)

    source_candles = load_candles()
    candles = aggregate_4h(source_candles)

    print(f"Source 5m candles : {len(source_candles):,}")
    print(f"Complete 4H bars  : {len(candles):,}")

    if not candles:
        raise RuntimeError("NO_COMPLETE_4H_CANDLES")

    print(
        f"4H range          : "
        f"{candles[0]['time']} -> {candles[-1]['time']}"
    )

    print(f"Capital THB       : {STARTING_CAPITAL_THB:.2f}")
    print(f"Capital USDT      : {STARTING_CAPITAL_USDT:.8f}")
    print(f"Fee / side        : {FEE_RATE * 100:.3f}%")
    print(f"Slippage / side   : {SLIPPAGE_RATE * 100:.3f}%")
    print(f"Time Exit         : {TIME_EXIT_BARS * 4}H")
    print(f"Session            : {SESSION_BARS * 4}H")
    print()

    # Continuous feature history across ALL 4H candles.
    feature_rows = build_feature_rows(candles)

    # Only complete 24H sessions.
    total_sessions = len(feature_rows) // SESSION_BARS

    print(f"Complete sessions  : {total_sessions:,}")
    print()

    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_gross = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    total_net = 0.0
    capital = STARTING_CAPITAL_USDT
    peak_capital = capital
    max_drawdown = 0.0

    session_results = []
    all_trades = []

    for session_number in range(total_sessions):
        start = session_number * SESSION_BARS
        end = start + SESSION_BARS

        session_rows = feature_rows[start:end]

        session_capital, trades = run_session(session_rows, capital)

        summary = summarize_trades(trades)
        all_trades.extend(trades)

        total_trades += summary["trades"]
        total_wins += summary["wins"]
        total_losses += summary["losses"]
        total_gross += summary["gross"]
        total_fees += summary["fees"]
        total_slippage += summary["slippage"]
        total_net += summary["net"]

        capital = session_capital

        if capital > peak_capital:
            peak_capital = capital

        drawdown = (
            (peak_capital - capital) / peak_capital * 100
            if peak_capital > 0
            else 0.0
        )

        if drawdown > max_drawdown:
            max_drawdown = drawdown

        session_results.append(
            {
                "session": session_number + 1,
                "start": session_rows[0]["candle"]["time"],
                "end": session_rows[-1]["candle"]["time"],
                "capital": session_capital,
                **summary,
            }
        )

    print("-" * 72)
    print("SESSION SUMMARY")
    print("-" * 72)

    traded_sessions = [
        x for x in session_results
        if x["trades"] > 0
    ]

    print(f"Sessions evaluated : {len(session_results):,}")
    print(f"Sessions traded   : {len(traded_sessions):,}")
    print(f"Total trades      : {total_trades:,}")
    print(f"Wins              : {total_wins:,}")
    print(f"Losses            : {total_losses:,}")

    if total_trades:
        print(
            f"Win rate          : "
            f"{total_wins / total_trades * 100:.2f}%"
        )

    print(f"Gross P/L         : {total_gross:+.8f} USDT")
    print(f"Fees              : {total_fees:.8f} USDT")
    print(f"Slippage          : {total_slippage:.8f} USDT")
    print(f"Net P/L           : {total_net:+.8f} USDT")

    if total_losses:
        pf = (
            sum(
                x["net_pnl"]
                for x in []
            )
        )

    net_positive = sum(
        t["net_pnl"]
        for x in session_results
        for t in []
    )

    # Profit Factor from the exact trades already executed
    # in the compounding run. Do not rerun sessions with reset capital.
    profit_sum = sum(
        t["net_pnl"] for t in all_trades
        if t["net_pnl"] > 0
    )
    loss_sum = abs(
        sum(
            t["net_pnl"] for t in all_trades
            if t["net_pnl"] <= 0
        )
    )

    pf = (
        profit_sum / loss_sum
        if loss_sum > 0
        else 0.0
    )

    print(f"Profit Factor     : {pf:.3f}")
    print(f"Final Capital     : {capital:.8f} USDT")
    print(f"Final Capital THB : {capital * REFERENCE_USDTHB:.2f} THB")
    print(f"Total Return      : {(capital / STARTING_CAPITAL_USDT - 1) * 100:+.2f}%")
    print(f"Max Drawdown      : {max_drawdown:.2f}%")

    print()
    print("Exit breakdown:")

    stop_count = sum(
        1 for t in all_trades
        if t["exit_reason"] == "STOP_LOSS"
    )

    time_count = sum(
        1 for t in all_trades
        if t["exit_reason"] == "TIME_EXIT"
    )

    session_end_count = sum(
        1 for t in all_trades
        if t["exit_reason"] == "SESSION_END"
    )

    print(f"  STOP_LOSS       : {stop_count}")
    print(f"  TIME_EXIT       : {time_count}")
    print(f"  SESSION_END     : {session_end_count}")

    print()
    print("First 10 traded sessions:")

    shown = 0

    for result in session_results:
        if result["trades"] == 0:
            continue

        print(
            f"Session {result['session']:03d} | "
            f"{result['start']} -> {result['end']} | "
            f"Trades {result['trades']:2d} | "
            f"WR {result['win_rate']:5.1f}% | "
            f"Net {result['net']:+.6f} USDT"
        )

        shown += 1

        if shown >= 10:
            break


if __name__ == "__main__":
    main()
