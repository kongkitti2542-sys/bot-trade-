"""Money Team V1.

Money Maker #1 -> Groq AI Review -> Risk Authority.

Paper/research orchestration only.
No order execution.
Does not modify the locked money maker, AI judge, or risk engine.
"""

from money_maker_01_adapter_v1 import find_candidates
from groq_judge_v1 import judge
from risk import evaluate_risk


TEAM_VERSION = "MONEY_TEAM_V1"
MONEY_MAKER = "MONEY_MAKER_01"


def _find_signal_candle(candles, signal_time):
    for candle in candles:
        if candle["time"] == signal_time:
            return candle
    return None


def evaluate_candidate(
    candidate,
    signal_candle,
    capital,
    daily_pnl=0.0,
    open_positions=0,
):
    """Run one candidate through AI review and then Risk."""

    ai_result = judge(candidate)

    result = {
        "team_version": TEAM_VERSION,
        "money_maker": MONEY_MAKER,
        "candidate": candidate,
        "ai": ai_result,
        "risk": None,
        "final_decision": "WAIT",
    }

    if ai_result.get("decision") != "PASS":
        result["final_decision"] = "WAIT"
        result["final_reason"] = "AI_REVIEW_WAIT"
        return result

    decision = {
        "signal": candidate["signal"],
        "confidence": 0,
        "quality": "PASSED",
    }

    features = {
        "close": signal_candle["close"],
        "atr14": candidate["features"]["atr"],
    }

    risk_result = evaluate_risk(
        decision,
        features,
        capital=capital,
        daily_pnl=daily_pnl,
        open_positions=open_positions,
    )

    result["risk"] = risk_result

    if risk_result.get("allowed"):
        result["final_decision"] = "RISK_APPROVED"
        result["final_reason"] = risk_result.get("reason")
    else:
        result["final_decision"] = "WAIT"
        result["final_reason"] = risk_result.get("reason")

    return result


def run_team(
    candles,
    capital,
    daily_pnl=0.0,
    open_positions=0,
):
    """Evaluate all current Money Maker #1 candidates."""

    candidates = find_candidates(candles)
    results = []

    for candidate in candidates:
        signal_candle = _find_signal_candle(
            candles,
            candidate["signal_time"],
        )

        if signal_candle is None:
            results.append(
                {
                    "team_version": TEAM_VERSION,
                    "money_maker": MONEY_MAKER,
                    "candidate": candidate,
                    "ai": {
                        "decision": "WAIT",
                        "quality": "LOW",
                        "reasons": ["Signal candle not found"],
                        "source": "TEAM_SAFE_FALLBACK",
                    },
                    "risk": None,
                    "final_decision": "WAIT",
                    "final_reason": "SIGNAL_CANDLE_NOT_FOUND",
                }
            )
            continue

        results.append(
            evaluate_candidate(
                candidate,
                signal_candle,
                capital=capital,
                daily_pnl=daily_pnl,
                open_positions=open_positions,
            )
        )

    return results


if __name__ == "__main__":
    print("=" * 72)
    print("MONEY TEAM V1")
    print("=" * 72)
    print("Money Maker : MONEY_MAKER_01")
    print("AI          : Groq Judge V1")
    print("Risk        : Risk Engine")
    print("Execution   : NONE")
    print("Mode        : PAPER / RESEARCH ONLY")
