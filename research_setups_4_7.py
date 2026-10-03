"""
RESEARCH ONLY — SETUPS 4-7

4  High Volatility Exhaustion
5  Consolidation Breakout Retest
6  Range Outer-Band Reversion
7  Relative Volume Impulse Continuation

No Core files are modified.
Signal at candle close -> entry at next candle open.
One position at a time.
Same-bar SL/TP collision -> SL first.
"""

import numpy as np

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"
STARTING_CAPITAL_USDT = 44.669446

FEE_RATE = 0.0005
SLIPPAGE_RATES = {
    "0.00%": 0.0,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}

ATR_N = 14
RELVOL_N = 20
MAX_HOLD = 48


def atr(high, low, close, period=14):
    n = len(close)
    out = np.full(n, np.nan)

    if n == 0:
        return out

    prev = np.empty(n)
    prev[0] = close[0]
    prev[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - prev),
            np.abs(low - prev),
        ),
    )

    if n < period:
        return out

    out[period - 1] = np.mean(tr[:period])

    for i in range(period, n):
        out[i] = (
            out[i - 1] * (period - 1) + tr[i]
        ) / period

    return out


def prepare(candles):
    o = np.array([float(x["open"]) for x in candles])
    h = np.array([float(x["high"]) for x in candles])
    l = np.array([float(x["low"]) for x in candles])
    c = np.array([float(x["close"]) for x in candles])
    v = np.array([float(x["volume"]) for x in candles])

    a = atr(h, l, c, ATR_N)

    relvol = np.full(len(c), np.nan)
    for i in range(RELVOL_N, len(c)):
        base = np.mean(v[i - RELVOL_N:i])
        if base > 0:
            relvol[i] = v[i] / base

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "atr": a,
        "relvol": relvol,
    }


# ------------------------------------------------------------
# SETUP 4
# HIGH VOLATILITY EXHAUSTION
# ------------------------------------------------------------

def signal_setup4(d, i):
    a = d["atr"][i]
    if not np.isfinite(a) or a <= 0:
        return 0

    candle_range = d["high"][i] - d["low"][i]
    if candle_range <= 0:
        return 0

    # Abnormally large candle relative to ATR.
    if candle_range < 2.0 * a:
        return 0

    body_high = max(d["open"][i], d["close"][i])
    body_low = min(d["open"][i], d["close"][i])

    upper_wick = d["high"][i] - body_high
    lower_wick = body_low - d["low"][i]

    # Exhaustion reversal:
    # large expansion + rejection wick + close away from extreme.
    if (
        d["close"][i] < d["open"][i]
        and upper_wick / candle_range >= 0.30
    ):
        return -1

    if (
        d["close"][i] > d["open"][i]
        and lower_wick / candle_range >= 0.30
    ):
        return 1

    return 0


# ------------------------------------------------------------
# SETUP 5
# CONSOLIDATION BREAKOUT RETEST
# ------------------------------------------------------------

def signal_setup5(d, i):
    if i < 25:
        return 0

    a = d["atr"][i]
    if not np.isfinite(a) or a <= 0:
        return 0

    # 10-bar consolidation before breakout.
    box_high = np.max(d["high"][i - 15:i - 5])
    box_low = np.min(d["low"][i - 15:i - 5])
    box_width = box_high - box_low

    if box_width <= 0:
        return 0

    # Current candle must be a retest/reclaim of the box boundary.
    previous = i - 1

    breakout_up = (
        d["close"][previous] > box_high
    )

    breakout_down = (
        d["close"][previous] < box_low
    )

    if breakout_up:
        retest = (
            d["low"][i] <= box_high
            and d["close"][i] > box_high
        )
        if retest:
            return 1

    if breakout_down:
        retest = (
            d["high"][i] >= box_low
            and d["close"][i] < box_low
        )
        if retest:
            return -1

    return 0


# ------------------------------------------------------------
# SETUP 6
# RANGE OUTER-BAND REVERSION
# ------------------------------------------------------------

