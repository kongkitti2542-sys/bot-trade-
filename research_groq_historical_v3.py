"""
Groq Historical Evaluation V3

Quota-efficient research:
- Load 100,000 closed BTCUSDT 5m candles using local pagination.
- Find all Money Maker #1 candidates.
- Calculate historical outcomes locally for ALL candidates.
- Send only a deterministic, chronologically distributed sample
  to Groq for AI review.
- Stop immediately on Groq HTTP 429.
- Does not modify locked Core, Money Maker, Risk, PaperTrader,
  Position Manager, data.py, Groq Judge, or V2.
"""

import json
import os
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
    os.environ.get("GROQ_RESEARCH_SAMPLE_SIZE", "50")
)

OUTPUT_FILE = Path(
    "research_groq_historical_v3_results.json"
)

RESEARCH_VERSION = "GROQ_HISTORICAL_V3"


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

    # Remove newest possibly-open candle.
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


def historical_return(candidate, exit_candle):
    entry = candidate["entry"]
    exit_price = exit_candle["close"]

    if candidate["signal"] == "BUY":
        return (exit_price - entry) / entry

    if candidate["signal"] == "SELL":
        return (entry - exit_price) / entry

    return None


def evaluate_historical_outcome(candidate, candles):
    exit_time = candidate["planned_exit_time"]

    exit_candle = find_candle(
        candles,
        exit_time,
    )

    if exit_candle is None:
        return {
            "status": "UNRESOLVED",
            "reason": "EXIT_CANDLE_NOT_FOUND",
            "signal_time": candidate[
                "signal_time"
            ].isoformat(),
        }

    return {
        "status": "RESOLVED",
        "signal_time": candidate[
            "signal_time"
        ].isoformat(),
        "entry_time": candidate[
            "entry_time"
        ].isoformat(),
        "entry": candidate["entry"],
        "signal": candidate["signal"],
        "setup": candidate["setup"],
        "planned_exit_time": exit_time.isoformat(),
        "reference_exit": candidate[
            "reference_exit"
        ],
        "actual_exit_close": exit_candle[
            "close"
        ],
        "outcome_return": historical_return(
            candidate,
            exit_candle,
        ),
    }


def select_ai_sample(candidates, sample_size):
    """
    Deterministic systematic sample.

    The sample is distributed across the complete candidate
    sequence instead of taking only the first N candidates.
    """
    if not candidates:
        return []

    if sample_size <= 0:
        return []

    if sample_size >= len(candidates):
        return list(candidates)

    selected = []

    for i in range(sample_size):
        index = round(
            i * (len(candidates) - 1)
            / (sample_size - 1)
        )
        selected.append(candidates[index])

    return selected


def is_groq_rate_limited(ai):
    if ai.get("source") != "SAFE_FALLBACK":
        return False

    for reason in ai.get("reasons", []):
        if "Groq HTTP error: 429" in str(reason):
            return True

    return False


def stats(items):
    returns = [
        x["outcome_return"]
        for x in items
        if x.get("status") == "RESOLVED"
        and x.get("outcome_return") is not None
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


def summarize_ai(results):
    resolved = [
        x
        for x in results
        if x.get("status") == "RESOLVED"
    ]

    return {
        "ai_sample_resolved": stats(resolved),
        "groq_pass": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket")
                == "GROQ_PASS"
            ]
        ),
        "groq_wait": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket")
                == "GROQ_WAIT"
            ]
        ),
        "safe_fallback": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket")
                == "SAFE_FALLBACK"
            ]
        ),
        "unresolved": (
            len(results)
            - len(resolved)
        ),
    }


