"""
RESEARCH ONLY — SETUP 8 ATR EXPANSION DEEP RESEARCH

Goal:
Find whether ATR Expansion contains a tradable LONG edge
after reducing low-quality / excessive signals.

Method:
1. Rebuild original Setup 8 signal.
2. Attribute forward returns and MFE/MAE.
3. Inspect structural filters.
4. Test a small set of pre-defined structural filters.
5. Compare First Half / Second Half.
6. Cost-adjust every result.
7. No Core changes.
8. No optimization loop.
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
RV_N = 20
EMA_FAST = 20
EMA_SLOW = 50
EMA_TREND = 200

HORIZON = 20

FEE = 0.0005
SLIPPAGE = 0.0002
ROUND_TRIP_COST = 2 * (FEE + SLIPPAGE)


def ema(x, n):
    out = np.full(len(x), np.nan)

    if len(x) < n:
        return out

    out[n - 1] = np.mean(x[:n])
    alpha = 2.0 / (n + 1)

    for i in range(n, len(x)):
        out[i] = (
            alpha * x[i]
            + (1 - alpha) * out[i - 1]
        )

    return out


def atr(h, l, c, n=14):
    out = np.full(len(c), np.nan)

    if len(c) < n:
        return out

    prev = np.empty(len(c))
    prev[0] = c[0]
    prev[1:] = c[:-1]

    tr = np.maximum(
        h - l,
        np.maximum(
            np.abs(h - prev),
            np.abs(l - prev),
        ),
    )

    out[n - 1] = np.mean(tr[:n])

    for i in range(n, len(c)):
        out[i] = (
            out[i - 1] * (n - 1)
            + tr[i]
        ) / n

    return out


def relative_volume(v, n=20):
    out = np.full(len(v), np.nan)

    for i in range(n, len(v)):
        avg = np.mean(v[i - n:i])

        if avg > 0:
            out[i] = v[i] / avg

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

    v = np.array(
        [float(x["volume"]) for x in candles]
    )

    a = atr(h, l, c, ATR_N)

    e20 = ema(c, EMA_FAST)
    e50 = ema(c, EMA_SLOW)
    e200 = ema(c, EMA_TREND)

    rv = relative_volume(v, RV_N)

    return {
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "v": v,
        "atr": a,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "rv": rv,
    }


def original_setup8(d, i):
    """
    Original Setup 8:
        ATR expands >= 1.25x recent average
        current range >= ATR
        bullish candle
        close > previous close
        RV >= 1.5
    """

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return False

    prior_atr = np.mean(
        d["atr"][i - 6:i]
    )

    if prior_atr <= 0:
        return False

    if a < prior_atr * 1.25:
        return False

    candle_range = (
        d["h"][i] - d["l"][i]
    )

    if candle_range < a:
        return False

    if d["c"][i] <= d["o"][i]:
        return False

    if d["c"][i] <= d["c"][i - 1]:
        return False

    if not np.isfinite(d["rv"][i]):
        return False

    if d["rv"][i] < 1.5:
        return False

    return True


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
        max(EMA_TREND, ATR_N, RV_N) + 1,
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

        if not original_setup8(d, i):
            continue

        entry_idx = i + 1
        entry = d["o"][entry_idx]

        if entry <= 0:
            continue

        a = d["atr"][i]
        candle_range = (
            d["h"][i] - d["l"][i]
        )

        body = abs(
            d["c"][i] - d["o"][i]
        )

        upper_wick = (
            d["h"][i]
            - max(d["o"][i], d["c"][i])
        )

        lower_wick = (
            min(d["o"][i], d["c"][i])
            - d["l"][i]
        )

        forward = (
            d["c"][entry_idx + HORIZON]
            - entry
        ) / entry

        future_high = np.max(
            d["h"][
                entry_idx:
                entry_idx + HORIZON + 1
            ]
        )

        future_low = np.min(
            d["l"][
                entry_idx:
                entry_idx + HORIZON + 1
            ]
        )

        mfe = (
            future_high - entry
        ) / entry

        mae = (
            future_low - entry
        ) / entry

        prior_atr = np.mean(
            d["atr"][i - 6:i]
        )

        events.append({
            "idx": i,
            "forward": forward,
            "mfe": mfe,
            "mae": mae,

            "atr_pct": a / entry,

            "atr_expansion": (
                a / prior_atr
                if prior_atr > 0
                else np.nan
            ),

            "range_atr": (
                candle_range / a
                if a > 0
                else np.nan
            ),

            "body_range": (
                body / candle_range
                if candle_range > 0
                else np.nan
            ),

            "upper_wick_range": (
                upper_wick / candle_range
                if candle_range > 0
                else np.nan
            ),

            "lower_wick_range": (
                lower_wick / candle_range
                if candle_range > 0
                else np.nan
            ),

            "rv": d["rv"][i],

            "ema20_gap": (
                d["c"][i]
                - d["ema20"][i]
            ) / entry,

            "ema50_gap": (
                d["c"][i]
                - d["ema50"][i]
            ) / entry,

            "ema200_gap": (
                d["c"][i]
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


def net_value(events):
    if not events:
        return 0.0

    gross = np.sum(
        [x["forward"] for x in events]
    )

    return (
        gross
        - len(events) * ROUND_TRIP_COST
    )


def pf(events):
    if not events:
        return 0.0

    values = np.array(
        [x["forward"] for x in events]
    )

    positive = values[values > 0]
    negative = values[values < 0]

    gp = np.sum(positive)
    gl = abs(np.sum(negative))

    if gl == 0:
        return np.inf

    return gp / gl


def report(name, events):
    if not events:
        print(
            f"{name:<32} N=0"
        )
        return

    values = np.array(
        [x["forward"] for x in events]
    )

    gross = np.sum(values)
    net = (
        gross
        - len(events) * ROUND_TRIP_COST
    )

    print(
        f"{name:<32}"
        f"N={len(events):>4} "
        f"WR={np.mean(values > 0) * 100:>5.1f}% "
        f"AVG={np.mean(values) * 100:+.4f}% "
        f"GROSS={gross * 100:+.3f}% "
        f"NET={net * 100:+.3f}% "
        f"PF={pf(events):.3f}"
    )


def split(events):
    n = len(events) // 2
    return events[:n], events[n:]


def apply_filter(events, fn):
    return [
        x for x in events
        if fn(x)
    ]


def median(events, key):
    values = np.array(
        [
            x[key]
            for x in events
            if np.isfinite(x[key])
        ]
    )

    if len(values) == 0:
        return np.nan

    return float(np.median(values))


def main():
    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(
        candles
    )

    print("=" * 110)
    print(
        "SETUP 8 — ATR EXPANSION DEEP RESEARCH"
    )
    print(
        "RESEARCH ONLY — CORE LOCKED"
    )
    print("=" * 110)

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
        "Execution: signal close -> next bar open"
    )

    print(
        f"Cost: fee={FEE * 100:.3f}%/side "
        f"slippage={SLIPPAGE * 100:.3f}%/side"
    )

    if not valid:
        raise RuntimeError(reason)

    d = prepare(candles)

    events = collect(
        candles,
        d,
    )

    first, second = split(events)

    print()
    print("=" * 110)
    print("BASELINE")
    print("=" * 110)

    report(
        "ALL",
        events,
    )

    report(
        "FIRST HALF",
        first,
    )

    report(
        "SECOND HALF",
        second,
    )

    # --------------------------------------------------------
    # Structural attribution
    # --------------------------------------------------------

    print()
    print("=" * 110)
    print("STRUCTURAL FILTERS")
    print("=" * 110)

    candidates = {
        "ATR_EXPANSION_HIGH": (
            lambda x:
            x["atr_expansion"] >= 1.50
        ),

        "RANGE_ATR_HIGH": (
            lambda x:
            x["range_atr"] >= 1.50
        ),

        "BODY_STRONG": (
            lambda x:
            x["body_range"] >= 0.60
        ),

        "LOWER_WICK_LOW": (
            lambda x:
            x["lower_wick_range"] <= 0.20
        ),

        "RV_HIGH": (
            lambda x:
            x["rv"] >= 2.00
        ),

        "ABOVE_EMA20": (
            lambda x:
            x["ema20_gap"] > 0
        ),

        "ABOVE_EMA50": (
            lambda x:
            x["ema50_gap"] > 0
        ),

        "ABOVE_EMA200": (
            lambda x:
            x["ema200_gap"] > 0
        ),

        "EMA20_ABOVE_50": (
            lambda x:
            x["ema20_50"] > 0
        ),

        "EMA50_ABOVE_200": (
            lambda x:
            x["ema50_200"] > 0
        ),

        "STRONG_TREND": (
            lambda x:
            x["ema20_gap"] > 0
            and x["ema50_gap"] > 0
            and x["ema200_gap"] > 0
        ),
    }

    for name, fn in candidates.items():
        print()
        print(name)

        selected = apply_filter(
            events,
            fn,
        )

        selected_first = apply_filter(
            first,
            fn,
        )

        selected_second = apply_filter(
            second,
            fn,
        )

        report(
            "ALL",
            selected,
        )

        report(
            "FIRST",
            selected_first,
        )

        report(
            "SECOND",
            selected_second,
        )

    # --------------------------------------------------------
    # Combined structural filters
    # --------------------------------------------------------

    print()
    print("=" * 110)
    print("COMBINED STRUCTURAL FILTERS")
    print("=" * 110)

    combinations = {
        "EXPANSION + STRONG_BODY": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["body_range"] >= 0.60
        ),

        "EXPANSION + RV": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["rv"] >= 2.00
        ),

        "RANGE + BODY": (
            lambda x:
            x["range_atr"] >= 1.50
            and x["body_range"] >= 0.60
        ),

        "RANGE + RV": (
            lambda x:
            x["range_atr"] >= 1.50
            and x["rv"] >= 2.00
        ),

        "EXPANSION + ABOVE_EMA50": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["ema50_gap"] > 0
        ),

        "EXPANSION + STRONG_TREND": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["ema20_gap"] > 0
            and x["ema50_gap"] > 0
            and x["ema200_gap"] > 0
        ),

        "RANGE + BODY + RV": (
            lambda x:
            x["range_atr"] >= 1.50
            and x["body_range"] >= 0.60
            and x["rv"] >= 2.00
        ),

        "EXPANSION + BODY + ABOVE_EMA50": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["body_range"] >= 0.60
            and x["ema50_gap"] > 0
        ),
    }

    for name, fn in combinations.items():
        print()
        print(name)

        selected = apply_filter(
            events,
            fn,
        )

        selected_first = apply_filter(
            first,
            fn,
        )

        selected_second = apply_filter(
            second,
            fn,
        )

        report(
            "ALL",
            selected,
        )

        report(
            "FIRST",
            selected_first,
        )

        report(
            "SECOND",
            selected_second,
        )

    # --------------------------------------------------------
    # Exit-independent MFE test
    # --------------------------------------------------------

    print()
    print("=" * 110)
    print("MFE / MAE ATTRIBUTION")
    print("=" * 110)

    for name, fn in {
        "BASELINE": lambda x: True,
        "EXPANSION+BODY": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["body_range"] >= 0.60
        ),
        "EXPANSION+RV": (
            lambda x:
            x["atr_expansion"] >= 1.50
            and x["rv"] >= 2.00
        ),
    }.items():

        selected = apply_filter(
            events,
            fn,
        )

        if not selected:
            continue

        mfe = np.array(
            [x["mfe"] for x in selected]
        )

        mae = np.array(
            [x["mae"] for x in selected]
        )

        print()
        print(name)
        print(
            f"N={len(selected)} "
            f"AVG_MFE={np.mean(mfe) * 100:+.4f}% "
            f"MEDIAN_MFE={np.median(mfe) * 100:+.4f}% "
            f"AVG_MAE={np.mean(mae) * 100:+.4f}% "
            f"MEDIAN_MAE={np.median(mae) * 100:+.4f}%"
        )

    # --------------------------------------------------------
    # Decision
    # --------------------------------------------------------

    print()
    print("=" * 110)
    print("DECISION")
    print("=" * 110)

    print(
        "This is structural research, not parameter optimization."
    )

    print(
        "No filter is promoted into Core."
    )

    print(
        "The next step, if any, must be locked walk-forward validation."
    )

    print(
        "If no structural filter survives validation after cost,"
    )

    print(
        "Setup 8 should be abandoned."
    )

    print()
    print(
        "No Core changes were made."
    )

    print("=" * 110)


if __name__ == "__main__":
    main()
