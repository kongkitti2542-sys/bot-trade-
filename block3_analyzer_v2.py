from validate_atr_expansion_ema50 import fetch_closed_candles
from block3_analyzer_v1 import build_trade_records, split_blocks


def main():
    print("=" * 72)
    print("BLOCK 3 ANALYZER V2")
    print("=" * 72)
    print("Purpose: inspect every Block 3 trade")
    print("Mode   : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)
    blocks = split_blocks(records)

    if len(blocks) < 3:
        print("Block 3 not available.")
        return

    block3 = blocks[2]

    print(f"Candles            : {len(candles)}")
    print(f"Total Trades       : {len(records)}")
    print(f"Block 3 Trades     : {len(block3)}")
    print()

    cumulative = 0.0

    print(
        f"{'#':<4}"
        f"{'TIME':<24}"
        f"{'NET':>10}"
        f"{'CUM':>10}"
        f"{'ATR EXP':>10}"
        f"{'R/ATR':>10}"
        f"{'RV':>10}"
        f"{'EMA50':>10}"
    )

    print("-" * 88)

    for number, trade in enumerate(block3, start=1):
        cumulative += trade["net"]

        print(
            f"{number:<4}"
            f"{str(trade['time']):<24}"
            f"{trade['net']:>9.3%}"
            f"{cumulative:>9.3%}"
            f"{trade['expansion_ratio']:>10.3f}"
            f"{trade['range_atr_ratio']:>10.3f}"
            f"{trade['relative_volume']:>10.3f}"
            f"{trade['ema50_distance']:>9.3%}"
        )

    print()
    print("=" * 72)
    print("BLOCK 3 CONTRIBUTION")
    print("=" * 72)

    total_net = sum(t["net"] for t in block3)
    positive = [t for t in block3 if t["net"] > 0]
    negative = [t for t in block3 if t["net"] <= 0]

    print(f"Total Net          : {total_net:+.4%}")
    print(f"Winners            : {len(positive)}")
    print(f"Losers             : {len(negative)}")

    print()
    print("WINNER CONTRIBUTION")
    print("-" * 72)

    for t in sorted(positive, key=lambda x: x["net"], reverse=True):
        contribution = (
            t["net"] / total_net
            if total_net != 0
            else 0.0
        )

        print(
            f"{str(t['time']):<24}"
            f"NET={t['net']:+.3%} "
            f"Contribution={contribution:.2%}"
        )

    print()
    print("TOP 3 WINNERS")
    print("-" * 72)

    top3 = sorted(
        positive,
        key=lambda x: x["net"],
        reverse=True,
    )[:3]

    top3_net = sum(t["net"] for t in top3)

    print(f"Top 3 Net          : {top3_net:+.4%}")
    print(
        f"Top 3 Share        : "
        f"{top3_net / total_net:.2%}"
        if total_net != 0
        else "Top 3 Share        : N/A"
    )

    print()
    print("TOP 5 WINNERS")
    print("-" * 72)

    top5 = sorted(
        positive,
        key=lambda x: x["net"],
        reverse=True,
    )[:5]

    top5_net = sum(t["net"] for t in top5)

    print(f"Top 5 Net          : {top5_net:+.4%}")
    print(
        f"Top 5 Share        : "
        f"{top5_net / total_net:.2%}"
        if total_net != 0
        else "Top 5 Share        : N/A"
    )


if __name__ == "__main__":
    main()
