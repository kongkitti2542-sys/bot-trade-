from validate_atr_expansion_ema50 import (
    fetch_closed_candles,
    calculate_atr,
    calculate_ema,
    calculate_relative_volume,
    ATR_PERIOD,
    ATR_LOOKBACK,
    ATR_EXPANSION_MULTIPLIER,
    RV_THRESHOLD,
    HORIZON,
)

print("=" * 72)
print("LIVE CANDIDATE AUDIT V1")
print("=" * 72)

candles = fetch_closed_candles()

print(f"Candles : {len(candles)}")
print(f"First   : {candles[0]['time']}")
print(f"Latest  : {candles[-1]['time']}")
print(f"Horizon : {HORIZON} bars")
print()

atr = calculate_atr(candles)
closes = [c["close"] for c in candles]
ema50 = calculate_ema(closes, 50)
rv = calculate_relative_volume(candles)

start = max(ATR_PERIOD + ATR_LOOKBACK, 50)
end = len(candles) - HORIZON - 1

print(f"Candidate scan range:")
print(f"Start index : {start}")
print(f"End index   : {end}")
print(f"Last index  : {len(candles) - 1}")
print()

print("LAST CANDLES / ELIGIBILITY")
print("-" * 72)

for i in range(max(0, len(candles) - 25), len(candles)):
    c = candles[i]

    eligible = start <= i <= end

    if not eligible:
        print(
            f"{c['time']} | index={i} | "
            f"ELIGIBLE=NO | reason=HORIZON_EXCLUDED"
        )
        continue

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
        print(
            f"{c['time']} | index={i} | "
            f"ELIGIBLE=YES | indicators=INCOMPLETE"
        )
        continue

    avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
    expansion_ratio = atr[i] / avg_recent_atr
    candle_range = c["high"] - c["low"]

    bullish = c["close"] > c["open"]
    higher_close = c["close"] > candles[i - 1]["close"]
    volume_confirmed = rv[i] >= RV_THRESHOLD
    above_ema50 = c["close"] > ema50[i]
    expansion = expansion_ratio >= ATR_EXPANSION_MULTIPLIER
    range_ok = candle_range >= atr[i]

    passed = (
        expansion
        and range_ok
        and bullish
        and higher_close
        and volume_confirmed
        and above_ema50
    )

    failed = []

    if not expansion:
        failed.append("ATR_EXPANSION")
    if not range_ok:
        failed.append("CANDLE_RANGE")
    if not bullish:
        failed.append("BEARISH")
    if not higher_close:
        failed.append("NOT_HIGHER_CLOSE")
    if not volume_confirmed:
        failed.append("LOW_VOLUME")
    if not above_ema50:
        failed.append("BELOW_EMA50")

    print(
        f"{c['time']} | index={i} | "
        f"PASS={passed} | "
        f"ATRx={expansion_ratio:.3f} | "
        f"RV={rv[i]:.3f} | "
        f"EMA50={ema50[i]:.2f} | "
        f"FAILED={','.join(failed) if failed else '-'}"
    )

print()
print("=" * 72)
print("LATEST ELIGIBLE CANDLE")
print("=" * 72)

c = candles[end]

print("Time :", c["time"])
print("Index:", end)

recent_atr = [
    atr[j]
    for j in range(end - ATR_LOOKBACK, end)
    if atr[j] is not None
]

avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
expansion_ratio = atr[end] / avg_recent_atr
candle_range = c["high"] - c["low"]

print(f"ATR expansion : {expansion_ratio:.3f}x")
print(f"Required      : {ATR_EXPANSION_MULTIPLIER:.3f}x")
print(f"Relative Vol  : {rv[end]:.3f}")
print(f"Required      : {RV_THRESHOLD:.3f}")
print(f"Close         : {c['close']:.2f}")
print(f"EMA50         : {ema50[end]:.2f}")
print(f"Candle Range  : {candle_range:.2f}")
print(f"ATR           : {atr[end]:.2f}")
print(f"Bullish       : {c['close'] > c['open']}")
print(f"Higher Close  : {c['close'] > candles[end-1]['close']}")

print()
print("IMPORTANT")
print("-" * 72)
print(
    "The live watcher requires candidate.signal_time == latest closed candle."
)
print(
    "This adapter excludes the final HORIZON candles from candidate scanning."
)
print(
    "Therefore this audit checks whether the stale-candidate behavior is"
)
print(
    "structurally caused by the backtest horizon rule."
)
print("=" * 72)