def main():
    print("=" * 72)
    print("GROQ HISTORICAL EVALUATION V3")
    print("=" * 72)
    print(f"Symbol          : {SYMBOL}")
    print(f"Interval        : {INTERVAL}")
    print(f"Requested       : {CANDLE_LIMIT:,}")
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
        "Fetching historical candles "
        "with pagination..."
    )

    try:
        candles = fetch_closed_candles_paginated(
            symbol=SYMBOL,
            interval=INTERVAL,
            limit=CANDLE_LIMIT,
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

    candidates = find_candidates(candles)

    print(
        f"Candidates found: "
        f"{len(candidates)}"
    )

    print(
        "Calculating historical outcomes "
        "locally for all candidates..."
    )

    all_outcomes = []

    for candidate in candidates:
        outcome = evaluate_historical_outcome(
            candidate,
            candles,
        )

        all_outcomes.append(
            {
                "candidate": candidate,
                "outcome": outcome,
            }
        )

    local_resolved = [
        x["outcome"]
        for x in all_outcomes
        if x["outcome"].get(
            "status"
        ) == "RESOLVED"
    ]

    print(
        f"Local outcomes resolved: "
        f"{len(local_resolved):,}"
    )

    sample = select_ai_sample(
        candidates,
        AI_SAMPLE_SIZE,
    )

    print(
        f"AI candidates selected: "
        f"{len(sample):,}"
    )

    print("=" * 72)
    print("AI SAMPLE EVALUATION")
    print("=" * 72)

    ai_results = []

    for index, candidate in enumerate(
        sample,
        start=1,
    ):
        print(
            f"[{index}/{len(sample)}] "
            f"{candidate['signal_time']} "
            f"{candidate['signal']} "
            f"{candidate['setup']}"
        )

        outcome = evaluate_historical_outcome(
            candidate,
            candles,
        )

        ai = judge(candidate)

        result = {
            "status": outcome.get(
                "status"
            ),
            "signal_time": outcome.get(
                "signal_time"
            ),
            "entry_time": outcome.get(
                "entry_time"
            ),
            "entry": outcome.get(
                "entry"
            ),
            "signal": outcome.get(
                "signal"
            ),
            "setup": outcome.get(
                "setup"
            ),
            "planned_exit_time": outcome.get(
                "planned_exit_time"
            ),
            "reference_exit": outcome.get(
                "reference_exit"
            ),
            "actual_exit_close": outcome.get(
                "actual_exit_close"
            ),
            "outcome_return": outcome.get(
                "outcome_return"
            ),
            "ai": ai,
        }

        source = ai.get("source")

        if source == "GROQ":
            result["ai_bucket"] = (
                "GROQ_PASS"
                if ai.get("decision")
                == "PASS"
                else "GROQ_WAIT"
            )
        elif source == "SAFE_FALLBACK":
            result["ai_bucket"] = (
                "SAFE_FALLBACK"
            )
        else:
            result["ai_bucket"] = (
                "OTHER"
            )

        ai_results.append(result)

        print(
            f"  AI: {ai.get('decision')} "
            f"{ai.get('quality')} "
            f"{ai.get('source')}"
        )

        print(
            "  Return: "
            f"{result.get('outcome_return')}"
        )

        if is_groq_rate_limited(ai):
            print(
                "  STOP: Groq HTTP 429 "
                "rate-limit/quota response."
            )
            print(
                "  Remaining AI sample "
                "candidates were not sent."
            )
            break

    ai_summary = summarize_ai(
        ai_results
    )

    local_summary = stats(
        local_resolved
    )

    output = {
        "research_version": RESEARCH_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "requested_candle_limit": (
            CANDLE_LIMIT
        ),
        "actual_candles": len(candles),
        "first_candle": candles[
            0
        ]["time"].isoformat(),
        "last_candle": candles[
            -1
        ]["time"].isoformat(),
        "candidates_found": len(
            candidates
        ),
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
            local_summary
        ),
        "ai_sample_summary": (
            ai_summary
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
        "LOCAL FULL CANDIDATE OUTCOME"
    )
    print(
        json.dumps(
            local_summary,
            indent=2,
            ensure_ascii=False,
        )
    )

    print(
        "AI SAMPLE OUTCOME"
    )
    print(
        json.dumps(
            ai_summary,
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
