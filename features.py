from data import get_closed_candles


def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:
        value = (price - value) * multiplier + value

    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    relative_strength = avg_gain / avg_loss

    return 100 - (100 / (1 + relative_strength))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        previous_close = previous["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        true_ranges.append(true_range)

    return sum(true_ranges[-period:]) / period


def bollinger(candles, period=20, deviations=2):
    closes = [c["close"] for c in candles]

    if len(closes) < period:
        return None

    window = closes[-period:]

    middle = sum(window) / period

    variance = sum(
        (price - middle) ** 2
        for price in window
    ) / period

    standard_deviation = variance ** 0.5

    upper = middle + deviations * standard_deviation
    lower = middle - deviations * standard_deviation

    if middle != 0:
        width = (upper - lower) / middle
    else:
        width = 0

    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "width": width
    }


def relative_volume(candles, period=20):
    volumes = [c["volume"] for c in candles]

    if len(volumes) < period + 1:
        return None

    average_volume = sum(volumes[-period-1:-1]) / period

    if average_volume == 0:
        return 0

    current_volume = volumes[-1]

    return current_volume / average_volume


def price_structure(candles, lookback=5):
    if len(candles) < lookback * 2:
        return None

    previous = candles[-lookback * 2:-lookback]
    current = candles[-lookback:]

    previous_high = max(c["high"] for c in previous)
    previous_low = min(c["low"] for c in previous)

    current_high = max(c["high"] for c in current)
    current_low = min(c["low"] for c in current)

    higher_high = current_high > previous_high
    higher_low = current_low > previous_low

    lower_high = current_high < previous_high
    lower_low = current_low < previous_low

    if higher_high and higher_low:
        structure = "BULLISH"

    elif lower_high and lower_low:
        structure = "BEARISH"

    else:
        structure = "MIXED"

    return {
        "higher_high": higher_high,
        "higher_low": higher_low,
        "lower_high": lower_high,
        "lower_low": lower_low,
        "structure": structure
    }


def calculate_features(candles):
    closes = [c["close"] for c in candles]

    current_price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    rsi14 = rsi(closes, 14)

    atr14 = atr(candles, 14)

    bb = bollinger(candles, 20, 2)

    rel_volume = relative_volume(candles, 20)

    structure = price_structure(candles, 5)

    if ema20 and ema50 and ema200:
        if ema20 > ema50 > ema200:
            trend = "UP"

        elif ema20 < ema50 < ema200:
            trend = "DOWN"

        else:
            trend = "MIXED"
    else:
        trend = "UNKNOWN"

    return {
        "time": candles[-1]["time"],
        "close": current_price,

        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,

        "trend": trend,

        "rsi14": rsi14,

        "atr14": atr14,

        "bollinger": bb,

        "relative_volume": rel_volume,

        "structure": structure,
    }


if __name__ == "__main__":
    candles = get_closed_candles(
        symbol="BTCUSDT",
        interval="5m",
        limit=250
    )

    features = calculate_features(candles)

    print()
    print("BTC/USDT - FEATURE ENGINE")
    print("=" * 60)

    print(f"Time:  {features['time']}")
    print(f"Price: {features['close']:.2f}")

    print()
    print("TREND")
    print("-" * 60)
    print(f"EMA20:  {features['ema20']:.2f}")
    print(f"EMA50:  {features['ema50']:.2f}")
    print(f"EMA200: {features['ema200']:.2f}")
    print(f"Trend:  {features['trend']}")

    print()
    print("MOMENTUM")
    print("-" * 60)
    print(f"RSI14: {features['rsi14']:.2f}")

    print()
    print("VOLATILITY")
    print("-" * 60)
    print(f"ATR14: {features['atr14']:.2f}")

    bb = features["bollinger"]

    print(f"BB Upper:  {bb['upper']:.2f}")
    print(f"BB Middle: {bb['middle']:.2f}")
    print(f"BB Lower:  {bb['lower']:.2f}")
    print(f"BB Width:  {bb['width']:.4f}")

    print()
    print("VOLUME")
    print("-" * 60)
    print(f"Relative Volume: {features['relative_volume']:.2f}x")

    print()
    print("PRICE STRUCTURE")
    print("-" * 60)

    structure = features["structure"]

    print(f"Structure:   {structure['structure']}")
    print(f"Higher High: {structure['higher_high']}")
    print(f"Higher Low:  {structure['higher_low']}")
    print(f"Lower High:  {structure['lower_high']}")
    print(f"Lower Low:   {structure['lower_low']}")
