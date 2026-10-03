"""
RESEARCH ONLY — 10 NEW SETUPS BATCH V2

Core is NOT modified.
No parameter optimization.
No setup from the previous 10-set batch is reused.
All setups use the same data, execution convention and cost assumptions.
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

HORIZON = 20

FEE = 0.0005
SLIPPAGE = 0.0002
ROUND_TRIP_COST = 2 * (FEE + SLIPPAGE)


def ema(x, n):
    out = np.full(len(x), np.nan)

    if len(x) < n:
        return out

    out[n - 1] = np.mean(x[:n])
    a = 2.0 / (n + 1)

    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]

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
            out[i - 1] * (n - 1) + tr[i]
        ) / n

    return out


def rsi(c, n=14):
    out = np.full(len(c), np.nan)

    if len(c) <= n:
        return out

    d = np.diff(c)
    gain = np.maximum(d, 0)
    loss = np.maximum(-d, 0)

    ag = np.mean(gain[:n])
    al = np.mean(loss[:n])

    if al == 0:
        out[n] = 100.0
    else:
        rs = ag / al
        out[n] = 100 - 100 / (1 + rs)

    for i in range(n + 1, len(c)):
        g = gain[i - 1]
        lo = loss[i - 1]

        ag = (ag * (n - 1) + g) / n
        al = (al * (n - 1) + lo) / n

        if al == 0:
            out[i] = 100.0
        else:
            rs = ag / al
            out[i] = 100 - 100 / (1 + rs)

    return out


def relative_volume(v, n=20):
    out = np.full(len(v), np.nan)

    for i in range(n, len(v)):
        avg = np.mean(v[i - n:i])

        if avg > 0:
            out[i] = v[i] / avg

    return out


def prepare(candles):
    o = np.array([float(x["open"]) for x in candles])
    h = np.array([float(x["high"]) for x in candles])
    l = np.array([float(x["low"]) for x in candles])
    c = np.array([float(x["close"]) for x in candles])
    v = np.array([float(x["volume"]) for x in candles])

    a = atr(h, l, c, 14)

    e12 = ema(c, 12)
    e20 = ema(c, 20)
    e26 = ema(c, 26)
    e50 = ema(c, 50)
    e200 = ema(c, 200)

    r = rsi(c, 14)
    rv = relative_volume(v, 20)

    bb_mid = np.full(len(c), np.nan)
    bb_std = np.full(len(c), np.nan)

    for i in range(19, len(c)):
        bb_mid[i] = np.mean(c[i - 19:i + 1])
        bb_std[i] = np.std(c[i - 19:i + 1])

    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    macd = e12 - e26
    macd_signal = ema(macd[~np.isnan(macd)], 9)

    full_signal = np.full(len(c), np.nan)

    valid_macd = np.where(~np.isnan(macd))[0]

    if len(valid_macd) >= 9:
        start = valid_macd[0]
        for j, value in enumerate(macd_signal):
            full_signal[start + j] = value

    return {
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "v": v,
        "atr": a,
        "ema12": e12,
        "ema20": e20,
        "ema26": e26,
        "ema50": e50,
        "ema200": e200,
        "rsi": r,
        "rv": rv,
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "macd": macd,
        "macd_signal": full_signal,
    }


# ------------------------------------------------------------
# 10 NEW CANDIDATE SETUPS
# ------------------------------------------------------------

def setup1_ema_trend_pullback_reclaim(d, i):
    if i < 5:
        return 0

    bullish_trend = (
        d["ema20"][i] > d["ema50"][i]
        and d["ema50"][i] > d["ema200"][i]
    )

    bearish_trend = (
        d["ema20"][i] < d["ema50"][i]
        and d["ema50"][i] < d["ema200"][i]
    )

    if d["rv"][i] < 1.2:
        return 0

    if bullish_trend:
        touched = np.min(d["l"][i - 4:i]) <= d["ema20"][i]
        reclaim = d["c"][i] > d["ema20"][i]
        momentum = d["c"][i] > d["h"][i - 1]

        if touched and reclaim and momentum:
            return 1

    if bearish_trend:
        touched = np.max(d["h"][i - 4:i]) >= d["ema20"][i]
        reclaim = d["c"][i] < d["ema20"][i]
        momentum = d["c"][i] < d["l"][i - 1]

        if touched and reclaim and momentum:
            return -1

    return 0


def setup2_rsi50_trend_continuation(d, i):
    if i < 2:
        return 0

    if d["rv"][i] < 1.2:
        return 0

    bullish = (
        d["ema20"][i] > d["ema50"][i]
        and d["ema50"][i] > d["ema200"][i]
        and d["rsi"][i - 1] <= 50
        and d["rsi"][i] > 50
        and d["c"][i] > d["o"][i]
    )

    bearish = (
        d["ema20"][i] < d["ema50"][i]
        and d["ema50"][i] < d["ema200"][i]
        and d["rsi"][i - 1] >= 50
        and d["rsi"][i] < 50
        and d["c"][i] < d["o"][i]
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


def setup3_bb_midline_continuation(d, i):
    if i < 2:
        return 0

    if d["rv"][i] < 1.2:
        return 0

    if not np.isfinite(d["bb_mid"][i]):
        return 0

    bullish = (
        d["ema50"][i] > d["ema200"][i]
        and d["c"][i - 1] <= d["bb_mid"][i - 1]
        and d["c"][i] > d["bb_mid"][i]
        and d["c"][i] > d["o"][i]
    )

    bearish = (
        d["ema50"][i] < d["ema200"][i]
        and d["c"][i - 1] >= d["bb_mid"][i - 1]
        and d["c"][i] < d["bb_mid"][i]
        and d["c"][i] < d["o"][i]
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


def setup4_keltner_breakout(d, i):
    if i < 2:
        return 0

    if d["rv"][i] < 1.5:
        return 0

    upper = d["ema20"][i] + 1.5 * d["atr"][i]
    lower = d["ema20"][i] - 1.5 * d["atr"][i]

    bullish = (
        d["c"][i - 1] <=
        d["ema20"][i - 1] + 1.5 * d["atr"][i - 1]
        and d["c"][i] > upper
        and d["c"][i] > d["o"][i]
    )

    bearish = (
        d["c"][i - 1] >=
        d["ema20"][i - 1] - 1.5 * d["atr"][i - 1]
        and d["c"][i] < lower
        and d["c"][i] < d["o"][i]
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


def setup5_macd_zero_line_momentum(d, i):
    if i < 2:
        return 0

    if not np.isfinite(d["macd_signal"][i]):
        return 0

    bullish = (
        d["macd"][i - 1] <= 0
        and d["macd"][i] > 0
        and d["macd"][i] > d["macd_signal"][i]
        and d["rv"][i] >= 1.2
    )

    bearish = (
        d["macd"][i - 1] >= 0
        and d["macd"][i] < 0
        and d["macd"][i] < d["macd_signal"][i]
        and d["rv"][i] >= 1.2
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


def setup6_three_bar_momentum(d, i):
    if i < 4:
        return 0

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    rng = d["h"][i] - d["l"][i]

    if rng < a or d["rv"][i] < 1.5:
        return 0

    bull_sequence = (
        d["c"][i - 2] > d["o"][i - 2]
        and d["c"][i - 1] > d["o"][i - 1]
        and d["c"][i] > d["o"][i]
        and d["c"][i] > d["c"][i - 1]
        and d["c"][i - 1] > d["c"][i - 2]
        and d["c"][i] > d["ema50"][i]
    )

    bear_sequence = (
        d["c"][i - 2] < d["o"][i - 2]
        and d["c"][i - 1] < d["o"][i - 1]
        and d["c"][i] < d["o"][i]
        and d["c"][i] < d["c"][i - 1]
        and d["c"][i - 1] < d["c"][i - 2]
        and d["c"][i] < d["ema50"][i]
    )

    if bull_sequence:
        return 1

    if bear_sequence:
        return -1

    return 0


def setup7_bb_outer_engulfing(d, i):
    if i < 2:
        return 0

    if d["rv"][i] < 1.2:
        return 0

    prev_body_high = max(d["o"][i - 1], d["c"][i - 1])
    prev_body_low = min(d["o"][i - 1], d["c"][i - 1])

    bullish = (
        d["c"][i - 1] < d["bb_lower"][i - 1]
        and d["c"][i] > d["o"][i]
        and d["o"][i] <= prev_body_low
        and d["c"][i] >= prev_body_high
    )

    bearish = (
        d["c"][i - 1] > d["bb_upper"][i - 1]
        and d["c"][i] < d["o"][i]
        and d["o"][i] >= prev_body_high
        and d["c"][i] <= prev_body_low
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


def setup8_ema50_pinbar_rejection(d, i):
    if i < 1:
        return 0

    if d["rv"][i] < 1.2:
        return 0

    rng = d["h"][i] - d["l"][i]

    if rng <= 0:
        return 0

    body = abs(d["c"][i] - d["o"][i])
    upper = d["h"][i] - max(d["o"][i], d["c"][i])
    lower = min(d["o"][i], d["c"][i]) - d["l"][i]

    bullish = (
        d["l"][i] <= d["ema50"][i]
        and d["c"][i] > d["ema50"][i]
        and lower / rng >= 0.50
        and body / rng <= 0.40
        and d["c"][i] > d["o"][i]
    )

    bearish = (
        d["h"][i] >= d["ema50"][i]
        and d["c"][i] < d["ema50"][i]
        and upper / rng >= 0.50
        and body / rng <= 0.40
        and d["c"][i] < d["o"][i]
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


def setup9_atr_compression_expansion(d, i):
    if i < 12:
        return 0

    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    prior = np.mean(d["atr"][i - 8:i])

    if prior <= 0:
        return 0

    compressed = prior <= np.mean(d["atr"][i - 20:i]) * 0.75
    expanded = a >= prior * 1.50

    rng = d["h"][i] - d["l"][i]

    if not compressed or not expanded:
        return 0

    if rng < a or d["rv"][i] < 1.5:
        return 0

    if d["c"][i] > d["o"][i] and d["c"][i] > d["c"][i - 1]:
        return 1

    if d["c"][i] < d["o"][i] and d["c"][i] < d["c"][i - 1]:
        return -1

    return 0


def setup10_short_swing_breakout(d, i):
    if i < 6:
        return 0

    if d["rv"][i] < 1.3:
        return 0

    prior_high = np.max(d["h"][i - 5:i])
    prior_low = np.min(d["l"][i - 5:i])

    bullish = (
        d["c"][i] > prior_high
        and d["c"][i] > d["ema50"][i]
        and d["ema50"][i] > d["ema200"][i]
        and d["c"][i] > d["o"][i]
    )

    bearish = (
        d["c"][i] < prior_low
        and d["c"][i] < d["ema50"][i]
        and d["ema50"][i] < d["ema200"][i]
        and d["c"][i] < d["o"][i]
    )

    if bullish:
        return 1

    if bearish:
        return -1

    return 0


SETUPS = [
    ("01_EMA_TREND_PULLBACK_RECLAIM", setup1_ema_trend_pullback_reclaim),
    ("02_RSI50_TREND_CONTINUATION", setup2_rsi50_trend_continuation),
    ("03_BB_MIDLINE_CONTINUATION", setup3_bb_midline_continuation),
    ("04_KELTNER_BREAKOUT", setup4_keltner_breakout),
    ("05_MACD_ZERO_LINE_MOMENTUM", setup5_macd_zero_line_momentum),
    ("06_THREE_BAR_MOMENTUM", setup6_three_bar_momentum),
    ("07_BB_OUTER_ENGULFING", setup7_bb_outer_engulfing),
    ("08_EMA50_PINBAR_REJECTION", setup8_ema50_pinbar_rejection),
    ("09_ATR_COMPRESSION_EXPANSION", setup9_atr_compression_expansion),
    ("10_SHORT_SWING_BREAKOUT", setup10_short_swing_breakout),
]


def collect(candles, d, fn):
    boundary = np.datetime64(
        OOS_BOUNDARY.replace("+00:00", "")
    )

    events = []

    last = len(candles) - HORIZON - 1

    for i in range(200, last + 1):
        t = np.datetime64(
            str(candles[i]["time"]).replace("+00:00", "")
        )

        if t < boundary:
            continue

        side = fn(d, i)

        if side == 0:
            continue

        entry_idx = i + 1
        entry = d["o"][entry_idx]

        if entry <= 0:
            continue

        forward = (
            side
            * (
                d["c"][entry_idx + HORIZON]
                - entry
            )
            / entry
        )

        events.append({
            "side": side,
            "forward": forward,
        })

    return events


def stats(events):
    if not events:
        return None

    values = np.array(
        [x["forward"] for x in events],
        dtype=float,
    )

    wins = values[values > 0]
    losses = values[values < 0]

    gross = np.sum(values)

    gross_profit = (
        np.sum(wins)
        if len(wins)
        else 0.0
    )

    gross_loss = (
        abs(np.sum(losses))
        if len(losses)
        else 0.0
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    net_value = (
        gross
        - len(values) * ROUND_TRIP_COST
    )

    return {
        "n": len(values),
        "winrate": np.mean(values > 0),
        "avg": np.mean(values),
        "gross": gross,
        "net": net_value,
        "pf": pf,
    }


def fmt(s):
    if s is None:
        return "N=0"

    return (
        f"N={s['n']:>4} "
        f"WR={s['winrate'] * 100:>5.1f}% "
        f"AVG={s['avg'] * 100:+.4f}% "
        f"GROSS={s['gross'] * 100:+.3f}% "
        f"NET={s['net'] * 100:+.3f}% "
        f"PF={s['pf']:.3f}"
    )


def main():
    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print("=" * 110)
    print("10 NEW SETUPS — RESEARCH BATCH V2")
    print("RESEARCH ONLY — CORE LOCKED")
    print("=" * 110)
    print(f"Candles: {len(candles)}")
    print(f"Validation: {valid}")
    print(f"Reason: {reason}")
    print(f"OOS: {OOS_BOUNDARY}")
    print(f"Horizon: {HORIZON} bars")
    print("Execution: signal close -> next bar open")
    print(
        f"Cost: fee={FEE * 100:.3f}%/side "
        f"slippage={SLIPPAGE * 100:.3f}%/side"
    )

    if not valid:
        raise RuntimeError(reason)

    d = prepare(candles)

    results = []

    print()
    print("=" * 110)
    print("RESULTS")
    print("=" * 110)

    for name, fn in SETUPS:
        events = collect(
            candles,
            d,
            fn,
        )

        all_stats = stats(events)

        first_n = len(events) // 2

        first = events[:first_n]
        second = events[first_n:]

        long_events = [
            x for x in events
            if x["side"] == 1
        ]

        short_events = [
            x for x in events
            if x["side"] == -1
        ]

        first_stats = stats(first)
        second_stats = stats(second)
        long_stats = stats(long_events)
        short_stats = stats(short_events)

        print()
        print(name)
        print(" ALL   ", fmt(all_stats))
        print(" FIRST ", fmt(first_stats))
        print(" SECOND", fmt(second_stats))
        print(" LONG  ", fmt(long_stats))
        print(" SHORT ", fmt(short_stats))

        results.append({
            "name": name,
            "all": all_stats,
            "first": first_stats,
            "second": second_stats,
            "long": long_stats,
            "short": short_stats,
        })

    print()
    print("=" * 110)
    print("QUICK SCREEN")
    print("=" * 110)
    print(
        "PASS CANDIDATE = second-half net > 0, "
        "PF > 1, N >= 10"
    )

    candidates = []

    for r in results:
        s = r["second"]

        if (
            s is not None
            and s["n"] >= 10
            and s["net"] > 0
            and s["pf"] > 1.0
        ):
            candidates.append(r)

    if not candidates:
        print("No setup passed the initial screen.")
    else:
        for r in candidates:
            print(
                r["name"],
                "->",
                fmt(r["second"]),
            )


if __name__ == "__main__":
    main()
