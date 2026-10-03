"""
RESEARCH ONLY — SETUP 4 LONG EDGE FILTER

Purpose:
Find whether existing entry features can separate stronger/weaker
LONG Setup 4 events without changing Core.

No Core files are modified.
No parameter optimization.
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

ATR_N = 14
HORIZON = 20

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002


def atr(high, low, close, period=14):
    n = len(close)
    out = np.full(n, np.nan)

    if n < period:
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

    out[period - 1] = np.mean(tr[:period])

    for i in range(period, n):
        out[i] = (
            out[i - 1] * (period - 1) + tr[i]
        ) / period

    return out


def ema(values, period):
    out = np.full(len(values), np.nan)

    if len(values) < period:
        return out

    out[period - 1] = np.mean(values[:period])
    alpha = 2.0 / (period + 1)

    for i in range(period, len(values)):
        out[i] = (
            alpha * values[i]
            + (1 - alpha) * out[i - 1]
        )

    return out


def relative_volume(volume, period=20):
    out = np.full(len(volume), np.nan)

    for i in range(period, len(volume)):
        avg = np.mean(volume[i - period:i])
        if avg > 0:
            out[i] = volume[i] / avg

    return out


def prepare(candles):
    o = np.array([float(x["open"]) for x in candles])
    h = np.array([float(x["high"]) for x in candles])
    l = np.array([float(x["low"]) for x in candles])
    c = np.array([float(x["close"]) for x in candles])
    v = np.array([float(x["volume"]) for x in candles])

    a = atr(h, l, c, ATR_N)

    e20 = ema(c, 20)
    e50 = ema(c, 50)
    e200 = ema(c, 200)

    rv = relative_volume(v, 20)

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "atr": a,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "rv": rv,
    }


def setup4_long(d, i):
    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return False

    candle_range = d["high"][i] - d["low"][i]

    if candle_range < 2.0 * a:
        return False

    if d["close"][i] <= d["open"][i]:
        return False

    body_low = min(d["open"][i], d["close"][i])
    lower_wick = body_low - d["low"][i]

    return (
        lower_wick / candle_range >= 0.30
    )


def collect(candles, d):
    boundary = np.datetime64(
        OOS_BOUNDARY.replace("+00:00", "")
    )

    events = []

    last_signal = len(candles) - HORIZON - 1

    for i in range(
        max(ATR_N, 200),
        last_signal + 1,
    ):
        signal_time = np.datetime64(
            str(candles[i]["time"]).replace(
                "+00:00", ""
            )
        )

        if signal_time < boundary:
            continue

        if not setup4_long(d, i):
            continue

        entry_idx = i + 1
        entry = d["open"][entry_idx]

        if entry <= 0:
            continue

        future = d["close"][entry_idx + HORIZON]

        forward = (future - entry) / entry

        candle_range = (
            d["high"][i] - d["low"][i]
        )

        body = abs(
            d["close"][i] - d["open"][i]
        )

        lower_wick = (
            min(d["open"][i], d["close"][i])
            - d["low"][i]
        )

        events.append({
            "idx": i,
            "forward": forward,
            "atr_pct": d["atr"][i] / entry,
            "range_pct": candle_range / entry,
            "body_pct": body / entry,
            "wick_pct": lower_wick / entry,
            "wick_ratio": lower_wick / candle_range,
            "rv": d["rv"][i],
            "ema20_gap": (
                d["close"][i] - d["ema20"][i]
            ) / entry,
            "ema50_gap": (
                d["close"][i] - d["ema50"][i]
            ) / entry,
            "ema200_gap": (
                d["close"][i] - d["ema200"][i]
            ) / entry,
            "ema20_50": (
                d["ema20"][i] - d["ema50"][i]
            ) / entry,
            "ema50_200": (
                d["ema50"][i] - d["ema200"][i]
            ) / entry,
        })

    return events


def net_return(gross):
    return (
        gross
        - 2 * FEE_PER_SIDE
        - 2 * SLIPPAGE_PER_SIDE
    )


def summarize(name, events):
    if not events:
        print(f"{name}: N=0")
        return

    values = np.array(
        [x["forward"] for x in events],
        dtype=float,
    )

    gross = np.sum(values)

    print(
        f"{name:<30} "
        f"N={len(values):>3} "
        f"positive={np.mean(values > 0) * 100:>5.1f}% "
        f"avg={np.mean(values) * 100:+.4f}% "
        f"median={np.median(values) * 100:+.4f}% "
        f"gross={gross * 100:+.4f}% "
        f"net={net_return(gross) * 100:+.4f}%"
    )


def median_split(events, key):
    values = np.array(
        [x[key] for x in events],
        dtype=float,
    )

    finite = np.isfinite(values)

    if np.sum(finite) < 10:
        return None

    threshold = np.median(values[finite])

    low = [
        x for x in events
        if np.isfinite(x[key])
        and x[key] <= threshold
    ]

    high = [
        x for x in events
        if np.isfinite(x[key])
        and x[key] > threshold
    ]

    return threshold, low, high


def main():
    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print("=" * 100)
    print("SETUP 4 — LONG EDGE FILTER RESEARCH")
    print("RESEARCH ONLY — CORE LOCKED")
    print("=" * 100)

    print(f"Candles: {len(candles)}")
    print(f"Validation: {valid}")
    print(f"Reason: {reason}")
    print(f"OOS: {OOS_BOUNDARY}")
    print(f"Horizon: {HORIZON} bars")
    print(
        f"Cost assumption: "
        f"fee={FEE_PER_SIDE * 100:.3f}%/side "
        f"slippage={SLIPPAGE_PER_SIDE * 100:.3f}%/side"
    )

    if not valid:
        raise RuntimeError(reason)

    d = prepare(candles)
    events = collect(candles, d)

    print()
    summarize("ALL LONG", events)

    split = len(events) // 2

    first = events[:split]
    second = events[split:]

    print()
    print("=" * 100)
    print("CHRONOLOGICAL CHECK")
    print("=" * 100)

    summarize("FIRST HALF", first)
    summarize("SECOND HALF", second)

    features = [
        "atr_pct",
        "range_pct",
        "body_pct",
        "wick_pct",
        "wick_ratio",
        "rv",
        "ema20_gap",
        "ema50_gap",
        "ema200_gap",
        "ema20_50",
        "ema50_200",
    ]

    print()
    print("=" * 100)
    print("FEATURE MEDIAN SPLITS — 20 BAR FORWARD")
    print("=" * 100)

    for key in features:
        result = median_split(events, key)

        if result is None:
            continue

        threshold, low, high = result

        print()
        print(
            f"{key} | median={threshold:.6f}"
        )

        summarize("LOW / <= median", low)
        summarize("HIGH / > median", high)

    print()
    print("=" * 100)
    print("SECOND-HALF MEDIAN SPLITS")
    print("=" * 100)

    for key in features:
        result = median_split(second, key)

        if result is None:
            continue

        threshold, low, high = result

        print()
        print(
            f"{key} | second-half median={threshold:.6f}"
        )

        summarize("LOW / <= median", low)
        summarize("HIGH / > median", high)

    print()
    print("=" * 100)
    print("DECISION")
    print("=" * 100)
    print(
        "This is an attribution test, not an optimization."
    )
    print(
        "No threshold is promoted into Core by this script."
    )
    print(
        "If no feature produces a stable second-half "
        "net-positive separation, Setup 4 is closed."
    )
    print()
    print("No Core changes were made.")
    print("=" * 100)


if __name__ == "__main__":
    main()
