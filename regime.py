from data import get_closed_candles
from features import calculate_features


def detect_regime(features):
    price = features["close"]

    ema20 = features["ema20"]
    ema50 = features["ema50"]
    ema200 = features["ema200"]

    rsi = features["rsi14"]
    atr = features["atr14"]

    bb = features["bollinger"]
    volume = features["relative_volume"]

    structure = features["structure"]

    if not all([
        ema20,
        ema50,
        ema200,
        rsi,
        atr,
        bb,
        volume,
        structure
    ]):
        return "INSUFFICIENT_DATA"

    # --------------------------------
    # 1. Extreme volatility
    # --------------------------------

    atr_percent = atr / price

    if atr_percent > 0.015:
        return "HIGH_VOLATILITY"

    # --------------------------------
    # 2. Strong bullish trend
    # --------------------------------

    if (
        price > ema20 > ema50 > ema200
        and structure["structure"] == "BULLISH"
        and rsi >= 50
        and volume >= 0.8
    ):
        return "TREND_UP"

    # --------------------------------
    # 3. Strong bearish trend
    # --------------------------------

    if (
        price < ema20 < ema50 < ema200
        and structure["structure"] == "BEARISH"
        and rsi <= 50
        and volume >= 0.8
    ):
        return "TREND_DOWN"

    # --------------------------------
    # 4. Potential bullish breakout
    # --------------------------------

    if (
        price > bb["upper"]
        and volume >= 1.5
        and structure["structure"] == "BULLISH"
    ):
        return "BREAKOUT_UP"

    # --------------------------------
    # 5. Potential bearish breakout
    # --------------------------------

    if (
        price < bb["lower"]
        and volume >= 1.5
        and structure["structure"] == "BEARISH"
    ):
        return "BREAKOUT_DOWN"

    # --------------------------------
    # 6. Range / sideways
    # --------------------------------

    if (
        abs(ema20 - ema50) / price < 0.001
        and 40 <= rsi <= 60
        and volume < 1.0
    ):
        return "RANGE"

    # --------------------------------
    # 7. Everything else
    # --------------------------------

    return "UNCERTAIN"


if __name__ == "__main__":

    candles = get_closed_candles(
        symbol="BTCUSDT",
        interval="5m",
        limit=250
    )

    features = calculate_features(candles)

    regime = detect_regime(features)

    print()
    print("BTC/USDT - MARKET REGIME")
    print("=" * 60)

    print(f"Price: {features['close']:.2f}")
    print(f"EMA20: {features['ema20']:.2f}")
    print(f"EMA50: {features['ema50']:.2f}")
    print(f"EMA200: {features['ema200']:.2f}")
    print(f"RSI: {features['rsi14']:.2f}")
    print(f"Relative Volume: {features['relative_volume']:.2f}x")

    print()
    print(f"REGIME: {regime}")
