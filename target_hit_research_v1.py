from datetime import timedelta

from research_data_cache import load_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import ATR_STOP_MULTIPLIER


TARGETS = [0.05, 0.10]
HORIZONS_HOURS = [12, 24, 48]

FIVE_MINUTES_PER_4H = 48


def aggregate_4h(candles):
    buckets = {}

    for candle in candles:
        ts = candle["time"]
        bucket_hour = (ts.hour // 4) * 4
        bucket_start = ts.replace(
            hour=bucket_hour,
            minute=0,
            second=0,
            microsecond=0,
        )

        buckets.setdefault(bucket_start, []).append(candle)

    result = []

    for bucket_start in sorted(buckets):
        bucket = sorted(
            buckets[bucket_start],
            key=lambda x: x["time"],
        )

        if len(bucket) != FIVE_MINUTES_PER_4H:
            continue

        expected = [
            bucket_start + timedelta(minutes=5 * i)
            for i in range(FIVE_MINUTES_PER_4H)
        ]

        actual = [c["time"] for c in bucket]

        if actual != expected:
            continue

        result.append(
            {
                "time": bucket_start,
                "open": bucket[0]["open"],
                "high": max(c["high"] for c in bucket),
                "low": min(c["low"] for c in bucket),
                "close": bucket[-1]["close"],
                "volume": sum(c["volume"] for c in bucket),
            }
        )

    return result


def build_entries(candles):
    engine = IncrementalFeatures()
    entries = []

    for index, candle in enumerate(candles):
        features = engine.update(candle)

        if index < 200:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] not in ("BUY", "SELL"):
            continue

        entries.append(
            {
                "index": index,
                "time": candle["time"],
                "side": decision["signal"],
                "entry_price": features["close"],
                "score": decision["score"],
                "confidence": decision["confidence"],
                "regime": regime,
                "atr14": features["atr14"],
            }
        )

    return entries


def evaluate_entry(entry, candles, target, horizon_hours):
    entry_index = entry["index"]
    entry_price = entry["entry_price"]
    side = entry["side"]
    atr = entry["atr14"]

    max_bars = horizon_hours // 4

    end_index = min(
        entry_index + max_bars,
        len(candles) - 1,
    )

    target_price = (
        entry_price * (1 + target)
        if side == "BUY"
        else entry_price * (1 - target)
    )

    stop_distance = atr * ATR_STOP_MULTIPLIER

    stop_price = (
        entry_price - stop_distance
        if side == "BUY"
        else entry_price + stop_distance
    )

    for i in range(entry_index + 1, end_index + 1):
        candle = candles[i]

        if side == "BUY":
            target_hit = candle["high"] >= target_price
            stop_hit = candle["low"] <= stop_price
        else:
            target_hit = candle["low"] <= target_price
            stop_hit = candle["high"] >= stop_price

        # If both are touched inside the same 4H candle,
        # OHLC data cannot establish which happened first.
        # Treat it as AMBIGUOUS rather than guessing.
        if target_hit and stop_hit:
            return "AMBIGUOUS", i, candle["time"]

        if target_hit:
            return "TARGET_REACHED", i, candle["time"]

        if stop_hit:
            return "STOP_LOSS", i, candle["time"]

    if end_index < entry_index + max_bars:
        return "END_OF_DATA", end_index, candles[end_index]["time"]

    return "TIMEOUT", end_index, candles[end_index]["time"]


def main():
    print("=" * 72)
    print("TARGET-HIT RESEARCH V1")
    print("=" * 72)

    source = load_candles()
    candles = aggregate_4h(source)

    print(f"Source 5m candles : {len(source):,}")
    print(f"Complete 4H bars  : {len(candles):,}")

    entries = build_entries(candles)

    print(f"Strategy entries  : {len(entries):,}")
    print()

    for side in ("BUY", "SELL", "ALL"):
        selected = [
            e for e in entries
            if side == "ALL" or e["side"] == side
        ]

        print("-" * 72)
        print(f"SIDE: {side}")
        print("-" * 72)

        for target in TARGETS:
            for horizon in HORIZONS_HOURS:
                results = [
                    evaluate_entry(
                        entry,
                        candles,
                        target,
                        horizon,
                    )[0]
                    for entry in selected
                ]

                target_hits = results.count("TARGET_REACHED")
                stop_loss = results.count("STOP_LOSS")
                timeout = results.count("TIMEOUT")
                ambiguous = results.count("AMBIGUOUS")
                end_data = results.count("END_OF_DATA")

                total = len(results)

                hit_rate = (
                    target_hits / total * 100
                    if total
                    else 0.0
                )

                print(
                    f"Target +{target * 100:.0f}% | "
                    f"{horizon:2d}H | "
                    f"N {total:3d} | "
                    f"Hit {target_hits:3d} | "
                    f"HitRate {hit_rate:6.2f}% | "
                    f"Stop {stop_loss:3d} | "
                    f"Ambig {ambiguous:3d} | "
                    f"Timeout {timeout:3d} | "
                    f"EndData {end_data:3d}"
                )

        print()


if __name__ == "__main__":
    main()
