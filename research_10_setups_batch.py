"""
RESEARCH ONLY — 10 NEW SETUPS BATCH

Core is NOT modified.
No parameter optimization.
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
ATR_N = 14
BB_N = 20
RV_N = 20
VWAP_N = 20

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

    a = atr(h, l, c, ATR_N)
    e20 = ema(c, 20)
    e50 = ema(c, 50)
    e200 = ema(c, 200)
    r = rsi(c, 14)
    rv = relative_volume(v, RV_N)

    bb_mid = np.full(len(c), np.nan)
    bb_std = np.full(len(c), np.nan)

    for i in range(BB_N - 1, len(c)):
        bb_mid[i] = np.mean(c[i - BB_N + 1:i + 1])
        bb_std[i] = np.std(c[i - BB_N + 1:i + 1])

    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_width = (bb_upper - bb_lower) / c

    vwap = np.full(len(c), np.nan)

    for i in range(VWAP_N - 1, len(c)):
        sl = slice(i - VWAP_N + 1, i + 1)
        typical = (h[sl] + l[sl] + c[sl]) / 3
        vol = v[sl]
        total = np.sum(vol)
        if total > 0:
            vwap[i] = np.sum(typical * vol) / total

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
        "rsi": r,
        "rv": rv,
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_width": bb_width,
        "vwap": vwap,
    }


# ------------------------------------------------------------
# 10 candidate setups
# ------------------------------------------------------------

def setup1_vwap_reclaim(d, i):
    if not np.isfinite(d["vwap"][i]):
        return 0

    if i < 2:
        return 0

    # Reclaim from below + volume confirmation.
    if (
        d["c"][i - 1] < d["vwap"][i - 1]
        and d["c"][i] > d["vwap"][i]
        and d["rv"][i] >= 1.5
    ):
        return 1

    if (
        d["c"][i - 1] > d["vwap"][i - 1]
        and d["c"][i] < d["vwap"][i]
        and d["rv"][i] >= 1.5
    ):
        return -1

    return 0


def setup2_rsi_failure_swing(d, i):
    if i < 5:
        return 0

    r = d["rsi"]

    # Bullish RSI failure swing:
    # RSI makes lower/equal low, then breaks prior swing high.
    if (
        np.isfinite(r[i])
        and np.isfinite(r[i - 1])
        and r[i - 2] < 35
        and r[i - 1] > r[i - 2]
        and r[i] > r[i - 1]
        and d["c"][i] > d["c"][i - 1]
    ):
        return 1

    if (
        np.isfinite(r[i])
        and np.isfinite(r[i - 1])
        and r[i - 2] > 65
        and r[i - 1] < r[i - 2]
        and r[i] < r[i - 1]
        and d["c"][i] < d["c"][i - 1]
    ):
        return -1

    return 0


def setup3_bb_squeeze_expansion(d, i):
    if i < 5:
        return 0

    widths = d["bb_width"]

    if not np.isfinite(widths[i]):
        return 0

    prior = widths[i - 1]

    if not np.isfinite(prior):
        return 0

    compressed = (
        np.mean(widths[i - 4:i]) <=
        np.percentile(widths[max(20, i - 40):i], 30)
    )

    if not compressed:
        return 0

    if (
        d["c"][i] > d["bb_upper"][i]
        and d["rv"][i] >= 1.5
    ):
        return 1

    if (
        d["c"][i] < d["bb_lower"][i]
        and d["rv"][i] >= 1.5
    ):
        return -1

    return 0


def setup4_donchian_retest(d, i):
    if i < 21:
        return 0

    high20 = np.max(d["h"][i - 21:i - 1])
    low20 = np.min(d["l"][i - 21:i - 1])

    # Previous candle breaks, current candle retests/reclaims.
    if (
        d["c"][i - 1] > high20
        and d["l"][i] <= high20
        and d["c"][i] > high20
        and d["rv"][i] >= 1.2
    ):
        return 1

    if (
        d["c"][i - 1] < low20
        and d["h"][i] >= low20
        and d["c"][i] < low20
        and d["rv"][i] >= 1.2
    ):
        return -1

    return 0


def setup5_ema200_reclaim(d, i):
    if i < 2:
        return 0

    e = d["ema200"]

    if not np.isfinite(e[i]):
        return 0

    if (
        d["c"][i - 1] < e[i - 1]
        and d["c"][i] > e[i]
        and d["rv"][i] >= 1.2
        and d["c"][i] > d["o"][i]
    ):
        return 1

    if (
        d["c"][i - 1] > e[i - 1]
        and d["c"][i] < e[i]
        and d["rv"][i] >= 1.2
        and d["c"][i] < d["o"][i]
    ):
        return -1

    return 0


def setup6_volume_climax_reversal(d, i):
    a = d["atr"][i]

    if not np.isfinite(a) or a <= 0:
        return 0

    rng = d["h"][i] - d["l"][i]

    if rng < 1.5 * a or d["rv"][i] < 2.0:
        return 0

    body_high = max(d["o"][i], d["c"][i])
    body_low = min(d["o"][i], d["c"][i])

    upper = d["h"][i] - body_high
    lower = body_low - d["l"][i]

    if (
        d["c"][i] < d["o"][i]
        and upper / rng >= 0.30
    ):
        return -1

    if (
        d["c"][i] > d["o"][i]
        and lower / rng >= 0.30
    ):
        return 1

    return 0


def setup7_rsi_extreme_recovery(d, i):
    if i < 3:
        return 0

    r = d["rsi"]

    if not np.isfinite(r[i]):
        return 0

    if (
        r[i - 2] < 25
        and r[i] > 30
        and d["c"][i] > d["c"][i - 1]
    ):
        return 1

    if (
        r[i - 2] > 75
        and r[i] < 70
        and d["c"][i] < d["c"][i - 1]
    ):
        return -1

    return 0


def setup8_atr_expansion(d, i):
    if i < 10:
        return 0

    a = d["atr"]

    if not np.isfinite(a[i]):
        return 0

    prior = np.mean(a[i - 6:i])

    if prior <= 0:
        return 0

    if a[i] < prior * 1.25:
        return 0

    rng = d["h"][i] - d["l"][i]

    if rng < a[i]:
        return 0

    if (
        d["c"][i] > d["o"][i]
        and d["c"][i] > d["c"][i - 1]
        and d["rv"][i] >= 1.5
    ):
        return 1

    if (
        d["c"][i] < d["o"][i]
        and d["c"][i] < d["c"][i - 1]
        and d["rv"][i] >= 1.5
    ):
        return -1

    return 0


def setup9_two_leg_pullback(d, i):
    if i < 6:
        return 0

    # Trend must already exist.
    uptrend = (
        d["ema20"][i] > d["ema50"][i]
        and d["ema50"][i] > d["ema200"][i]
    )

    downtrend = (
        d["ema20"][i] < d["ema50"][i]
        and d["ema50"][i] < d["ema200"][i]
    )

    if uptrend:
        pullback1 = d["c"][i - 4] < d["c"][i - 5]
        pullback2 = d["c"][i - 2] < d["c"][i - 3]
        recovery = d["c"][i] > d["c"][i - 1]

        if pullback1 and pullback2 and recovery:
            return 1

    if downtrend:
        pullback1 = d["c"][i - 4] > d["c"][i - 5]
        pullback2 = d["c"][i - 2] > d["c"][i - 3]
        recovery = d["c"][i] < d["c"][i - 1]

        if pullback1 and pullback2 and recovery:
            return -1

    return 0


def setup10_price_volume_divergence(d, i):
    if i < 10:
        return 0

    price_old = d["c"][i - 5]
    price_now = d["c"][i]

    vol_old = np.mean(d["v"][i - 5:i])
    vol_now = np.mean(d["v"][i - 2:i])

    if vol_old <= 0:
        return 0

    # Price makes a new local extreme while volume fails to confirm.
    if (
        price_now > price_old
        and vol_now < vol_old * 0.75
        and d["c"][i] < d["o"][i]
    ):
        return -1

    if (
        price_now < price_old
        and vol_now < vol_old * 0.75
        and d["c"][i] > d["o"][i]
    ):
        return 1

    return 0


SETUPS = [
    ("01_VWAP_RECLAIM", setup1_vwap_reclaim),
    ("02_RSI_FAILURE_SWING", setup2_rsi_failure_swing),
    ("03_BB_SQUEEZE_EXPANSION", setup3_bb_squeeze_expansion),
    ("04_DONCHIAN_RETEST", setup4_donchian_retest),
    ("05_EMA200_RECLAIM", setup5_ema200_reclaim),
    ("06_VOLUME_CLIMAX_REVERSAL", setup6_volume_climax_reversal),
    ("07_RSI_EXTREME_RECOVERY", setup7_rsi_extreme_recovery),
    ("08_ATR_EXPANSION", setup8_atr_expansion),
    ("09_TWO_LEG_PULLBACK", setup9_two_leg_pullback),
    ("10_PRICE_VOLUME_DIVERGENCE", setup10_price_volume_divergence),
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

    gross_profit = np.sum(wins) if len(wins) else 0.0
    gross_loss = abs(np.sum(losses)) if len(losses) else 0.0

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
    print("10 SETUPS — RESEARCH BATCH")
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

    print()
    print("=" * 110)
    print("IMPORTANT")
    print("=" * 110)
    print(
        "This batch does NOT promote any setup into Core."
    )
    print(
        "A passing setup requires separate walk-forward "
        "validation before consideration for Strategy."
    )
    print(
        "No Core changes were made."
    )
    print("=" * 110)


if __name__ == "__main__":
    main()
