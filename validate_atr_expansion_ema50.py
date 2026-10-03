import requests
from datetime import datetime, timezone

BASE_URL = "https://api.binance.com/api/v3/klines"

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 10000

ATR_PERIOD = 14
ATR_LOOKBACK = 6
ATR_EXPANSION_MULTIPLIER = 1.25
RV_THRESHOLD = 1.5
HORIZON = 20

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002


def fetch_closed_candles():
    candles = []
    end_time = None

    while len(candles) < LIMIT:
        request_limit = min(1000, LIMIT - len(candles) + 1)

        params = {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": request_limit,
        }

        if end_time is not None:
            params["endTime"] = end_time

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=20,
        )
        response.raise_for_status()

        raw = response.json()

        if not raw:
            break

        batch = raw

        if end_time is None:
            batch = batch[:-1]

        if not batch:
            break

        parsed = []

        for candle in batch:
            parsed.append({
                "time": datetime.fromtimestamp(
                    candle[0] / 1000,
                    tz=timezone.utc,
                ),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            })

        candles = parsed + candles

        oldest_open_time_ms = raw[0][0]
        end_time = oldest_open_time_ms - 1

        if len(raw) < request_limit:
            break

    candles.sort(key=lambda c: c["time"])

    return candles[-LIMIT:]


def true_range(current, previous_close):
    return max(
        current["high"] - current["low"],
        abs(current["high"] - previous_close),
        abs(current["low"] - previous_close),
    )


def calculate_atr(candles):
    atr = [None] * len(candles)

    trs = [None] * len(candles)

    for i in range(1, len(candles)):
        trs[i] = true_range(candles[i], candles[i - 1]["close"])

    for i in range(ATR_PERIOD, len(candles)):
        window = [
            trs[j]
            for j in range(i - ATR_PERIOD + 1, i + 1)
            if trs[j] is not None
        ]

        if len(window) == ATR_PERIOD:
            atr[i] = sum(window) / ATR_PERIOD

    return atr


def calculate_ema(values, period):
    ema = [None] * len(values)

    valid = [v for v in values if v is not None]

    if len(valid) < period:
        return ema

    first_index = next(
        i for i, v in enumerate(values)
        if v is not None
    )

    if len(values) - first_index < period:
        return ema

    start = first_index + period - 1
    seed = sum(values[first_index:start + 1]) / period

    ema[start] = seed

    multiplier = 2 / (period + 1)

    for i in range(start + 1, len(values)):
        if values[i] is not None:
            ema[i] = (
                (values[i] - ema[i - 1]) * multiplier
                + ema[i - 1]
            )

    return ema


def calculate_relative_volume(candles, period=20):
    rv = [None] * len(candles)

    for i in range(period, len(candles)):
        previous = [
            candles[j]["volume"]
            for j in range(i - period, i)
        ]

        avg_volume = sum(previous) / period

        if avg_volume > 0:
            rv[i] = candles[i]["volume"] / avg_volume

    return rv


def evaluate(candles):
    atr = calculate_atr(candles)

    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, 50)

    relative_volume = calculate_relative_volume(candles)

    trades = []

    start = max(
        ATR_PERIOD + ATR_LOOKBACK,
        50,
    )

    end = len(candles) - HORIZON - 1

    for i in range(start, end + 1):
        if atr[i] is None:
            continue

        if ema50[i] is None:
            continue

        if relative_volume[i] is None:
            continue

        recent_atr = [
            atr[j]
            for j in range(i - ATR_LOOKBACK, i)
            if atr[j] is not None
        ]

        if len(recent_atr) != ATR_LOOKBACK:
            continue

        avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK

        expansion = (
            atr[i] >= avg_recent_atr * ATR_EXPANSION_MULTIPLIER
        )

        candle_range = candles[i]["high"] - candles[i]["low"]

        bullish = candles[i]["close"] > candles[i]["open"]

        higher_close = candles[i]["close"] > candles[i - 1]["close"]

        volume_confirmed = relative_volume[i] >= RV_THRESHOLD

        above_ema50 = candles[i]["close"] > ema50[i]

        if not (
            expansion
            and candle_range >= atr[i]
            and bullish
            and higher_close
            and volume_confirmed
            and above_ema50
        ):
            continue

        entry = candles[i + 1]["open"]
        exit_price = candles[i + 1 + HORIZON]["close"]

        gross_return = (exit_price / entry) - 1

        total_cost = (
            2 * FEE_PER_SIDE
            + 2 * SLIPPAGE_PER_SIDE
        )

        net_return = gross_return - total_cost

        trades.append({
            "time": candles[i]["time"],
            "gross": gross_return,
            "net": net_return,
        })

    return trades


def summarize(trades, label):
    if not trades:
        print(f"{label}: N=0")
        return

    gross = sum(t["gross"] for t in trades)
    net = sum(t["net"] for t in trades)

    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]

    win_rate = len(wins) / len(trades)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    avg_net = net / len(trades)

    print(f"{label}")
    print("-" * 72)
    print(f"N              : {len(trades)}")
    print(f"Win Rate       : {win_rate * 100:.2f}%")
    print(f"Avg Net        : {avg_net * 100:.4f}%")
    print(f"Gross Return   : {gross * 100:.4f}%")
    print(f"Net Return     : {net * 100:.4f}%")
    print(f"Profit Factor  : {pf:.3f}")


def main():
    print("=" * 72)
    print("ATR EXPANSION + EMA50 VALIDATION")
    print("=" * 72)
    print(f"Symbol         : {SYMBOL}")
    print(f"Interval       : {INTERVAL}")
    print(f"Requested      : {LIMIT} closed candles")
    print(f"ATR Expansion  : >= {ATR_EXPANSION_MULTIPLIER:.2f}x")
    print(f"RV Threshold   : >= {RV_THRESHOLD:.2f}")
    print(f"EMA Filter     : Close > EMA50")
    print(f"Horizon        : {HORIZON} bars")
    print(
        f"Costs          : "
        f"fee {FEE_PER_SIDE * 100:.2f}%/side + "
        f"slippage {SLIPPAGE_PER_SIDE * 100:.2f}%/side"
    )
    print()

    candles = fetch_closed_candles()

    print(f"Actual Candles : {len(candles)}")

    if len(candles) < 1000:
        raise RuntimeError(
            "Validation dataset is too small."
        )

    print(
        f"Period         : "
        f"{candles[0]['time']} -> {candles[-1]['time']}"
    )
    print()

    trades = evaluate(candles)

    summarize(
        trades,
        "LOCKED VALIDATION RESULT",
    )


if __name__ == "__main__":
    main()