def signal_setup6(d, i):
    if i < 30:
        return 0

    a = d["atr"][i]
    if not np.isfinite(a) or a <= 0:
        return 0

    range_high = np.max(d["high"][i - 20:i])
    range_low = np.min(d["low"][i - 20:i])
    width = range_high - range_low

    if width <= 0:
        return 0

    # Reject excessively wide/trending conditions.
    if width > 8.0 * a:
        return 0

    close = d["close"][i]

    # Lower-band rejection -> long.
    if (
        d["low"][i] < range_low
        and close > range_low
    ):
        return 1

    # Upper-band rejection -> short.
    if (
        d["high"][i] > range_high
        and close < range_high
    ):
        return -1

    return 0


# ------------------------------------------------------------
# SETUP 7
# RELATIVE VOLUME IMPULSE CONTINUATION
# ------------------------------------------------------------

def signal_setup7(d, i):
    if i < RELVOL_N:
        return 0

    a = d["atr"][i]
    rv = d["relvol"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    if not np.isfinite(rv) or rv < 2.0:
        return 0

    candle_range = (
        d["high"][i] - d["low"][i]
    )

    if candle_range < 1.2 * a:
        return 0

    body = abs(
        d["close"][i] - d["open"][i]
    )

    if body / candle_range < 0.60:
        return 0

    if d["close"][i] > d["open"][i]:
        return 1

    if d["close"][i] < d["open"][i]:
        return -1

    return 0


SETUPS = {
    4: signal_setup4,
    5: signal_setup5,
    6: signal_setup6,
    7: signal_setup7,
}


def backtest(d, candles, signal_func):
    boundary = np.datetime64(
        OOS_BOUNDARY.replace("+00:00", "")
    )

    trades = []

    start = max(
        ATR_N,
        RELVOL_N,
        30,
    )

    i = start

    while i < len(candles) - 1:

        signal_time = np.datetime64(
            str(candles[i]["time"]).replace("+00:00", "")
        )

        if signal_time < boundary:
            i += 1
            continue

        side = signal_func(d, i)

        if side == 0:
            i += 1
            continue

        entry_idx = i + 1
        entry = d["open"][entry_idx]
        a = d["atr"][i]

        if not np.isfinite(a) or a <= 0:
            i += 1
            continue

        # Generic research risk model:
        # 1 ATR stop, 1.5R target.
        risk = a

        if side == 1:
            stop = entry - risk
            target = entry + 1.5 * risk
        else:
            stop = entry + risk
            target = entry - 1.5 * risk

        end = min(
            entry_idx + MAX_HOLD,
            len(candles) - 1,
        )

        exit_price = None
        exit_reason = "TIME_EXIT"
        exit_idx = end

        for j in range(entry_idx, end + 1):

            hi = d["high"][j]
            lo = d["low"][j]

            # Stop checked first.
            if side == 1:

                if lo <= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    exit_idx = j
                    break

                if hi >= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_idx = j
                    break

            else:

                if hi >= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    exit_idx = j
                    break

                if lo <= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_idx = j
                    break

        if exit_price is None:
            exit_price = d["close"][end]

        gross = (
            side
            * (exit_price - entry)
            / entry
        )

        trades.append({
            "side": "BUY" if side == 1 else "SELL",
            "entry_price": float(entry),
            "exit_price": float(exit_price),
            "gross_return": float(gross),
            "bars_held": exit_idx - entry_idx,
            "exit_reason": exit_reason,
            "entry_time": candles[entry_idx]["time"],
        })

        i = exit_idx + 1

    return trades


def stats(trades):
    if not trades:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "gross": 0.0,
            "pf": None,
        }

    wins = [
        x for x in trades
        if x["gross_return"] > 0
    ]

    losses = [
        x for x in trades
        if x["gross_return"] < 0
    ]

    gp = sum(
        x["gross_return"]
        for x in wins
    )

    gl = abs(sum(
        x["gross_return"]
        for x in losses
    ))

    return {
        "n": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross": sum(
            x["gross_return"]
            for x in trades
        ),
        "pf": gp / gl if gl > 0 else None,
    }


def costs(trades, slip):
    net = 0.0
    fees = 0.0
    slip_total = 0.0

    for t in trades:

        side = (
            1 if t["side"] == "BUY"
            else -1
        )

        entry = t["entry_price"]
        exit_price = t["exit_price"]

        entry_exec = (
            entry * (1 + side * slip)
        )

        exit_exec = (
            exit_price * (1 - side * slip)
        )

        gross = (
            side
            * (exit_exec - entry_exec)
            / entry_exec
        )

        fee = 2 * FEE_RATE

        net += gross - fee
        fees += fee

        slip_total += (
            abs(entry_exec - entry) / entry
            + abs(exit_exec - exit_price)
            / exit_price
        )

    return net, fees, slip_total


