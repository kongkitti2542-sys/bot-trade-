from validate_atr_expansion_ema50 import (
    fetch_closed_candles,
    calculate_atr,
    calculate_ema,
    calculate_relative_volume,
    ATR_PERIOD,
    ATR_LOOKBACK,
    ATR_EXPANSION_MULTIPLIER,
    RV_THRESHOLD,
)

print("=" * 72)
print("LIVE SIGNAL AUDIT V2")
print("=" * 72)

candles = fetch_closed_candles()

print(f"Candles : {len(candles)}")
print(f"Latest  : {candles[-1]['time']}")
print()

atr = calculate_atr(candles)
closes = [c["close"] for c in candles]
ema50 = calculate_ema(closes, 50)
rv = calculate_relative_volume(candles)

start = max(ATR_PERIOD + ATR_LOOKBACK, 50)

signals = []

print("SCANNING LAST 100 CLOSED CANDLES")
print("-" * 72)

for i in range(max(start, len(candles) - 100), len(candles)):

    if atr[i] is None or ema50[i] is None or rv[i] is None:
        continue

    recent_atr = [
        atr[j]
        for j in range(i - ATR_LOOKBACK, i)
        if atr[j] is not None
    ]

    if len(recent_atr) != ATR_LOOKBACK:
        continue

    avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
    expansion_ratio = atr[i] / avg_recent_atr
    candle_range = candles[i]["high"] - candles[i]["low"]

    bullish = candles[i]["close"] > candles[i]["open"]
    higher_close = candles[i]["close"] > candles[i - 1]["close"]
    volume_confirmed = rv[i] >= RV_THRESHOLD
    above_ema50 = candles[i]["close"] > ema50[i]
    range_ok = candle_range >= atr[i]
    expansion = expansion_ratio >= ATR_EXPANSION_MULTIPLIER

    passed = (
        expansion
        and range_ok
        and bullish
        and higher_close
        and volume_confirmed
        and above_ema50
    )

    if passed:
        signals.append(candles[i]["time"])

        print()
        print(">>> LIVE CANDIDATE FOUND")
        print(f"Time          : {candles[i]['time']}")
        print(f"Close         : {candles[i]['close']:.2f}")
        print(f"ATR           : {atr[i]:.4f}")
        print(f"ATR Expansion : {expansion_ratio:.3f}x")
        print(f"Relative Vol  : {rv[i]:.3f}")
        print(f"EMA50         : {ema50[i]:.2f}")
        print(f"Candle Range  : {candle_range:.2f}")
        print(f"Bullish       : {bullish}")
        print(f"Higher Close  : {higher_close}")
        print()

print()
print("=" * 72)
print("RESULT")
print("=" * 72)

if signals:
    print(f"Live candidates found : {len(signals)}")
    print(f"Latest candidate      : {signals[-1]}")
else:
    print("Live candidates found : 0")
    print("No candle in the last 100 closed candles passed all conditions.")

print()
print("Latest 5 candles diagnostic")
print("-" * 72)

for i in range(len(candles) - 5, len(candles)):

    recent_atr = [
        atr[j]
        for j in range(i - ATR_LOOKBACK, i)
        if atr[j] is not None
    ]

    if (
        atr[i] is None
        or ema50[i] is None
        or rv[i] is None
        or len(recent_atr) != ATR_LOOKBACK
    ):
        print(f"{candles[i]['time']} | indicators incomplete")
        continue

    avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
    expansion_ratio = atr[i] / avg_recent_atr
    candle_range = candles[i]["high"] - candles[i]["low"]

    bullish = candles[i]["close"] > candles[i]["open"]
    higher_close = candles[i]["close"] > candles[i - 1]["close"]
    volume_confirmed = rv[i] >= RV_THRESHOLD
    above_ema50 = candles[i]["close"] > ema50[i]
    range_ok = candle_range >= atr[i]
    expansion = expansion_ratio >= ATR_EXPANSION_MULTIPLIER

    print(
        f"{candles[i]['time']} | "
        f"ATRx={expansion_ratio:.3f} | "
        f"RV={rv[i]:.3f} | "
        f"Range/ATR={candle_range/atr[i]:.3f} | "
        f"Bull={bullish} | "
        f"Higher={higher_close} | "
        f"EMA50={above_ema50} | "
        f"PASS={expansion and range_ok and bullish and higher_close and volume_confirmed and above_ema50}"
    )

print("=" * 72)
