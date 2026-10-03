from statistics import mean, median
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
    FEE_PER_SIDE,
    SLIPPAGE_PER_SIDE,
)


def build_trade_records(candles):
    atr = calculate_atr(candles)
    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, 50)
    relative_volume = calculate_relative_volume(candles)

    start = max(ATR_PERIOD + ATR_LOOKBACK, 50)
    end = len(candles) - HORIZON - 1

    records = []

    for i in range(start, end + 1):
        if atr[i] is None or ema50[i] is None or relative_volume[i] is None:
            continue

        recent_atr = [
            atr[j]
            for j in range(i - ATR_LOOKBACK, i)
            if atr[j] is not None
        ]

        if len(recent_atr) != ATR_LOOKBACK:
            continue

        avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK

        expansion_ratio = atr[i] / avg_recent_atr if avg_recent_atr > 0 else 0.0

        candle_range = candles[i]["high"] - candles[i]["low"]
        range_atr_ratio = (
            candle_range / atr[i]
            if atr[i] > 0
            else 0.0
        )

        bullish = candles[i]["close"] > candles[i]["open"]
        higher_close = candles[i]["close"] > candles[i - 1]["close"]
        volume_confirmed = relative_volume[i] >= RV_THRESHOLD
        above_ema50 = candles[i]["close"] > ema50[i]

        if not (
            expansion_ratio >= ATR_EXPANSION_MULTIPLIER
            and range_atr_ratio >= 1.0
            and bullish
            and higher_close
            and volume_confirmed
            and above_ema50
        ):
            continue

        entry = candles[i + 1]["open"]
        exit_price = candles[i + 1 + HORIZON]["close"]

        gross_return = (exit_price / entry) - 1.0
        total_cost = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE
        net_return = gross_return - total_cost

        ema_distance = (
            (candles[i]["close"] / ema50[i]) - 1.0
            if ema50[i] > 0
            else 0.0
        )

        records.append(
            {
                "time": candles[i]["time"],
                "net": net_return,
                "gross": gross_return,
                "atr": atr[i],
                "atr_avg": avg_recent_atr,
                "expansion_ratio": expansion_ratio,
                "range_atr_ratio": range_atr_ratio,
                "relative_volume": relative_volume[i],
                "ema50_distance": ema_distance,
                "entry": entry,
                "exit": exit_price,
            }
        )

    return records


def split_blocks(records):
    n = len(records)
    blocks = []

    for i in range(4):
        start = (n * i) // 4
        end = (n * (i + 1)) // 4
        blocks.append(records[start:end])

    return blocks


def stats(records):
    if not records:
        return {
            "n": 0,
            "win_rate": 0.0,
            "net": 0.0,
            "avg": 0.0,
            "median": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "best": 0.0,
            "worst": 0.0,
            "pf": 0.0,
        }

    nets = [r["net"] for r in records]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "n": len(records),
        "win_rate": len(wins) / len(nets),
        "net": sum(nets),
        "avg": mean(nets),
        "median": median(nets),
        "avg_win": mean(wins) if wins else 0.0,
        "avg_loss": mean(losses) if losses else 0.0,
        "best": max(nets),
        "worst": min(nets),
        "pf": (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf")
        ),
    }


def feature_stats(records, key):
    values = [r[key] for r in records]

    if not values:
        return 0.0, 0.0

    return mean(values), median(values)


def max_loss_streak(records):
    current = 0
    maximum = 0

    for record in records:
        if record["net"] <= 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0

    return maximum


def print_block(number, records):
    s = stats(records)

    expansion_mean, expansion_median = feature_stats(
        records, "expansion_ratio"
    )
    range_mean, range_median = feature_stats(
        records, "range_atr_ratio"
    )
    rv_mean, rv_median = feature_stats(
        records, "relative_volume"
    )
    ema_mean, ema_median = feature_stats(
        records, "ema50_distance"
    )

    print()
    print("=" * 72)
    print(f"BLOCK {number}")
    print("=" * 72)

    print(f"Trades             : {s['n']}")
    print(f"Net Return         : {s['net']:+.4%}")
    print(f"Win Rate           : {s['win_rate']:.2%}")
    print(f"Average Trade      : {s['avg']:+.4%}")
    print(f"Median Trade       : {s['median']:+.4%}")
    print(f"Average Win        : {s['avg_win']:+.4%}")
    print(f"Average Loss       : {s['avg_loss']:+.4%}")
    print(f"Best Trade         : {s['best']:+.4%}")
    print(f"Worst Trade        : {s['worst']:+.4%}")
    print(f"Profit Factor      : {s['pf']:.3f}")
    print(f"Max Loss Streak    : {max_loss_streak(records)}")

    print()
    print("ENTRY FEATURES")
    print("-" * 72)

    print(
        f"ATR Expansion      : "
        f"mean={expansion_mean:.3f} "
        f"median={expansion_median:.3f}"
    )

    print(
        f"Range / ATR        : "
        f"mean={range_mean:.3f} "
        f"median={range_median:.3f}"
    )

    print(
        f"Relative Volume    : "
        f"mean={rv_mean:.3f} "
        f"median={rv_median:.3f}"
    )

    print(
        f"Close vs EMA50     : "
        f"mean={ema_mean:+.3%} "
        f"median={ema_median:+.3%}"
    )


def main():
    print("=" * 72)
    print("BLOCK 3 ANALYZER V1")
    print("=" * 72)
    print("Purpose: identify characteristics of profitable POT-growth periods")
    print("Source: validate_atr_expansion_ema50.py")
    print("Mode  : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)

    print(f"Candles            : {len(candles)}")
    print(f"Trade Records      : {len(records)}")

    if not records:
        print("No qualifying records.")
        return

    blocks = split_blocks(records)

    for number, block in enumerate(blocks, start=1):
        print_block(number, block)

    print()
    print("=" * 72)
    print("BLOCK 3 VS OTHER BLOCKS")
    print("=" * 72)

    b1 = stats(blocks[0])
    b2 = stats(blocks[1])
    b3 = stats(blocks[2])
    b4 = stats(blocks[3])

    print(
        f"{'BLOCK':<10}"
        f"{'N':>6}"
        f"{'NET':>12}"
        f"{'WR':>10}"
        f"{'AVG':>12}"
        f"{'MEDIAN':>12}"
        f"{'PF':>10}"
    )

    for number, s in enumerate([b1, b2, b3, b4], start=1):
        print(
            f"{number:<10}"
            f"{s['n']:>6}"
            f"{s['net']:>11.2%}"
            f"{s['win_rate']:>9.2%}"
            f"{s['avg']:>11.2%}"
            f"{s['median']:>11.2%}"
            f"{s['pf']:>10.3f}"
        )

    print()
    print("NOTE")
    print("-" * 72)
    print("This analyzer does not modify the strategy.")
    print("It only investigates why the historical trade stream grew POT.")
    print("It does not establish future profitability.")


if __name__ == "__main__":
    main()