def print_stats(name, trades):

    s = stats(trades)

    pf = (
        "N/A"
        if s["pf"] is None
        else f"{s['pf']:.4f}"
    )

    print(
        f"{name:<14}"
        f"N={s['n']:>4} "
        f"W={s['wins']:>4} "
        f"L={s['losses']:>4} "
        f"Gross={s['gross'] * 100:+.4f}% "
        f"PF={pf}"
    )


def run_one(number, data, candles):

    trades = backtest(
        data,
        candles,
        SETUPS[number],
    )

    print()
    print("=" * 100)
    print(f"SETUP {number}")
    print("=" * 100)

    if not trades:
        print("NO TRADES")
        return {
            "number": number,
            "trades": 0,
            "gross": 0.0,
            "pf": None,
            "net002": 0.0,
            "decision": "KILL",
        }

    split = len(trades) // 2

    first = trades[:split]
    second = trades[split:]

    print_stats("ALL", trades)
    print_stats("FIRST HALF", first)
    print_stats("SECOND HALF", second)
    print_stats(
        "LONG",
        [x for x in trades if x["side"] == "BUY"],
    )
    print_stats(
        "SHORT",
        [x for x in trades if x["side"] == "SELL"],
    )

    reasons = {}

    for t in trades:
        reasons[t["exit_reason"]] = (
            reasons.get(t["exit_reason"], 0) + 1
        )

    print("Exit reasons:", reasons)

    avg_hold = sum(
        x["bars_held"] for x in trades
    ) / len(trades)

    print(
        f"Average bars held: {avg_hold:.2f}"
    )

    net002 = None

    for label, slip in SLIPPAGE_RATES.items():

        net, fee, slip_cost = costs(
            trades,
            slip,
        )

        final_pot = (
            STARTING_CAPITAL_USDT
            * (1 + net)
        )

        print(
            f"Slippage {label:<6} | "
            f"Final Pot ${final_pot:>10.4f} | "
            f"Net {net * 100:+.4f}% | "
            f"Fees {fee * 100:+.4f}% | "
            f"Slip {slip_cost * 100:+.4f}%"
        )

        if label == "0.02%":
            net002 = net

    s2 = stats(second)

    if (
        s2["gross"] > 0
        and net002 is not None
        and net002 > 0
    ):
        decision = "CANDIDATE"
    else:
        decision = "KILL"

    print(
        "DECISION:",
        decision,
    )

    s = stats(trades)

    return {
        "number": number,
        "trades": len(trades),
        "gross": s["gross"],
        "pf": s["pf"],
        "net002": net002,
        "decision": decision,
    }


def main():

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(
        candles
    )

    print("=" * 100)
    print("SETUPS 4–7 BATCH RESEARCH")
    print("RESEARCH ONLY — CORE LOCKED")
    print("=" * 100)
    print(
        f"Candles: {len(candles)}"
    )
    print(
        f"Validation: {valid}"
    )
    print(
        f"Reason: {reason}"
    )
    print(
        f"OOS: {OOS_BOUNDARY}"
    )

    if not valid:
        raise RuntimeError(reason)

    data = prepare(candles)

    results = []

    for number in (4, 5, 6, 7):
        results.append(
            run_one(
                number,
                data,
                candles,
            )
        )

    print()
    print("=" * 100)
    print("FINAL SUMMARY")
    print("=" * 100)

    print(
        "SETUP | TRADES | GROSS | PF | "
        "NET@0.02% | RESULT"
    )

    for r in results:

        pf = (
            "N/A"
            if r["pf"] is None
            else f"{r['pf']:.4f}"
        )

        print(
            f"{r['number']:>5} | "
            f"{r['trades']:>6} | "
            f"{r['gross'] * 100:+.4f}% | "
            f"{pf:>6} | "
            f"{r['net002'] * 100:+.4f}% | "
            f"{r['decision']}"
        )

    print("=" * 100)


if __name__ == "__main__":
    main()
