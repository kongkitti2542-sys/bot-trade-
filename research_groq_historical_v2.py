"""
Groq Historical Evaluation V2

Research-only expansion:
Money Maker #1 -> Groq Judge -> historical outcome.

V2:
- Fetches up to 100,000 closed candles using Binance pagination.
- Stops safely when Groq returns HTTP 429 rate-limit/quota response.
- Does not modify locked Core, Money Maker, Risk, PaperTrader,
  Position Manager, data.py, or Groq Judge behavior.
"""

import json
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

OUTPUT_FILE = Path("research_groq_historical_v2_results.json")
RESEARCH_VERSION = "GROQ_HISTORICAL_V2"


def fetch_closed_candles_paginated(symbol, interval, limit):
    """
    Research-local Binance pagination.

    data.py is intentionally not modified.
    Fetches newest pages backward until enough candles exist,
    then sorts chronologically and removes the newest candle
    because Binance's newest kline may still be open.
    """
    raw_candles = []
    end_time = None

    while len(raw_candles) < limit + 1:
        page_limit = min(BINANCE_PAGE_LIMIT, limit + 1 - len(raw_candles))

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
            page = json.loads(response.read().decode("utf-8"))

        if not page:
            break

        raw_candles.extend(page)

        oldest_open_time = page[0][0]
        end_time = oldest_open_time - 1

        if len(page) < page_limit:
            break

    unique = {}
    for candle in raw_candles:
        unique[candle[0]] = candle

    ordered = [
        unique[key]
        for key in sorted(unique)
    ]

    if not ordered:
        return []

    # Remove newest kline because it may still be open.
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


def evaluate_candidate(candidate, candles):
    exit_time = candidate["planned_exit_time"]
    exit_candle = find_candle(candles, exit_time)

    if exit_candle is None:
        return {
            "status": "UNRESOLVED",
            "reason": "EXIT_CANDLE_NOT_FOUND",
            "signal_time": candidate["signal_time"].isoformat(),
        }

    result = {
        "status": "RESOLVED",
        "signal_time": candidate["signal_time"].isoformat(),
        "entry_time": candidate["entry_time"].isoformat(),
        "entry": candidate["entry"],
        "signal": candidate["signal"],
        "setup": candidate["setup"],
        "planned_exit_time": exit_time.isoformat(),
        "reference_exit": candidate["reference_exit"],
        "actual_exit_close": exit_candle["close"],
        "outcome_return": historical_return(
            candidate,
            exit_candle,
        ),
    }

    ai = judge(candidate)
    result["ai"] = ai

    source = ai.get("source")

    if source == "GROQ":
        result["ai_bucket"] = (
            "GROQ_PASS"
            if ai.get("decision") == "PASS"
            else "GROQ_WAIT"
        )
    elif source == "SAFE_FALLBACK":
        result["ai_bucket"] = "SAFE_FALLBACK"
    elif source == "BUDGET_GUARD":
        result["ai_bucket"] = "BUDGET_GUARD"
    else:
        result["ai_bucket"] = "OTHER"

    return result


def is_groq_rate_limited(ai):
    """
    Groq Judge intentionally converts HTTP errors into SAFE_FALLBACK.
    Detect the real HTTP 429 from its reason text without changing
    the locked Groq Judge.
    """
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
            sum(1 for r in returns if r > 0)
            / len(returns)
            * 100.0
        ),
        "sum_return": sum(returns) * 100.0,
        "avg_return": (
            sum(returns)
            / len(returns)
            * 100.0
        ),
    }


def summarize(results):
    resolved = [
        x
        for x in results
        if x.get("status") == "RESOLVED"
    ]

    return {
        "all_resolved": stats(resolved),
        "groq_pass": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket") == "GROQ_PASS"
            ]
        ),
        "groq_wait": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket") == "GROQ_WAIT"
            ]
        ),
        "safe_fallback": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket") == "SAFE_FALLBACK"
            ]
        ),
        "budget_guard": stats(
            [
                x
                for x in resolved
                if x.get("ai_bucket") == "BUDGET_GUARD"
            ]
        ),
        "unresolved": len(results) - len(resolved),
    }


def main():
    print("=" * 72)
    print("GROQ HISTORICAL EVALUATION V2")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Requested    : {CANDLE_LIMIT:,}")
    print("Execution    : NONE")
    print("Paper DB     : NOT USED")
    print("=" * 72)

    print(
        "Groq calls made today:",
        remaining_calls(),
    )

    print("Fetching historical candles with pagination...")

    try:
        candles = fetch_closed_candles_paginated(
            symbol=SYMBOL,
            interval=INTERVAL,
            limit=CANDLE_LIMIT,
        )
    except HTTPError as exc:
        print("RESULT: STOPPED")
        print(f"Reason: BINANCE_HTTP_ERROR_{exc.code}")
        return
    except (URLError, TimeoutError) as exc:
        print("RESULT: STOPPED")
        print(
            "Reason: BINANCE_CONNECTION_ERROR_"
            f"{type(exc).__name__}"
        )
        return

    print(
        f"Actual candles returned: {len(candles):,}"
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
        f"Candidates found: {len(candidates)}"
    )
    print("=" * 72)

    results = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        print(
            f"[{index}/{len(candidates)}] "
            f"{candidate['signal_time']} "
            f"{candidate['signal']} "
            f"{candidate['setup']}"
        )

        result = evaluate_candidate(
            candidate,
            candles,
        )

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

        if ai.get("source") == "SAFE_FALLBACK":
            print(
                "  NOTE: Not counted as a real AI decision."
            )

        if is_groq_rate_limited(ai):
            print(
                "  STOP: Groq HTTP 429 "
                "rate-limit/quota response."
            )
            print(
                "  Remaining candidates were not sent "
                "to Groq."
            )
            break

    summary = summarize(results)

    output = {
        "research_version": RESEARCH_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "requested_candle_limit": CANDLE_LIMIT,
        "actual_candles": len(candles),
        "first_candle": candles[0]["time"].isoformat(),
        "last_candle": candles[-1]["time"].isoformat(),
        "candidates_found": len(candidates),
        "evaluated": len(results),
        "summary": summary,
        "results": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    print(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
