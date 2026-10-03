"""
Groq Feature Discovery V4

Research-only discovery layer.

Goal:
- Analyze all Money Maker #1 candidates locally.
- Group candidates by their REAL adapter features.
- Select a deterministic, feature-diverse AI sample.
- Ask Groq to judge only the selected sample.
- Compare AI PASS/WAIT with historical outcomes and feature groups.

This file does NOT modify:
- Core
- Money Maker #1 adapter
- Risk
- PaperTrader
- Position Manager
- Groq Judge
- data.py
- V2
- V3
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from money_maker_01_adapter_v1 import find_candidates
from groq_judge_v1 import judge, remaining_calls


SYMBOL = "BTCUSDT"
INTERVAL = "5m"

CANDLE_LIMIT = 100_000
BINANCE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_PAGE_LIMIT = 1000

AI_SAMPLE_SIZE = int(
    os.environ.get("GROQ_RESEARCH_SAMPLE_SIZE", "24")
)

OUTPUT_FILE = Path(
    "research_groq_feature_discovery_v4_results.json"
)

RESEARCH_VERSION = "GROQ_FEATURE_DISCOVERY_V4"


def fetch_closed_candles_paginated(symbol, interval, limit):
    raw_candles = []
    end_time = None

    while len(raw_candles) < limit + 1:
        page_limit = min(
            BINANCE_PAGE_LIMIT,
            limit + 1 - len(raw_candles),
        )

        params = [
            f"symbol={symbol}",
            f"interval={interval}",
            f"limit={page_limit}",
        ]

        if end_time is not None:
            params.append(f"endTime={end_time}")

        url = BINANCE_URL + "?" + "&".join(params)

        request = Request(
            url,
            headers={
                "User-Agent": "personal-trading-bot-research/1.0",
            },
            method="GET",
        )

        with urlopen(request, timeout=15) as response:
            page = json.loads(
                response.read().decode("utf-8")
            )

        if not page:
            break

        raw_candles.extend(page)

        oldest_open_time = page[0][0]
        end_time = oldest_open_time - 1

        if len(page) < page_limit:
            break

    unique = {
        candle[0]: candle
        for candle in raw_candles
    }

    ordered = [
        unique[key]
        for key in sorted(unique)
    ]

    if not ordered:
        return []

    ordered = ordered[:-1]
    ordered = ordered[-limit:]

    candles = []

    for candle in ordered:
        candles.append(
            {
                "time": datetime.fromtimestamp(
                    candle[0] / 1000,
                    tz=timezone.utc,
                ),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            }
        )

    return candles


def find_candle(candles, candle_time):
    for candle in candles:
        if candle["time"] == candle_time:
            return candle
    return None


def historical_return(candidate, candles):
    exit_candle = find_candle(
        candles,
        candidate["planned_exit_time"],
    )

    if exit_candle is None:
        return None

    entry = candidate["entry"]
    exit_price = exit_candle["close"]

    if candidate["signal"] == "BUY":
        return (exit_price - entry) / entry

    if candidate["signal"] == "SELL":
        return (entry - exit_price) / entry

    return None


def bucket(value, edges):
    """
    Return a deterministic numeric bucket.

    Example:
    bucket(1.4, [1.25, 1.5, 1.75])
    -> 1.25-1.50
    """
    previous = None

    for edge in edges:
        if value < edge:
            if previous is None:
                return f"<{edge}"
            return f"{previous}-{edge}"
        previous = edge

    if previous is None:
        return "ALL"

    return f">={previous}"


def feature_stratum(candidate):
    features = candidate["features"]

    atr_expansion = features[
        "atr_expansion_ratio"
    ]

    relative_volume = features[
        "relative_volume"
    ]

    ema_distance = features[
        "ema50_distance"
    ]

    return {
        "atr_expansion_bucket": bucket(
            atr_expansion,
            [1.5, 2.0, 2.5],
        ),
        "relative_volume_bucket": bucket(
            relative_volume,
            [1.5, 2.0, 3.0],
        ),
        "ema50_distance_bucket": bucket(
            ema_distance,
            [0.0025, 0.005, 0.01],
        ),
    }


def stratum_key(candidate):
    s = feature_stratum(candidate)

    return (
        s["atr_expansion_bucket"],
        s["relative_volume_bucket"],
        s["ema50_distance_bucket"],
    )


def build_local_records(candidates, candles):
    records = []

    for candidate in candidates:
        outcome = historical_return(
            candidate,
            candles,
        )

        features = candidate["features"]

        records.append(
            {
                "candidate": candidate,
                "signal_time": candidate[
                    "signal_time"
                ].isoformat(),
                "outcome_return": outcome,
                "win": (
                    outcome is not None
                    and outcome > 0
                ),
                "stratum": feature_stratum(
                    candidate
                ),
            }
        )

    return records


def local_summary(records):
    resolved = [
        r
        for r in records
        if r["outcome_return"]
        is not None
    ]

    returns = [
        r["outcome_return"]
        for r in resolved
    ]

    if not returns:
        return {
            "n": 0,
            "win_rate": 0.0,
            "sum_return": 0.0,
            "avg_return": 0.0,
        }

    return {
        "n": len(returns),
        "win_rate": (
            sum(
                1
                for r in returns
                if r > 0
            )
            / len(returns)
            * 100.0
        ),
        "sum_return": (
            sum(returns) * 100.0
        ),
        "avg_return": (
            sum(returns)
            / len(returns)
            * 100.0
        ),
    }


def stratum_summary(records):
    groups = defaultdict(list)

    for record in records:
        groups[
            str(record["stratum"])
        ].append(record)

    output = []

    for key, items in sorted(
        groups.items(),
        key=lambda x: x[0],
    ):
        returns = [
            x["outcome_return"]
            for x in items
            if x["outcome_return"]
            is not None
        ]

        if returns:
            output.append(
                {
                    "stratum": key,
                    "n": len(returns),
                    "win_rate": (
                        sum(
                            1
                            for r in returns
                            if r > 0
                        )
                        / len(returns)
                        * 100.0
                    ),
                    "sum_return": (
                        sum(returns)
                        * 100.0
                    ),
                    "avg_return": (
                        sum(returns)
                        / len(returns)
                        * 100.0
                    ),
                }
            )

    return output


def select_feature_diverse_sample(
    records,
    sample_size,
):
    """
    Select representatives across feature strata.

    First pass:
    one representative from each stratum.

    Remaining slots:
    distribute deterministically across strata
    according to chronological position.

    This is discovery sampling, not optimization.
    """

    if not records or sample_size <= 0:
        return []

    groups = defaultdict(list)

    for record in records:
        groups[
            str(record["stratum"])
        ].append(record)

    strata = sorted(groups)

    selected = []

    # One representative per stratum first.
    for key in strata:
        if len(selected) >= sample_size:
            break

        items = groups[key]

        middle = len(items) // 2

        selected.append(
            items[middle]
        )

    if len(selected) >= sample_size:
        return selected[:sample_size]

    selected_ids = {
        r["signal_time"]
        for r in selected
    }

    remaining = [
        r
        for r in records
        if r["signal_time"]
        not in selected_ids
    ]

    remaining_slots = (
        sample_size - len(selected)
    )

    if not remaining:
        return selected

    if remaining_slots >= len(remaining):
        return selected + remaining

    for i in range(remaining_slots):
        index = round(
            i * (len(remaining) - 1)
            / max(1, remaining_slots - 1)
        )

        candidate = remaining[index]

        if (
            candidate["signal_time"]
            not in selected_ids
        ):
            selected.append(candidate)
            selected_ids.add(
                candidate["signal_time"]
            )

    return selected[:sample_size]


def is_groq_rate_limited(ai):
    if ai.get("source") != "SAFE_FALLBACK":
        return False

    for reason in ai.get("reasons", []):
        if "Groq HTTP error: 429" in str(reason):
            return True

    return False


def ai_bucket(ai):
    if ai.get("source") == "GROQ":
        if ai.get("decision") == "PASS":
            return "GROQ_PASS"
        return "GROQ_WAIT"

    if ai.get("source") == "SAFE_FALLBACK":
        return "SAFE_FALLBACK"

    return "OTHER"


def ai_summary(results):
    groups = defaultdict(list)

    for result in results:
        groups[
            result["ai_bucket"]
        ].append(result)

    output = {}

    for key in (
        "GROQ_PASS",
        "GROQ_WAIT",
        "SAFE_FALLBACK",
        "OTHER",
    ):
        items = groups.get(key, [])

        returns = [
            x["outcome_return"]
            for x in items
            if x["outcome_return"]
            is not None
        ]

        if not returns:
            output[key] = {
                "n": 0,
                "win_rate": 0.0,
                "sum_return": 0.0,
                "avg_return": 0.0,
            }
            continue

        output[key] = {
            "n": len(returns),
            "win_rate": (
                sum(
                    1
                    for r in returns
                    if r > 0
                )
                / len(returns)
                * 100.0
            ),
            "sum_return": (
                sum(returns)
                * 100.0
            ),
            "avg_return": (
                sum(returns)
                / len(returns)
                * 100.0
            ),
        }

    return output


def ai_stratum_summary(results):
    groups = defaultdict(list)

    for result in results:
        groups[
            str(result["stratum"])
        ].append(result)

    output = []

    for key, items in sorted(
        groups.items(),
        key=lambda x: x[0],
    ):
        pass_items = [
            x
            for x in items
            if x["ai_bucket"]
            == "GROQ_PASS"
        ]

        wait_items = [
            x
            for x in items
            if x["ai_bucket"]
            == "GROQ_WAIT"
        ]

        returns = [
            x["outcome_return"]
            for x in items
            if x["outcome_return"]
            is not None
        ]

        output.append(
            {
                "stratum": key,
                "sample_n": len(items),
                "pass_n": len(pass_items),
                "wait_n": len(wait_items),
                "sample_win_rate": (
                    sum(
                        1
                        for r in returns
                        if r > 0
                    )
                    / len(returns)
                    * 100.0
                    if returns
                    else 0.0
                ),
                "sample_sum_return": (
                    sum(returns)
                    * 100.0
                    if returns
                    else 0.0
                ),
            }
        )

    return output


def main():
    print("=" * 72)
    print("GROQ FEATURE DISCOVERY V4")
    print("=" * 72)
    print(f"Symbol          : {SYMBOL}")
    print(f"Interval        : {INTERVAL}")
    print(
        f"Requested       : {CANDLE_LIMIT:,}"
    )
    print(
        f"AI sample size  : {AI_SAMPLE_SIZE:,}"
    )
    print("Execution       : NONE")
    print("Paper DB        : NOT USED")
    print("=" * 72)

    print(
        "Groq calls made today:",
        remaining_calls(),
    )

    print(
        "Fetching historical candles..."
    )

    try:
        candles = fetch_closed_candles_paginated(
            SYMBOL,
            INTERVAL,
            CANDLE_LIMIT,
        )
    except HTTPError as exc:
        print("RESULT: STOPPED")
        print(
            f"Reason: BINANCE_HTTP_ERROR_{exc.code}"
        )
        return
    except (
        URLError,
        TimeoutError,
    ) as exc:
        print("RESULT: STOPPED")
        print(
            "Reason: BINANCE_CONNECTION_ERROR_"
            f"{type(exc).__name__}"
        )
        return

    print(
        f"Actual candles returned: "
        f"{len(candles):,}"
    )

    if not candles:
        print("RESULT: STOPPED")
        print("Reason: NO_CANDLES")
        return

    print(
        "First candle:",
        candles[0]["time"],
    )
    print(
        "Last candle :",
        candles[-1]["time"],
    )

    candidates = find_candidates(
        candles
    )

    print(
        f"Candidates found: "
        f"{len(candidates)}"
    )

    print(
        "Building local feature strata..."
    )

    records = build_local_records(
        candidates,
        candles,
    )

    strata = stratum_summary(
        records
    )

    print(
        f"Feature strata found: "
        f"{len(strata)}"
    )

    print(
        "Local full outcome:"
    )

    print(
        json.dumps(
            local_summary(records),
            indent=2,
            ensure_ascii=False,
        )
    )

    print(
        "Selecting feature-diverse AI sample..."
    )

    sample = select_feature_diverse_sample(
        records,
        AI_SAMPLE_SIZE,
    )

    print(
        f"AI candidates selected: "
        f"{len(sample)}"
    )

    print("=" * 72)
    print("AI FEATURE DISCOVERY")
    print("=" * 72)

    ai_results = []

    for index, record in enumerate(
        sample,
        start=1,
    ):
        candidate = record[
            "candidate"
        ]

        print(
            f"[{index}/{len(sample)}] "
            f"{record['signal_time']} "
            f"{candidate['signal']} "
            f"{candidate['setup']}"
        )

        print(
            "  Stratum:",
            record["stratum"],
        )

        ai = judge(candidate)

        result = {
            "signal_time": record[
                "signal_time"
            ],
            "candidate": candidate,
            "stratum": record[
                "stratum"
            ],
            "outcome_return": record[
                "outcome_return"
            ],
            "ai": ai,
            "ai_bucket": ai_bucket(ai),
        }

        ai_results.append(result)

        print(
            f"  AI: {ai.get('decision')} "
            f"{ai.get('quality')} "
            f"{ai.get('source')}"
        )

        print(
            "  Return:",
            record["outcome_return"],
        )

        if is_groq_rate_limited(ai):
            print(
                "  STOP: Groq HTTP 429 "
                "rate-limit/quota response."
            )
            print(
                "  Remaining feature sample "
                "candidates were not sent."
            )
            break

    output = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "requested_candle_limit": (
            CANDLE_LIMIT
        ),
        "actual_candles": len(
            candles
        ),
        "first_candle": candles[
            0
        ]["time"].isoformat(),
        "last_candle": candles[
            -1
        ]["time"].isoformat(),
        "candidates_found": len(
            candidates
        ),
        "feature_strata": strata,
        "ai_sample_requested": (
            AI_SAMPLE_SIZE
        ),
        "ai_sample_selected": len(
            sample
        ),
        "ai_evaluated": len(
            ai_results
        ),
        "local_full_summary": (
            local_summary(records)
        ),
        "ai_summary": ai_summary(
            ai_results
        ),
        "ai_stratum_summary": (
            ai_stratum_summary(
                ai_results
            )
        ),
        "ai_results": ai_results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    print(
        "LOCAL FULL SUMMARY"
    )

    print(
        json.dumps(
            local_summary(records),
            indent=2,
            ensure_ascii=False,
        )
    )

    print(
        "AI SUMMARY"
    )

    print(
        json.dumps(
            ai_summary(ai_results),
            indent=2,
            ensure_ascii=False,
        )
    )

    print(
        "AI BY FEATURE STRATUM"
    )

    print(
        json.dumps(
            ai_stratum_summary(
                ai_results
            ),
            indent=2,
            ensure_ascii=False,
        )
    )

    print("=" * 72)
    print(
        "Saved:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
