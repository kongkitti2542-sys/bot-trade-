from backtest_data_100k import get_historical_candles_100k, validate_candles
from research_data_cache import save_candles


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100000


def main():
    print("=" * 70)
    print("BUILD RESEARCH DATA CACHE")
    print("=" * 70)
    print(f"Symbol:  {SYMBOL}")
    print(f"Interval: {INTERVAL}")
    print(f"Target:  {CANDLES_NEEDED:,} candles")
    print()

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    print(f"Downloaded: {len(candles):,} candles")

    validation = validate_candles(candles)

    print(f"Validation: {validation}")

    if not validation["valid"]:
        raise RuntimeError(
            f"Dataset validation failed: {validation['reason']}"
        )

    path = save_candles(
        candles,
        "btc_usdt_5m_100k.json",
    )

    print()
    print(f"Cache saved: {path}")
    print(f"Cached candles: {len(candles):,}")


if __name__ == "__main__":
    main()
