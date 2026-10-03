"""
Groq Historical Evaluation V1

Research-only:
Money Maker #1 Adapter -> Groq Judge -> historical outcome comparison.

Does NOT modify:
- Core strategy
- Money Maker #1 adapter
- Risk engine
- PaperTrader
- Position Manager
- Database
- Groq Judge

No order execution.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from data import get_closed_candles
from money_maker_01_adapter_v1 import find_candidates
from groq_judge_v1 import judge, remaining_calls

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLE_LIMIT = 10_000
OUTPUT_FILE = Path("research_groq_historical_v1_results.json")

RESEARCH_VERSION = "GROQ_HISTORICAL_V1"


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


def evaluate_candidate(candidate, candles):
    exit_time = candidate["planned_exit_time"]
    exit_candle = find_candle(candles, exit_time)

    if exit_candle is None:
        return {
            "status": "UNRESOLVED",
            "reason": "EXIT_CANDLE_NOT_FOUND",
        }

    result = {
        "signal_time": candidate["signal_time"].isoformat(),
        "entry_time": candidate["entry_time"].isoformat(),
        "entry": candidate["entry"],
        "signal": candidate["signal"],
        "setup": candidate["setup"],
        "planned_exit_time": exit_time.isoformat(),
        "reference_exit": candidate["reference_exit"],
        "actual_exit_close": exit_candle["close"],
        "outcome_return": historical_return(candidate, exit_candle),
    }

    ai = judge(candidate)
    result["ai"] = ai

    if ai.get("decision") == "PASS":
        result["ai_bucket"] = "PASS"
    elif ai.get("decision") == "WAIT":
        result["ai_bucket"] = "WAIT"
    else:
        result["ai_bucket"] = "INVALID"

    return result


def summarize(results):
    resolved = [
        x for x in results
        if x.get("status") != "UNRESOLVED"
        and x.get("outcome_return") is not None
    ]

    def bucket(name):
        return [
            x for x in resolved
            if x.get("ai_bucket") == name
        ]

    def stats(items):
        returns = [x["outcome_return"] for x in items]
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
                sum(1 for r in returns if r > 0)
                / len(returns)
                * 100.0
            ),
            "sum_return": sum(returns) * 100.0,
            "avg_return": sum(returns)
            / len(returns)
            * 100.0,
        }

    return {
        "all": stats(resolved),
        "ai_pass": stats(bucket("PASS")),
        "ai_wait": stats(bucket("WAIT")),
        "unresolved": len(results) - len(resolved),
    }


def main():
    print("=" * 72)
    print("GROQ HISTORICAL EVALUATION V1")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Candles      : {CANDLE_LIMIT}")
    print("Execution    : NONE")
    print("Paper DB     : NOT USED")
    print("=" * 72)

    remaining = remaining_calls()
    print(f"Groq calls remaining today: {remaining}")

    if remaining <= 0:
        print("RESULT: STOPPED")
        print("Reason: GROQ_DAILY_BUDGET_EXHAUSTED")
        print("No historical evaluation was run.")
        return

    candles = get_closed_candles(
        symbol=SYMBOL,
        interval=INTERVAL,
        limit=CANDLE_LIMIT,
    )

    candidates = find_candidates(candles)

    print(f"Candidates found: {len(candidates)}")

    results = []

    for index, candidate in enumerate(candidates, start=1):
        if remaining_calls() <= 0:
            print("Groq budget exhausted. Stopping without guessing.")
            break

        print(
            f"[{index}/{len(candidates)}] "
            f"{candidate['signal_time']} "
            f"{candidate['signal']} "
            f"{candidate['setup']}"
        )

        result = evaluate_candidate(candidate, candles)
        results.append(result)

        ai = result.get("ai", {})
        print(
            f"  AI: {ai.get('decision')} "
            f"{ai.get('quality')} "
            f"{ai.get('source')}"
        )
        print(
            f"  Return: "
            f"{result.get('outcome_return')}"
        )

    summary = summarize(results)

    output = {
        "research_version": RESEARCH_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "candle_limit": CANDLE_LIMIT,
        "candidates_found": len(candidates),
        "evaluated": len(results),
        "summary": summary,
        "results": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Results saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
