"""
RESEARCH ONLY — SETUP 4 LONG WALK-FORWARD VALIDATION

First half:
    discover thresholds

Second half:
    locked validation

No optimization on validation data.
No Core changes.
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
            out[i - 1] * (period - 1)
            + tr[i]
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

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "atr": a,
        "ema20": ema(c, 20),
        "ema50": ema(c, 50),
        "ema200": ema(c, 200),
        "rv": relative_volume(v, 20),
    }


def setup4_long(d, i):
    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return False

    candle_range = (
        d["high"][i]
        - d["low"][i]
    )

    if candle_range < 2.0 * a:
        return False

    if d["close"][i] <= d["open"][i]:
        return False

    body_low = min(
        d["open"][i],
        d["close"][i],
    )

    lower_wick = (
        body_low
        - d["low"][i]
    )

    return (
        lower_wick / candle_range >= 0.30
    )


def collect(candles, d):
    boundary = np.datetime64(
        OOS_BOUNDARY.replace("+00:00", "")
    )

    events = []

    last_signal = (
        len(candles)
        - HORIZON
        - 1
    )

    for i in range(
        max(ATR_N, 200),
        last_signal + 1,
    ):
        signal_time = np.datetime64(
            str(candles[i]["time"]).replace(
                "+00:00",
                "",
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

        forward = (
            d["close"][entry_idx + HORIZON]
            - entry
        ) / entry

        candle_range = (
            d["high"][i]
            - d["low"][i]
        )

        body = abs(
            d["close"][i]
            - d["open"][i]
        )

        lower_wick = (
            min(
                d["open"][i],
                d["close"][i],
            )
            - d["low"][i]
        )

        events.append({
            "idx": i,
            "forward": forward,
            "atr_pct": d["atr"][i] / entry,
            "range_pct": candle_range / entry,
            "body_pct": body / entry,
            "wick_ratio": lower_wick / candle_range,
            "rv": d["rv"][i],
            "ema20_gap": (
                d["close"][i]
                - d["ema20"][i]
            ) / entry,
            "ema50_gap": (
                d["close"][i]
                - d["ema50"][i]
            ) / entry,
            "ema200_gap": (
                d["close"][i]
                - d["ema200"][i]
            ) / entry,
            "ema20_50": (
                d["ema20"][i]
                - d["ema50"][i]
            ) / entry,
            "ema50_200": (
                d["ema50"][i]
                - d["ema200"][i]
            ) / entry,
        })

    return events


def net(gross, n):
    return (
        gross
        - n * 2 * (
            FEE_PER_SIDE
            + SLIPPAGE_PER_SIDE
        )
    )


def report(name, events):
    if not events:
        print(
            f"{name}: N=0"
        )
        return

    values = np.array(
        [x["forward"] for x in events],
        dtype=float,
    )

    gross = np.sum(values)
    net_value = net(
        gross,
        len(values),
    )

    print(
        f"{name:<25}"
        f"N={len(values):>3} "
        f"positive={np.mean(values > 0) * 100:>5.1f}% "
        f"avg={np.mean(values) * 100:+.4f}% "
        f"gross={gross * 100:+.4f}% "
        f"net={net_value * 100:+.4f}%"
    )


def median_threshold(events, key):
    values = np.array(
        [
            x[key]
            for x in events
            if np.isfinite(x[key])
        ],
        dtype=float,
    )

    if len(values) == 0:
        return None

    return float(np.median(values))


def filtered(events, key, threshold):
    return [
        x
        for x in events
        if np.isfinite(x[key])
        and x[key] > threshold
    ]


def main():
    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print("=" * 100)
    print(
        "SETUP 4 — LONG WALK-FORWARD VALIDATION"
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
        f"Horizon: {HORIZON} bars"
    )

    print(
        "Execution:"
        " signal close -> next bar open"
    )

    print(
        "Cost:"
        f" fee={FEE_PER_SIDE * 100:.3f}%/side"
        f" slippage={SLIPPAGE_PER_SIDE * 100:.3f}%/side"
    )

    if not valid:
        raise RuntimeError(reason)

    d = prepare(candles)

    events = collect(
        candles,
        d,
    )

    split = len(events) // 2

    discovery = events[:split]
    validation = events[split:]

    print()
    print("=" * 100)
    print("RAW DATA")
    print("=" * 100)

    report(
        "ALL",
        events,
    )

    report(
        "DISCOVERY",
        discovery,
    )

    report(
        "VALIDATION",
        validation,
    )

    # Thresholds are determined ONLY from discovery.
    threshold_keys = [
        "atr_pct",
        "range_pct",
        "rv",
        "ema50_gap",
    ]

    thresholds = {}

    print()
    print("=" * 100)
    print("LOCKED DISCOVERY THRESHOLDS")
    print("=" * 100)

    for key in threshold_keys:
        threshold = median_threshold(
            discovery,
            key,
        )

        thresholds[key] = threshold

        print(
            f"{key:<15} "
            f"{threshold:.8f}"
        )

    print()
    print("=" * 100)
    print("DISCOVERY — LOCKED RULES")
    print("=" * 100)

    discovery_sets = {}

    for key in threshold_keys:
        selected = filtered(
            discovery,
            key,
            thresholds[key],
        )

        discovery_sets[key] = selected

        report(
            key,
            selected,
        )

    # Combined rule is deliberately simple:
    # require both volatility/range confirmation.
    combined_discovery = [
        x
        for x in discovery
        if (
            x["atr_pct"] > thresholds["atr_pct"]
            and x["range_pct"] > thresholds["range_pct"]
        )
    ]

    print()
    print(
        "COMBINED: ATR > discovery median "
        "AND RANGE > discovery median"
    )

    report(
        "COMBINED DISCOVERY",
        combined_discovery,
    )

    print()
    print("=" * 100)
    print("LOCKED VALIDATION")
    print("=" * 100)

    validation_sets = {}

    for key in threshold_keys:
        selected = filtered(
            validation,
            key,
            thresholds[key],
        )

        validation_sets[key] = selected

        report(
            key,
            selected,
        )

    combined_validation = [
        x
        for x in validation
        if (
            x["atr_pct"] > thresholds["atr_pct"]
            and x["range_pct"] > thresholds["range_pct"]
        )
    ]

    print()
    print(
        "COMBINED: ATR > discovery median "
        "AND RANGE > discovery median"
    )

    report(
        "COMBINED VALIDATION",
        combined_validation,
    )

    print()
    print("=" * 100)
    print("DECISION")
    print("=" * 100)

    validation_gross = np.sum(
        [
            x["forward"]
            for x in combined_validation
        ]
    ) if combined_validation else 0.0

    validation_net = net(
        validation_gross,
        len(combined_validation),
    )

    print(
        f"Validation N: "
        f"{len(combined_validation)}"
    )

    print(
        f"Validation gross: "
        f"{validation_gross * 100:+.4f}%"
    )

    print(
        f"Validation net: "
        f"{validation_net * 100:+.4f}%"
    )

    if (
        len(combined_validation) >= 10
        and validation_net > 0
    ):
        print()
        print(
            "RESULT: PASS — "
            "Setup 4 LONG has a validated candidate filter."
        )
    else:
        print()
        print(
            "RESULT: FAIL — "
            "Setup 4 LONG does not pass locked validation."
        )

    print()
    print(
        "No Core changes were made."
    )

    print("=" * 100)


if __name__ == "__main__":
    main()
