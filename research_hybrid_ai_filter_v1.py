import json
import math
import time
from dataclasses import dataclass
from urllib.request import Request, urlopen

SYMBOLS = ["SOLUSDT", "DOGEUSDT", "BTCUSDT"]
INTERVALS = ["30m", "1h"]

LIMIT = 5000
HORIZON = 20
ROUND_TRIP_COST = 0.0014
STARTING_POT = 1500.0


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_klines(symbol, interval, limit=LIMIT):
    rows = []
    end_time = None

    while len(rows) < limit:
        batch_limit = min(1000, limit - len(rows))

        url = (
            "https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&limit={batch_limit}"
        )

        if end_time is not None:
            url += f"&endTime={end_time}"

        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})

        with urlopen(req, timeout=20) as response:
            batch = json.loads(response.read())

        if not batch:
            break

        rows = batch + rows
        end_time = int(batch[0][0]) - 1

        if len(batch) < batch_limit:
            break

        time.sleep(0.1)

    rows.sort(key=lambda x: int(x[0]))

    unique = {}
    for row in rows:
        unique[int(row[0])] = row

    rows = [unique[k] for k in sorted(unique)]
    rows = rows[-limit:]
    rows = rows[:-1]

    return [
        Candle(
            int(x[0]),
            float(x[1]),
            float(x[2]),
            float(x[3]),
            float(x[4]),
            float(x[5]),
        )
        for x in rows
    ]


def ema(values, period):
    out = [None] * len(values)

    if len(values) < period:
        return out

    prev = sum(values[:period]) / period
    out[period - 1] = prev

    alpha = 2.0 / (period + 1)

    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev

    return out


def rsi(candles, period=14):
    out = [None] * len(candles)

    if len(candles) <= period:
        return out

    gains = []
    losses = []

    for i in range(1, len(candles)):
        change = candles[i].close - candles[i - 1].close
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def value(gain, loss):
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = value(avg_gain, avg_loss)

    for i in range(period + 1, len(candles)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i - 1]) / period
        out[i] = value(avg_gain, avg_loss)

    return out


def relative_volume(candles, lookback=20):
    out = [None] * len(candles)

    for i in range(lookback, len(candles)):
        avg = sum(
            candles[j].volume
            for j in range(i - lookback, i)
        ) / lookback

        if avg > 0:
            out[i] = candles[i].volume / avg

    return out


def structure(candles, lookback=5):
    out = [None] * len(candles)

    for i in range(lookback, len(candles)):
        recent = candles[i - lookback:i]

        if (
            candles[i].high > max(x.high for x in recent)
            and candles[i].low > min(x.low for x in recent)
        ):
            out[i] = "BULLISH"

        elif (
            candles[i].high < max(x.high for x in recent)
            and candles[i].low < min(x.low for x in recent)
        ):
            out[i] = "BEARISH"

        else:
            out[i] = "NEUTRAL"

    return out


def build_features(candles):
    closes = [c.close for c in candles]

    return {
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "rsi": rsi(candles),
        "rv": relative_volume(candles),
        "structure": structure(candles),
    }


def quant_candidate(candles, f, i):
    if i < 200:
        return None

    price = candles[i].close

    e20 = f["ema20"][i]
    e50 = f["ema50"][i]
    e200 = f["ema200"][i]
    r = f["rsi"][i]
    rv = f["rv"][i]
    struct = f["structure"][i]

    if None in (e20, e50, e200, r, rv, struct):
        return None

    if price > e200 and e20 > e50 and struct == "BULLISH":
        side = "BUY"
    elif price < e200 and e20 < e50 and struct == "BEARISH":
        side = "SELL"
    else:
        return None

    return {
        "side": side,
        "price": price,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "rsi": r,
        "rv": rv,
        "structure": struct,
    }


def mock_ai_filter(candidate):
    """
    RESEARCH-ONLY MOCK AI.

    Fixed rules chosen before evaluating outcomes:
      1. Trend must be aligned.
      2. Relative volume must not be weak.
      3. RSI must not be in an extreme zone.

    This is deliberately deterministic.
    It is NOT a machine-learning model.
    """

    side = candidate["side"]
    rsi_value = candidate["rsi"]
    rv = candidate["rv"]

    if side == "BUY":
        trend_ok = (
            candidate["price"] > candidate["ema200"]
            and candidate["ema20"] > candidate["ema50"]
        )
        rsi_ok = 50.0 <= rsi_value <= 70.0
    else:
        trend_ok = (
            candidate["price"] < candidate["ema200"]
            and candidate["ema20"] < candidate["ema50"]
        )
        rsi_ok = 30.0 <= rsi_value <= 50.0

    volume_ok = rv >= 0.8

    passed = trend_ok and volume_ok and rsi_ok

    return {
        "decision": "PASS" if passed else "WAIT",
        "trend_ok": trend_ok,
        "volume_ok": volume_ok,
        "rsi_ok": rsi_ok,
    }


