import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates

OUTPUT_FILE = Path(
    "money_machine_v2/research/big_winner_preservation_audit_v1.json"
)

STARTING_POT_THB = 1500.0
BIG_WINNER_MFE = 0.01
GIVEBACK_LEVELS = [0.002, 0.003, 0.005]

HORIZON = 20


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])

        if entry_index is None:
            continue

        end_index = min(
            entry_index + HORIZON,
            len(candles) - 1,
        )

        rows.append({
            "candidate": candidate,
            "entry_index": entry_index,
            "end_index": end_index,
        })

    return sorted(
        rows,
        key=lambda r: r["candidate"]["entry_time"],
    )


def analyze_trade(record, candles):
    candidate = record["candidate"]
    entry = float(candidate["entry"])

    peak = entry
    peak_index = record["entry_index"]

    observations = []

    for i in range(
        record["entry_index"] + 1,
        record["end_index"] + 1,
    ):
        candle = candles[i]

        peak_before = peak

        if candle["high"] > peak:
            peak = candle["high"]
            peak_index = i

        mfe = peak / entry - 1.0

        giveback = (
            (peak - candle["close"]) / peak
            if peak > 0
            else 0.0
        )

        observations.append({
            "index": i,
            "time": candle["time"].isoformat(),
            "close": candle["close"],
            "peak": peak,
            "mfe_pct": mfe * 100.0,
            "giveback_pct": giveback * 100.0,
        })

    max_mfe = max(
        (x["mfe_pct"] for x in observations),
        default=0.0,
    )

    row = {
        "entry_time": candidate["entry_time"].isoformat(),
        "entry": entry,
        "max_mfe_pct": max_mfe,
        "big_winner": max_mfe >= BIG_WINNER_MFE * 100.0,
        "giveback_events": {},
    }

    for level in GIVEBACK_LEVELS:
        level_pct = level * 100.0

        hits = [
            x for x in observations
            if x["mfe_pct"] >= BIG_WINNER_MFE * 100.0
            and x["giveback_pct"] >= level_pct
        ]

        if not hits:
            row["giveback_events"][str(level_pct)] = {
                "hit": False,
            }
            continue

        first = hits[0]
        first_index = first["index"]

        future = candles[
            first_index + 1:
            record["end_index"] + 1
        ]

        future_highs = [
            c["high"] for c in future
        ]

        future_closes = [
            c["close"] for c in future
        ]

        post_giveback_high_pct = (
            max(future_highs) / entry - 1.0
            if future_highs
            else 0.0
        )

        post_giveback_close_pct = (
            max(future_closes) / entry - 1.0
            if future_closes
            else 0.0
        )

        row["giveback_events"][str(level_pct)] = {
            "hit": True,
            "time": first["time"],
            "mfe_at_hit_pct": first["mfe_pct"],
            "giveback_at_hit_pct": first["giveback_pct"],
            "bars_remaining": record["end_index"] - first_index,
            "post_giveback_max_high_pct":
                post_giveback_high_pct * 100.0,
            "post_giveback_max_close_pct":
                post_giveback_close_pct * 100.0,
        }

    return row


def summarize(rows):
    winners = [
        r for r in rows
        if r["big_winner"]
    ]

    summary = {
        "all_trades": len(rows),
        "big_winners": len(winners),
        "big_winner_rate_pct": (
            len(winners) / len(rows) * 100.0
            if rows else 0.0
        ),
        "giveback_levels": {},
    }

    for level in GIVEBACK_LEVELS:
        key = str(level * 100.0)

        hits = [
            r["giveback_events"][key]
            for r in winners
            if r["giveback_events"][key]["hit"]
        ]

        continuation = [
            x["post_giveback_max_high_pct"]
            for x in hits
            if x["bars_remaining"] > 0
        ]

        summary["giveback_levels"][key] = {
            "hits": len(hits),
            "avg_post_giveback_max_high_pct": (
                sum(continuation) / len(continuation)
                if continuation else 0.0
            ),
            "max_post_giveback_max_high_pct": (
                max(continuation)
                if continuation else 0.0
            ),
            "still_had_upside_0_50pct": sum(
                x >= 0.50
                for x in continuation
            ),
            "still_had_upside_1_00pct": sum(
                x >= 1.00
                for x in continuation
            ),
        }

    return summary


def main():
    print("=" * 72)
    print("BIG WINNER PRESERVATION AUDIT V1")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Candles      : {WINDOW_30D_CANDLES:,}")
    print(f"Big Winner   : MFE >= {BIG_WINNER_MFE * 100:.2f}%")
    print("Lookahead    : BLOCKED")
    print("Profit Lock  : NOT USED")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)

    rows = [
        analyze_trade(record, candles)
        for record in records
    ]

    summary = summarize(rows)

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "horizon_bars": HORIZON,
            "big_winner_mfe_pct": BIG_WINNER_MFE * 100.0,
            "lookahead": False,
            "profit_lock_used": False,
        },
        "summary": summary,
        "trades": rows,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("RESULT")
    print("-" * 72)
    print(f"Candidates   : {len(rows)}")
    print(f"Big Winners  : {summary['big_winners']}")
    print(
        f"Winner Rate  : "
        f"{summary['big_winner_rate_pct']:.2f}%"
    )

    for level, data in summary["giveback_levels"].items():
        print(
            f"Giveback {level}% : "
            f"hits={data['hits']} "
            f"avg_future_high="
            f"{data['avg_post_giveback_max_high_pct']:.2f}% "
            f"max_future_high="
            f"{data['max_post_giveback_max_high_pct']:.2f}%"
        )

    print(f"Saved        : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
