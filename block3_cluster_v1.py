from block3_analyzer_v1 import build_trade_records, split_blocks
from validate_atr_expansion_ema50 import fetch_closed_candles


def find_positive_clusters(records):
    clusters = []
    current = []

    for record in records:
        if record["net"] > 0:
            current.append(record)
        else:
            if current:
                clusters.append(current)
                current = []

    if current:
        clusters.append(current)

    return clusters


def print_cluster(index, cluster):
    total = sum(x["net"] for x in cluster)

    print(
        f"Cluster {index:<3}"
        f" Trades={len(cluster):<3}"
        f" Net={total:+.4%}"
        f" First={cluster[0]['time']}"
        f" Last={cluster[-1]['time']}"
    )

    for i, trade in enumerate(cluster, start=1):
        print(
            f"   {i:>2}. "
            f"{trade['time']}  "
            f"{trade['net']:+.3%}"
        )


def main():
    print("=" * 72)
    print("BLOCK 3 CLUSTER ANALYZER V1")
    print("=" * 72)
    print("Focus: profitable winning runs")
    print("Mode : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)
    blocks = split_blocks(records)

    block3 = blocks[2]

    print(f"Block 3 Trades     : {len(block3)}")
    print()

    clusters = find_positive_clusters(block3)

    print(f"Positive Clusters  : {len(clusters)}")
    print()

    for index, cluster in enumerate(clusters, start=1):
        print_cluster(index, cluster)
        print()

    print("=" * 72)
    print("CLUSTER SUMMARY")
    print("=" * 72)

    ranked = sorted(
        clusters,
        key=lambda c: sum(x["net"] for x in c),
        reverse=True,
    )

    total_net = sum(x["net"] for x in block3)

    for index, cluster in enumerate(ranked, start=1):
        cluster_net = sum(x["net"] for x in cluster)
        share = cluster_net / total_net if total_net else 0.0

        print(
            f"{index:>2}. "
            f"Trades={len(cluster):<3} "
            f"Net={cluster_net:+.4%} "
            f"Share={share:.2%}"
        )

    print()
    print("=" * 72)
    print("WINNING RUN TOTAL")
    print("=" * 72)

    positive_total = sum(
        x["net"]
        for x in block3
        if x["net"] > 0
    )

    print(f"Positive Trades    : {positive_total:+.4%}")
    print(f"Block 3 Net        : {total_net:+.4%}")
    print(
        f"Negative Trades    : "
        f"{sum(x['net'] for x in block3 if x['net'] <= 0):+.4%}"
    )


if __name__ == "__main__":
    main()