def evaluate(candles, i, side):
    exit_i = i + HORIZON

    if exit_i >= len(candles):
        return None

    entry = candles[i].close
    exit_price = candles[exit_i].close

    if side == "BUY":
        gross = (exit_price - entry) / entry
    else:
        gross = (entry - exit_price) / entry

    return gross - ROUND_TRIP_COST


def simulate(trades):
    pot = STARTING_POT
    peak = pot
    max_dd = 0.0
    loss_streak = 0
    max_loss_streak = 0

    winners = 0
    gross_profit = 0.0
    gross_loss = 0.0

    for trade in trades:
        r = trade["return"]

        if r > 0:
            winners += 1
            gross_profit += r
            loss_streak = 0
        else:
            gross_loss += abs(r)
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)

        pot *= 1.0 + r

        peak = max(peak, pot)
        max_dd = min(max_dd, (pot - peak) / peak)

    net = sum(x["return"] for x in trades)

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    return {
        "n": len(trades),
        "wr": (winners / len(trades) * 100) if trades else 0.0,
        "net": net * 100,
        "pf": pf,
        "dd": max_dd * 100,
        "loss_streak": max_loss_streak,
        "final_pot": pot,
    }


def collect(candles, features, ai_enabled):
    candidates = []

    for i in range(200, len(candles) - HORIZON):
        candidate = quant_candidate(candles, features, i)

        if candidate is None:
            continue

        ai = mock_ai_filter(candidate)

        if ai_enabled and ai["decision"] != "PASS":
            continue

        ret = evaluate(candles, i, candidate["side"])

        if ret is None:
            continue

        candidates.append({
            "index": i,
            "side": candidate["side"],
            "return": ret,
        })

    candidates.sort(key=lambda x: x["index"])

    selected = []
    next_free = -1

    for trade in candidates:
        if trade["index"] < next_free:
            continue

        selected.append(trade)
        next_free = trade["index"] + HORIZON

    return selected


def print_stats(label, s):
    print(
        f"{label:<12}"
        f"N={s['n']:>4} "
        f"WR={s['wr']:>6.2f}% "
        f"Net={s['net']:>9.3f}% "
        f"PF={s['pf']:>6.3f} "
        f"DD={s['dd']:>8.2f}% "
        f"LS={s['loss_streak']:>3} "
        f"Pot={s['final_pot']:>9.2f}"
    )


def main():
    print("=" * 110)
    print("HYBRID BOT — MOCK AI FILTER V1")
    print("RESEARCH ONLY — NO ORDERS — CORE UNTOUCHED")
    print("=" * 110)
    print("Baseline: Quant candidate only")
    print("Hybrid  : Quant candidate + Mock AI filter")
    print()

    results = []

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            print(f"Loading {symbol} {interval}...", flush=True)

            try:
                candles = fetch_klines(symbol, interval)
            except Exception as exc:
                print(f"ERROR: {exc}")
                continue

            features = build_features(candles)

            baseline = collect(candles, features, False)
            hybrid = collect(candles, features, True)

            base_stats = simulate(baseline)
            hybrid_stats = simulate(hybrid)

            print_stats("QUANT", base_stats)
            print_stats("HYBRID", hybrid_stats)

            print(
                f"Trade change : "
                f"{hybrid_stats['n'] - base_stats['n']:+d}"
            )
            print(
                f"Net change   : "
                f"{hybrid_stats['net'] - base_stats['net']:+.3f}%"
            )
            print("-" * 110)

            results.append({
                "symbol": symbol,
                "interval": interval,
                "baseline": base_stats,
                "hybrid": hybrid_stats,
            })

    with open(
        "research_hybrid_ai_filter_v1_results.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(results, f, indent=2)

    print()
    print("=" * 110)
    print("HYBRID EXPERIMENT COMPLETE")
    print("Saved: research_hybrid_ai_filter_v1_results.json")
    print("CORE FILES MODIFIED: NO")
    print("=" * 110)


if __name__ == "__main__":
    main()
