"""
RESEARCH ONLY — SETUPS 8-10 vs SETUP 4

Setup 4  High Volatility Exhaustion       (benchmark)
Setup 8  Range Expansion Rejection
Setup 9  Three-Bar Exhaustion
Setup 10 Inside-Bar Expansion Breakout

Purpose:
Find the strongest research candidate before deeper development.

No Core files are modified.
Signal at candle close -> entry next candle open.
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

ATR_N = 14
RELVOL_N = 20
MAX_HOLD = 48

FEE_RATE = 0.0005

SLIPPAGE_RATES = {
    "0.00%": 0.0,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}


# ============================================================
# INDICATORS
# ============================================================

def atr(high, low, close, period=14):

    n = len(close)

    out = np.full(
        n,
        np.nan,
        dtype=float,
    )

    if n == 0:
        return out

    previous_close = np.empty(n)

    previous_close[0] = close[0]
    previous_close[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - previous_close),
            np.abs(low - previous_close),
        ),
    )

    if n < period:
        return out

    out[period - 1] = np.mean(
        tr[:period]
    )

    for i in range(period, n):

        out[i] = (
            out[i - 1] * (period - 1)
            + tr[i]
        ) / period

    return out


def prepare(candles):

    open_ = np.array(
        [float(x["open"]) for x in candles]
    )

    high = np.array(
        [float(x["high"]) for x in candles]
    )

    low = np.array(
        [float(x["low"]) for x in candles]
    )

    close = np.array(
        [float(x["close"]) for x in candles]
    )

    volume = np.array(
        [float(x["volume"]) for x in candles]
    )

    atr_values = atr(
        high,
        low,
        close,
        ATR_N,
    )

    relvol = np.full(
        len(close),
        np.nan,
    )

    for i in range(
        RELVOL_N,
        len(close),
    ):

        base = np.mean(
            volume[i - RELVOL_N:i]
        )

        if base > 0:
            relvol[i] = (
                volume[i] / base
            )

    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "atr": atr_values,
        "relvol": relvol,
    }


# ============================================================
# SETUP 4 — BENCHMARK
# ============================================================

def signal_setup4(d, i):

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    candle_range = (
        d["high"][i]
        - d["low"][i]
    )

    if candle_range < 2.0 * a:
        return 0

    body_high = max(
        d["open"][i],
        d["close"][i],
    )

    body_low = min(
        d["open"][i],
        d["close"][i],
    )

    upper_wick = (
        d["high"][i]
        - body_high
    )

    lower_wick = (
        body_low
        - d["low"][i]
    )

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


# ============================================================
# SETUP 8 — RANGE EXPANSION REJECTION
# ============================================================

def signal_setup8(d, i):

    if i < 20:
        return 0

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    range_high = np.max(
        d["high"][i - 20:i]
    )

    range_low = np.min(
        d["low"][i - 20:i]
    )

    candle_range = (
        d["high"][i]
        - d["low"][i]
    )

    if candle_range < 1.5 * a:
        return 0

    # Sweep upper range and close back inside.
    if (
        d["high"][i] > range_high
        and d["close"][i] < range_high
    ):
        return -1

    # Sweep lower range and close back inside.
    if (
        d["low"][i] < range_low
        and d["close"][i] > range_low
    ):
        return 1

    return 0


# ============================================================
# SETUP 9 — THREE-BAR EXHAUSTION
# ============================================================

def signal_setup9(d, i):

    if i < 3:
        return 0

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    o1 = d["open"][i - 2]
    c1 = d["close"][i - 2]

    o2 = d["open"][i - 1]
    c2 = d["close"][i - 1]

    o3 = d["open"][i]
    c3 = d["close"][i]

    r1 = d["high"][i - 2] - d["low"][i - 2]
    r2 = d["high"][i - 1] - d["low"][i - 1]
    r3 = d["high"][i] - d["low"][i]

    if min(r1, r2, r3) <= 0:
        return 0

    # Two bullish impulse candles followed by
    # bearish rejection closing below previous close.
    bullish_impulse = (
        c1 > o1
        and c2 > o2
        and c2 > c1
        and (c2 - o2) >= 0.50 * r2
    )

    bearish_reversal = (
        c3 < o3
        and c3 < c2
        and (o3 - c3) >= 0.40 * r3
    )

    if bullish_impulse and bearish_reversal:
        if r2 >= 1.0 * a:
            return -1

    # Two bearish impulse candles followed by
    # bullish rejection closing above previous close.
    bearish_impulse = (
        c1 < o1
        and c2 < o2
        and c2 < c1
        and (o2 - c2) >= 0.50 * r2
    )

    bullish_reversal = (
        c3 > o3
        and c3 > c2
        and (c3 - o3) >= 0.40 * r3
    )

    if bearish_impulse and bullish_reversal:
        if r2 >= 1.0 * a:
            return 1

    return 0


# ============================================================
# SETUP 10 — INSIDE BAR EXPANSION BREAKOUT
# ============================================================

def signal_setup10(d, i):

    if i < 2:
        return 0

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    mother_high = d["high"][i - 2]
    mother_low = d["low"][i - 2]

    inside = (
        d["high"][i - 1] < mother_high
        and d["low"][i - 1] > mother_low
    )

    if not inside:
        return 0

    current_range = (
        d["high"][i]
        - d["low"][i]
    )

    if current_range < 1.0 * a:
        return 0

    rv = d["relvol"][i]

    if not np.isfinite(rv) or rv < 1.5:
        return 0

    if (
        d["close"][i] > mother_high
        and d["close"][i] > d["open"][i]
    ):
        return 1

    if (
        d["close"][i] < mother_low
        and d["close"][i] < d["open"][i]
    ):
        return -1

    return 0


SETUPS = {
    4: signal_setup4,
    8: signal_setup8,
    9: signal_setup9,
    10: signal_setup10,
}


# ============================================================
# BACKTEST
# ============================================================

def backtest(
    d,
    candles,
    signal_func,
):

    boundary = np.datetime64(
        OOS_BOUNDARY.replace(
            "+00:00",
            "",
        )
    )

    trades = []

    start = max(
        ATR_N,
        RELVOL_N,
        20,
    )

    i = start

    while i < len(candles) - 1:

        signal_time = np.datetime64(
            str(
                candles[i]["time"]
            ).replace(
                "+00:00",
                "",
            )
        )

        if signal_time < boundary:
            i += 1
            continue

        side = signal_func(
            d,
            i,
        )

        if side == 0:
            i += 1
            continue

        entry_idx = i + 1

        entry = d["open"][entry_idx]

        a = d["atr"][i]

        if not np.isfinite(a) or a <= 0:
            i += 1
            continue

        risk = a

        if side == 1:

            stop = (
                entry - risk
            )

            target = (
                entry + 1.5 * risk
            )

        else:

            stop = (
                entry + risk
            )

            target = (
                entry - 1.5 * risk
            )

        end = min(
            entry_idx + MAX_HOLD,
            len(candles) - 1,
        )

        exit_price = None
        exit_reason = "TIME_EXIT"
        exit_idx = end

        for j in range(
            entry_idx,
            end + 1,
        ):

            hi = d["high"][j]
            lo = d["low"][j]

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
            "side": (
                "BUY"
                if side == 1
                else "SELL"
            ),
            "entry_price": float(entry),
            "exit_price": float(
                exit_price
            ),
            "gross_return": float(
                gross
            ),
            "bars_held": (
                exit_idx
                - entry_idx
            ),
            "exit_reason": exit_reason,
        })

        # One position at a time.
        i = exit_idx + 1

    return trades


# ============================================================
# STATS
# ============================================================

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
        t for t in trades
        if t["gross_return"] > 0
    ]

    losses = [
        t for t in trades
        if t["gross_return"] < 0
    ]

    gp = sum(
        t["gross_return"]
        for t in wins
    )

    gl = abs(
        sum(
            t["gross_return"]
            for t in losses
        )
    )

    return {
        "n": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross": sum(
            t["gross_return"]
            for t in trades
        ),
        "pf": (
            gp / gl
            if gl > 0
            else None
        ),
    }


def costs(
    trades,
    slippage,
):

    net = 0.0
    fees = 0.0
    slip_total = 0.0

    for t in trades:

        side = (
            1
            if t["side"] == "BUY"
            else -1
        )

        entry = t["entry_price"]
        exit_price = t["exit_price"]

        entry_exec = (
            entry
            * (
                1
                + side * slippage
            )
        )

        exit_exec = (
            exit_price
            * (
                1
                - side * slippage
            )
        )

        gross_after_slip = (
            side
            * (
                exit_exec
                - entry_exec
            )
            / entry_exec
        )

        fee = 2 * FEE_RATE

        net += (
            gross_after_slip
            - fee
        )

        fees += fee

        slip_total += (
            abs(
                entry_exec - entry
            ) / entry
            +
            abs(
                exit_exec - exit_price
            ) / exit_price
        )

    return (
        net,
        fees,
        slip_total,
    )


def print_stats(
    name,
    trades,
):

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


# ============================================================
# RUN
# ============================================================

def run_one(
    number,
    d,
    candles,
):

    trades = backtest(
        d,
        candles,
        SETUPS[number],
    )

    print()
    print("=" * 100)
    print(
        f"SETUP {number}"
    )
    print("=" * 100)

    if not trades:

        print(
            "NO TRADES"
        )

        return {
            "number": number,
            "trades": 0,
            "gross": 0.0,
            "pf": None,
            "net002": 0.0,
            "second_gross": 0.0,
            "decision": "KILL",
        }

    split = len(trades) // 2

    first = trades[:split]
    second = trades[split:]

    print_stats(
        "ALL",
        trades,
    )

    print_stats(
        "FIRST HALF",
        first,
    )

    print_stats(
        "SECOND HALF",
        second,
    )

    print_stats(
        "LONG",
        [
            x
            for x in trades
            if x["side"] == "BUY"
        ],
    )

    print_stats(
        "SHORT",
        [
            x
            for x in trades
            if x["side"] == "SELL"
        ],
    )

    reasons = {}

    for t in trades:

        reasons[
            t["exit_reason"]
        ] = (
            reasons.get(
                t["exit_reason"],
                0,
            )
            + 1
        )

    print(
        "Exit reasons:",
        reasons,
    )

    print(
        "Average bars held:",
        round(
            sum(
                t["bars_held"]
                for t in trades
            )
            / len(trades),
            2,
        ),
    )

    net002 = None

    print()
    print(
        "NET COST"
    )

    for label, slip in (
        SLIPPAGE_RATES.items()
    ):

        net, fee, slip_cost = costs(
            trades,
            slip,
        )

        final_pot = (
            STARTING_CAPITAL_USDT
            * (
                1 + net
            )
        )

        print(
            f"{label:<7} "
            f"Final=${final_pot:>9.4f} "
            f"Net={net * 100:+.4f}% "
            f"Fee={fee * 100:+.4f}% "
            f"Slip={slip_cost * 100:+.4f}%"
        )

        if label == "0.02%":
            net002 = net

    s2 = stats(
        second
    )

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

    s = stats(
        trades
    )

    return {
        "number": number,
        "trades": len(trades),
        "gross": s["gross"],
        "pf": s["pf"],
        "net002": net002,
        "second_gross": s2["gross"],
        "decision": decision,
    }


def main():

    candles = (
        get_historical_candles_100k(
            symbol=SYMBOL,
            interval=INTERVAL,
            candles_needed=CANDLES_NEEDED,
        )
    )

    valid, reason = (
        validate_candles(
            candles
        )
    )

    print("=" * 100)
    print(
        "SETUPS 8-10 vs SETUP 4"
    )
    print(
        "RESEARCH ONLY — CORE LOCKED"
    )
    print("=" * 100)

    print(
        "Candles:",
        len(candles),
    )

    print(
        "Validation:",
        valid,
    )

    print(
        "Reason:",
        reason,
    )

    print(
        "OOS:",
        OOS_BOUNDARY,
    )

    if not valid:
        raise RuntimeError(
            reason
        )

    data = prepare(
        candles
    )

    results = []

    for number in (
        4,
        8,
        9,
        10,
    ):

        results.append(
            run_one(
                number,
                data,
                candles,
            )
        )

    print()
    print("=" * 100)
    print(
        "FINAL COMPARISON"
    )
    print("=" * 100)

    print(
        "SETUP | TRADES | GROSS | PF | "
        "SECOND | NET@0.02 | RESULT"
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
            f"{r['second_gross'] * 100:+.4f}% | "
            f"{r['net002'] * 100:+.4f}% | "
            f"{r['decision']}"
        )

    print("=" * 100)


if __name__ == "__main__":
    main()
