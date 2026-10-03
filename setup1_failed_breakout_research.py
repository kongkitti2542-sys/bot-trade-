"""Research-only: Setup 1 Failed Breakout / Fakeout Reversal.

Signal is evaluated at candle close; entry is next candle open.
This file does not modify Core strategy/risk/execution/database files.
"""
import numpy as np

from backtest_data_100k import get_historical_candles_100k, validate_candles

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"
STARTING_CAPITAL_USDT = 44.669446

LOOKBACK = 30
ATR_N = 14
RELVOL_N = 20
RELVOL_MIN = 1.5
WICK_MIN = 0.5
SL_ATR = 0.2
MAX_HOLD_BARS = 48
FEE_RATE = 0.0005
SLIPPAGE_RATES = {"0.00%": 0.0, "0.02%": 0.0002, "0.05%": 0.0005}


def _ema(values, span):
    out = np.full(len(values), np.nan, dtype=float)
    if not values:
        return out
    alpha = 2.0 / (span + 1.0)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _atr(high, low, close, period):
    out = np.full(len(close), np.nan, dtype=float)
    if len(close) == 0:
        return out
    tr = np.empty(len(close), dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    alpha = 1.0 / period
    out[0] = tr[0]
    for i in range(1, len(close)):
        out[i] = alpha * tr[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rolling_mean_previous(values, period):
    out = np.full(len(values), np.nan, dtype=float)
    total = 0.0
    for i, value in enumerate(values):
        if i >= period:
            total += values[i - period]
            if i - period - 1 >= 0:
                total -= values[i - period - 1]
        if i >= period:
            # This branch is intentionally replaced below by direct sum
            # to keep the "previous period" definition unambiguous.
            pass
    for i in range(period, len(values)):
        out[i] = np.mean(values[i - period:i])
    return out


def _rolling_max_previous(values, period):
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(period, len(values)):
        out[i] = np.max(values[i - period:i])
    return out


def _rolling_min_previous(values, period):
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(period, len(values)):
        out[i] = np.min(values[i - period:i])
    return out


def prepare(candles):
    times = [c["time"] for c in candles]
    open_ = np.asarray([float(c["open"]) for c in candles], dtype=float)
    high = np.asarray([float(c["high"]) for c in candles], dtype=float)
    low = np.asarray([float(c["low"]) for c in candles], dtype=float)
    close = np.asarray([float(c["close"]) for c in candles], dtype=float)
    volume = np.asarray([float(c["volume"]) for c in candles], dtype=float)

    atr = _atr(high, low, close, ATR_N)
    ema20 = _ema(close.tolist(), 20)
    ema50 = _ema(close.tolist(), 50)
    vol_mean_prev = _rolling_mean_previous(volume, RELVOL_N)
    relvol = volume / vol_mean_prev
    range_high = _rolling_max_previous(high, LOOKBACK)
    range_low = _rolling_min_previous(low, LOOKBACK)

    candle_range = high - low
    body_high = np.maximum(open_, close)
    body_low = np.minimum(open_, close)
    upper_wick_pct = np.divide(
        high - body_high,
        candle_range,
        out=np.full(len(close), np.nan),
        where=candle_range != 0,
    )
    lower_wick_pct = np.divide(
        body_low - low,
        candle_range,
        out=np.full(len(close), np.nan),
        where=candle_range != 0,
    )

    regime_proxy = np.abs(ema20 - ema50) < atr

    short = (
        (high > range_high)
        & (close < range_high)
        & (upper_wick_pct > WICK_MIN)
        & (relvol > RELVOL_MIN)
        & regime_proxy
    )
    long_ = (
        (low < range_low)
        & (close > range_low)
        & (lower_wick_pct > WICK_MIN)
        & regime_proxy
        & (relvol > RELVOL_MIN)
    )

    signal = np.where(short & ~long_, -1, np.where(long_ & ~short, 1, 0))
    return {
        "time": times,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "atr": atr,
        "range_high": range_high,
        "range_low": range_low,
        "signal": signal,
    }


def _ts(value):
    # Dataset timestamps are ISO-8601 UTC strings. Lexical ordering is safe.
    return str(value)


def backtest(d, boundary):
    times = d["time"]
    boundary_ts = boundary
    trades = []
    i = 0

    while i < len(times) - 1:
        signal_time = _ts(times[i])
        if signal_time < boundary_ts or int(d["signal"][i]) == 0:
            i += 1
            continue

        side = int(d["signal"][i])
        entry = float(d["open"][i + 1])
        atr = float(d["atr"][i])

        if not np.isfinite(atr):
            i += 1
            continue

        if side == -1:
            stop = float(d["high"][i]) + SL_ATR * atr
        else:
            stop = float(d["low"][i]) - SL_ATR * atr

        if (side == -1 and stop <= entry) or (side == 1 and stop >= entry):
            i += 1
            continue

        range_high = float(d["range_high"][i])
        range_low = float(d["range_low"][i])
        target = (range_high + range_low) / 2.0

        if (side == 1 and target <= entry) or (side == -1 and target >= entry):
            i += 1
            continue

        end = min(i + MAX_HOLD_BARS, len(times) - 1)
        exit_price = None
        exit_reason = "TIME_EXIT"
        exit_idx = end

        for j in range(i + 1, end + 1):
            high = float(d["high"][j])
            low = float(d["low"][j])

            if side == 1:
                if low <= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    exit_idx = j
                    break
                if high >= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_idx = j
                    break
            else:
                if high >= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    exit_idx = j
                    break
                if low <= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_idx = j
                    break

        if exit_price is None:
            exit_price = float(d["close"][end])

        risk = abs(entry - stop)
        gross_return = side * (exit_price - entry) / entry

        trades.append({
            "signal_idx": i,
            "entry_idx": i + 1,
            "exit_idx": exit_idx,
            "signal_time": times[i],
            "entry_time": times[i + 1],
            "exit_time": times[exit_idx],
            "side": "BUY" if side == 1 else "SELL",
            "entry_price": entry,
            "exit_price": float(exit_price),
            "stop_loss": stop,
            "take_profit": target,
            "risk_pct": risk / entry,
            "bars_held": exit_idx - (i + 1),
            "gross_return": gross_return,
            "exit_reason": exit_reason,
        })

        i = exit_idx + 1

    return trades


def apply_costs(trades, slippage_rate):
    if not trades:
        return 0.0, 0.0, 0.0

    net_return = 0.0
    fee_return = 0.0
    slippage_return = 0.0

    for row in trades:
        side = 1 if row["side"] == "BUY" else -1
        entry = row["entry_price"]
        exit_price = row["exit_price"]

        entry_exec = entry * (1 + side * slippage_rate)
        exit_exec = exit_price * (1 - side * slippage_rate)

        gross_after_slip = side * (exit_exec - entry_exec) / entry_exec
        fees = 2 * FEE_RATE

        net_return += gross_after_slip - fees
        fee_return += fees
        slippage_return += (
            abs(entry_exec - entry) / entry
            + abs(exit_exec - exit_price) / exit_price
        )

    return net_return, fee_return, slippage_return


def stats(trades):
    if not trades:
        return {"n": 0, "wins": 0, "losses": 0, "gross": 0.0, "pf": None}

    wins = [t["gross_return"] for t in trades if t["gross_return"] > 0]
    losses = [t["gross_return"] for t in trades if t["gross_return"] < 0]
    gross = sum(t["gross_return"] for t in trades)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "n": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross": float(gross),
        "pf": float(gross_profit / gross_loss) if gross_loss > 0 else None,
    }


def print_stats(name, trades):
    s = stats(trades)
    pf = "N/A" if s["pf"] is None else f"{s['pf']:.4f}"
    print(
        f"{name:<18} N={s['n']:>4} W={s['wins']:>4} L={s['losses']:>4} "
        f"Gross={s['gross'] * 100:+.4f}% PF={pf}"
    )


def run(candles):
    valid, reason = validate_candles(candles)

    print("=" * 100)
    print("SETUP 1 โ€” FAILED BREAKOUT / FAKEOUT REVERSAL")
    print("RESEARCH ONLY โ€” NO CORE FILES MODIFIED")
    print("=" * 100)
    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {valid}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY}")
    print(f"Starting Pot:   ${STARTING_CAPITAL_USDT:.4f}")
    print(f"Lookback:       {LOOKBACK} bars")
    print(f"Max Hold:       {MAX_HOLD_BARS} bars / 4h")

    if not valid:
        raise RuntimeError(f"Dataset validation failed: {reason}")

    data = prepare(candles)
    trades = backtest(data, OOS_BOUNDARY)

    if not trades:
        print("No trades.")
        return

    split_idx = len(trades) // 2
    first_half = trades[:split_idx]
    second_half = trades[split_idx:]

    print()
    print("=" * 100)
    print("RESULT")
    print("=" * 100)
    print_stats("ALL OOS", trades)
    print_stats("FIRST HALF", first_half)
    print_stats("SECOND HALF", second_half)
    print_stats("LONG", [t for t in trades if t["side"] == "BUY"])
    print_stats("SHORT", [t for t in trades if t["side"] == "SELL"])

    exit_counts = {}
    for t in trades:
        exit_counts[t["exit_reason"]] = exit_counts.get(t["exit_reason"], 0) + 1
    print("Exit reasons:", exit_counts)
    print(f"Average bars held: {np.mean([t['bars_held'] for t in trades]):.2f}")

    print()
    print("=" * 100)
    print("NET COST GATE")
    print("=" * 100)

    for name, slip in SLIPPAGE_RATES.items():
        net, fees, slippage = apply_costs(trades, slip)
        final_pot = STARTING_CAPITAL_USDT * (1 + net)
        print(
            f"Slippage {name:<6} | Final Pot ${final_pot:>10.4f} | "
            f"Net Return {net * 100:+.4f}% | Fees(Return) {fees * 100:+.4f}% | "
            f"Slippage(Return) {slippage * 100:+.4f}%"
        )

    print()
    print("=" * 100)
    print("RESEARCH DECISION")
    print("=" * 100)

    net_002, _, _ = apply_costs(trades, 0.0002)
    second_stats = stats(second_half)

    if second_stats["gross"] > 0 and net_002 > 0:
        print("Candidate survives initial chronological/cost screen.")
    else:
        print("Candidate fails initial chronological/cost screen โ€” KILL.")

    print("=" * 100)


if __name__ == "__main__":
    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )
    run(candles)
