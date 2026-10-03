import json
import math
import time
from dataclasses import dataclass
from urllib.request import Request, urlopen
from bisect import bisect_right

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


def fetch_klines(symbol: str, interval: str, limit: int = LIMIT) -> list[Candle]:
    max_per_request = 1000
    rows = []
    end_time = None

    while len(rows) < limit:
        batch_limit = min(max_per_request, limit - len(rows))

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

        oldest_time = int(batch[0][0])
        end_time = oldest_time - 1

        if len(batch) < batch_limit:
            break

        time.sleep(0.1)

    rows.sort(key=lambda x: int(x[0]))

    # Remove duplicates by candle open time.
    unique = {}
    for row in rows:
        unique[int(row[0])] = row

    rows = [unique[k] for k in sorted(unique)]

    # Keep requested number, then remove newest candle if it is still open.
    rows = rows[-limit:]
    rows = rows[:-1]

    return [
        Candle(
            time=int(x[0]),
            open=float(x[1]),
            high=float(x[2]),
            low=float(x[3]),
            close=float(x[4]),
            volume=float(x[5]),
        )
        for x in rows
    ]


def ema(values: list[float], period: int) -> list[float | None]:
    out = [None] * len(values)
    if len(values) < period:
        return out

    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1)

    prev = seed
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev

    return out


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    tr = [None] * len(candles)

    for i, c in enumerate(candles):
        if i == 0:
            tr[i] = c.high - c.low
        else:
            prev = candles[i - 1].close
            tr[i] = max(
                c.high - c.low,
                abs(c.high - prev),
                abs(c.low - prev),
            )

    out = [None] * len(candles)
    if len(candles) < period:
        return out

    seed = sum(x for x in tr[:period] if x is not None) / period
    out[period - 1] = seed
    prev = seed

    for i in range(period, len(candles)):
        prev = ((prev * (period - 1)) + tr[i]) / period
        out[i] = prev

    return out


def relative_volume(
    candles: list[Candle],
    lookback: int = 20,
) -> list[float | None]:
    out = [None] * len(candles)

    for i in range(lookback, len(candles)):
        avg = sum(
            candles[j].volume
            for j in range(i - lookback, i)
        ) / lookback

        if avg > 0:
            out[i] = candles[i].volume / avg

    return out


def structure(
    candles: list[Candle],
    lookback: int = 5,
) -> list[str | None]:
    out = [None] * len(candles)

    for i in range(lookback, len(candles)):
        recent = candles[i - lookback:i]

        hh = candles[i].high > max(x.high for x in recent)
        hl = candles[i].low > min(x.low for x in recent)

        lh = candles[i].high < max(x.high for x in recent)
        ll = candles[i].low < min(x.low for x in recent)

        if hh and hl:
            out[i] = "BULLISH"
        elif lh and ll:
            out[i] = "BEARISH"
        else:
            out[i] = "NEUTRAL"

    return out


def build_features(candles: list[Candle]) -> dict[str, list]:
    closes = [c.close for c in candles]

    return {
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "atr": atr(candles),
        "relative_volume": relative_volume(candles),
        "structure": structure(candles),
    }


def directional_alignment(
    features: dict[str, list],
    candles: list[Candle],
    index: int,
    side: str,
) -> bool:
    price = candles[index].close
    e20 = features["ema20"][index]
    e50 = features["ema50"][index]
    e200 = features["ema200"][index]
    struct = features["structure"][index]

    if None in (e20, e50, e200, struct):
        return False

    if side == "BUY":
        return (
            price > e200
            and e20 > e50
            and struct == "BULLISH"
        )

    return (
        price < e200
        and e20 < e50
        and struct == "BEARISH"
    )


def evaluate_trade(
    candles: list[Candle],
    index: int,
    side: str,
) -> float | None:
    exit_index = index + HORIZON

    if exit_index >= len(candles):
        return None

    entry = candles[index].close
    exit_price = candles[exit_index].close

    if entry <= 0:
        return None

    if side == "BUY":
        gross = (exit_price - entry) / entry
    else:
        gross = (entry - exit_price) / entry

    return gross - ROUND_TRIP_COST


