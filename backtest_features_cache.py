from features import calculate_features


def build_feature_cache(candles, warmup=200):
    """
    Precompute features once for every candle after warmup.

    This preserves the existing calculate_features() logic.
    It is a research-performance layer only.
    """

    cache = {}

    for index in range(warmup, len(candles)):
        # Keep the same history boundary used by the original backtest.
        history = candles[:index + 1]

        cache[index] = calculate_features(history)

        if index % 5000 == 0:
            print(f"Feature cache: {index}/{len(candles)}")

    return cache


if __name__ == "__main__":
    from backtest_data_100k import (
        get_historical_candles_100k,
        validate_candles,
    )

    SYMBOL = "BTCUSDT"
    INTERVAL = "5m"
    CANDLES_NEEDED = 100_000

    print("=" * 70)
    print("BUILDING 100K FEATURE CACHE")
    print("=" * 70)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:     {len(candles)}")
    print(f"Validation:  {valid}")
    print(f"Reason:      {reason}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    cache = build_feature_cache(candles)

    print()
    print("=" * 70)
    print("FEATURE CACHE COMPLETE")
    print("=" * 70)
    print(f"Candles:       {len(candles)}")
    print(f"Cached rows:   {len(cache)}")

    if cache:
        first_index = min(cache)
        last_index = max(cache)

        print(f"First index:   {first_index}")
        print(f"Last index:    {last_index}")

        first_features = cache[first_index]

        print()
        print("SAMPLE:")
        print(f"Time:          {first_features['time']}")
        print(f"Close:         {first_features['close']}")
        print(f"Trend:         {first_features['trend']}")
        print(f"RSI:           {first_features['rsi14']}")
        print(f"ATR:           {first_features['atr14']}")
