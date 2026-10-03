"""
RESEARCH ONLY — SETUP 4 EDGE ATTRIBUTION

Purpose:
Determine whether Setup 4 has an entry/price-action edge
independent of the chosen SL/TP.

Core files are NOT modified.
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

HORIZONS = (1, 3, 5, 10, 20, 40)


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
            out[i - 1] * (period - 1)
            + tr[i]
        ) / period

    return out


def prepare(candles):
    o = np.array(
        [float(x["open"]) for x in candles]
    )
    h = np.array(
        [float(x["high"]) for x in candles]
    )
    l = np.array(
        [float(x["low"]) for x in candles]
    )
    c = np.array(
        [float(x["close"]) for x in candles]
    )

    a = atr(h, l, c, ATR_N)

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "atr": a,
    }


def setup4_signal(d, i):
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


def collect_events(d, candles):
    boundary = np.datetime64(
        OOS_BOUNDARY.replace(
            "+00:00",
            "",
        )
    )

    events = []

    # Need enough future candles for the longest horizon.
    last_signal = len(candles) - max(HORIZONS) - 1

    for i in range(
        max(ATR_N, 20),
        last_signal + 1,
    ):

        signal_time = np.datetime64(
            str(
                candles[i]["time"]
            ).replace(
                "+00:00",
                "",
            )
        )

        if signal_time < boundary:
            continue

        side = setup4_signal(d, i)

        if side == 0:
            continue

        entry_idx = i + 1
        entry = d["open"][entry_idx]

        a = d["atr"][i]

        if not np.isfinite(a) or a <= 0:
            continue

        # Forward path from actual next-bar entry.
        future_high = {}
        future_low = {}

        for horizon in HORIZONS:
            end = entry_idx + horizon

            future_high[horizon] = np.max(
                d["high"][entry_idx:end + 1]
            )

            future_low[horizon] = np.min(
                d["low"][entry_idx:end + 1]
            )

        forward = {}

        for horizon in HORIZONS:
            close_idx = entry_idx + horizon

            forward[horizon] = (
                side
                * (
                    d["close"][close_idx]
                    - entry
                )
                / entry
            )

        # Maximum favorable / adverse excursion
        # over the full 40-bar observation window.
        max_high = np.max(
            d["high"][entry_idx:entry_idx + max(HORIZONS) + 1]
        )

        min_low = np.min(
            d["low"][entry_idx:entry_idx + max(HORIZONS) + 1]
        )

        if side == 1:
            mfe = (
                max_high - entry
            ) / entry

            mae = (
                min_low - entry
            ) / entry
        else:
            mfe = (
                entry - min_low
            ) / entry

            mae = (
                entry - max_high
            ) / entry

        events.append({
            "signal_idx": i,
            "entry_idx": entry_idx,
            "side": side,
            "entry": entry,
            "atr_pct": a / entry,
            "candle_range_pct": (
                d["high"][i]
                - d["low"][i]
            ) / entry,
            "mfe": mfe,
            "mae": mae,
            "forward": forward,
        })

    return events


def summarize(name, events):
    print()
    print("=" * 100)
    print(name)
    print("=" * 100)

    print(
        f"Events: {len(events)}"
    )

    if not events:
        return

    wins = sum(
        1
        for x in events
        if x["forward"][20] > 0
    )

    print(
        f"Positive 20-bar close: "
        f"{wins}/{len(events)}"
    )

    print()
    print(
        "HORIZON | N | POSITIVE | "
        "AVG RETURN | MEDIAN RETURN"
    )

    for h in HORIZONS:

        values = np.array(
            [
                x["forward"][h]
                for x in events
            ],
            dtype=float,
        )

        positive = np.sum(
            values > 0
        )

        print(
            f"{h:>7} | "
            f"{len(values):>3} | "
            f"{positive:>8} | "
            f"{np.mean(values) * 100:+.4f}% | "
            f"{np.median(values) * 100:+.4f}%"
        )

    mae = np.array(
        [x["mae"] for x in events]
    )

    mfe = np.array(
        [x["mfe"] for x in events]
    )

    atr_pct = np.array(
        [x["atr_pct"] for x in events]
    )

    range_pct = np.array(
        [
            x["candle_range_pct"]
            for x in events
        ]
    )

    print()
    print(
        f"AVG MAE: "
        f"{np.mean(mae) * 100:+.4f}%"
    )

    print(
        f"AVG MFE: "
        f"{np.mean(mfe) * 100:+.4f}%"
    )

    print(
        f"MEDIAN MFE: "
        f"{np.median(mfe) * 100:+.4f}%"
    )

    print(
        f"MEDIAN MAE: "
        f"{np.median(mae) * 100:+.4f}%"
    )

    print(
        f"AVG ATR%: "
        f"{np.mean(atr_pct) * 100:.4f}%"
    )

    print(
        f"AVG SIGNAL RANGE%: "
        f"{np.mean(range_pct) * 100:.4f}%"
    )


def chronological(events):
    if not events:
        return [], []

    split = len(events) // 2

    return (
        events[:split],
        events[split:],
    )


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
    print(
        "SETUP 4 — EDGE ATTRIBUTION"
    )
    print(
        "RESEARCH ONLY — CORE LOCKED"
    )
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

    print(
        "HORIZONS:",
        HORIZONS,
    )

    if not valid:
        raise RuntimeError(reason)

    data = prepare(candles)

    events = collect_events(
        data,
        candles,
    )

    long_events = [
        x
        for x in events
        if x["side"] == 1
    ]

    short_events = [
        x
        for x in events
        if x["side"] == -1
    ]

    first, second = chronological(
        events
    )

    first_long = [
        x
        for x in first
        if x["side"] == 1
    ]

    second_long = [
        x
        for x in second
        if x["side"] == 1
    ]

    summarize(
        "ALL",
        events,
    )

    summarize(
        "LONG",
        long_events,
    )

    summarize(
        "SHORT",
        short_events,
    )

    summarize(
        "FIRST HALF",
        first,
    )

    summarize(
        "SECOND HALF",
        second,
    )

    summarize(
        "FIRST HALF — LONG",
        first_long,
    )

    summarize(
        "SECOND HALF — LONG",
        second_long,
    )

    print()
    print("=" * 100)
    print(
        "EXIT-INDEPENDENT EDGE CHECK"
    )
    print("=" * 100)

    print(
        "This section intentionally ignores "
        "the 1.5R target and 1 ATR stop."
    )

    for h in HORIZONS:

        values = np.array(
            [
                x["forward"][h]
                for x in long_events
            ]
        )

        if len(values) == 0:
            continue

        print(
            f"LONG {h:>2} bars: "
            f"avg={np.mean(values) * 100:+.4f}% "
            f"median={np.median(values) * 100:+.4f}% "
            f"positive={np.mean(values > 0) * 100:.1f}%"
        )

    print()
    print("=" * 100)
    print(
        "RESEARCH INTERPRETATION"
    )
    print("=" * 100)

    long20 = np.mean(
        [
            x["forward"][20]
            for x in long_events
        ]
    ) if long_events else 0.0

    long40 = np.mean(
        [
            x["forward"][40]
            for x in long_events
        ]
    ) if long_events else 0.0

    second20 = np.mean(
        [
            x["forward"][20]
            for x in second_long
        ]
    ) if second_long else 0.0

    second40 = np.mean(
        [
            x["forward"][40]
            for x in second_long
        ]
    ) if second_long else 0.0

    print(
        f"LONG 20-bar avg: "
        f"{long20 * 100:+.4f}%"
    )

    print(
        f"LONG 40-bar avg: "
        f"{long40 * 100:+.4f}%"
    )

    print(
        f"SECOND-HALF LONG 20-bar avg: "
        f"{second20 * 100:+.4f}%"
    )

    print(
        f"SECOND-HALF LONG 40-bar avg: "
        f"{second40 * 100:+.4f}%"
    )

    print()
    print(
        "No Core changes were made."
    )

    print("=" * 100)


if __name__ == "__main__":
    main()