def summarize(returns: list[float]) -> dict:
    if not returns:
        return {
            "n": 0,
            "wr": 0.0,
            "net": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "loss_streak": 0,
            "final_pot": STARTING_POT,
        }

    winners = [x for x in returns if x > 0]
    losers = [x for x in returns if x <= 0]

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    pot = STARTING_POT
    peak = pot
    max_dd = 0.0
    current_loss = 0
    max_loss = 0

    for r in returns:
        pot *= 1.0 + r

        if pot > peak:
            peak = pot

        dd = (pot - peak) / peak
        max_dd = min(max_dd, dd)

        if r <= 0:
            current_loss += 1
            max_loss = max(max_loss, current_loss)
        else:
            current_loss = 0

    return {
        "n": len(returns),
        "wr": len(winners) / len(returns) * 100,
        "net": sum(returns) * 100,
        "pf": pf,
        "dd": max_dd * 100,
        "loss_streak": max_loss,
        "final_pot": pot,
    }


def collect_trades(candles, features):
    candidates = []

    for i in range(200, len(candles) - HORIZON):
        for side in ("BUY", "SELL"):
            if directional_alignment(features, candles, i, side):
                ret = evaluate_trade(candles, i, side)

                if ret is not None:
                    candidates.append({
                        "index": i,
                        "time": candles[i].time,
                        "side": side,
                        "ret": ret,
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


def block_stats(trades):
    if not trades:
        return []

    size = math.ceil(len(trades) / 4)
    blocks = []

    for n in range(4):
        block = trades[n * size:(n + 1) * size]

        if not block:
            continue

        s = summarize([x["ret"] for x in block])
        blocks.append(s)

    return blocks


def side_stats(trades):
    result = {}

    for side in ("BUY", "SELL"):
        subset = [x["ret"] for x in trades if x["side"] == side]
        result[side] = summarize(subset)

    return result


def print_stats(label, stats):
    print(
        f"{label:<10} "
        f"N={stats['n']:>4} "
        f"WR={stats['wr']:>6.2f}% "
        f"Net={stats['net']:>9.3f}% "
        f"PF={stats['pf']:>6.3f} "
        f"DD={stats['dd']:>8.2f}% "
        f"LS={stats['loss_streak']:>3} "
        f"Pot={stats['final_pot']:>9.2f}"
    )


def main():
    print("=" * 110)
    print("TRADING BOT — ARENA VALIDATION V1")
    print("RESEARCH ONLY — NO ORDERS — CORE UNTOUCHED")
    print("=" * 110)
    print(
        f"Markets: {', '.join(SYMBOLS)} | "
        f"TF: {', '.join(INTERVALS)} | "
        f"Candles: {LIMIT} | "
        f"Horizon: {HORIZON} | "
        f"Cost: {ROUND_TRIP_COST * 100:.3f}%"
    )
    print()

    results = []

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            print(f"Loading {symbol} {interval}...", flush=True)

            try:
                candles = fetch_klines(symbol, interval)
            except Exception as exc:
                print(f"  ERROR: {exc}")
                continue

            features = build_features(candles)
            trades = collect_trades(candles, features)

            all_stats = summarize([x["ret"] for x in trades])
            sides = side_stats(trades)
            blocks = block_stats(trades)

            print_stats("ALL", all_stats)
            print_stats("LONG", sides["BUY"])
            print_stats("SHORT", sides["SELL"])

            for i, block in enumerate(blocks, 1):
                print_stats(f"BLOCK{i}", block)

            result = {
                "symbol": symbol,
                "interval": interval,
                "candles": len(candles),
                "trades": trades,
                "all": all_stats,
                "long": sides["BUY"],
                "short": sides["SELL"],
                "blocks": blocks,
            }

            results.append(result)
            print("-" * 110)

            time.sleep(0.25)

    with open(
        "research_arena_validation_v1_results.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(results, f, indent=2)

    print()
    print("=" * 110)
    print("VALIDATION COMPLETE")
    print("=" * 110)
    print("Saved: research_arena_validation_v1_results.json")
    print("CORE FILES MODIFIED: NO")
    print("=" * 110)


if __name__ == "__main__":
    main()
