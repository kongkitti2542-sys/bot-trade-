"""Paper Team V1.

Money Team V1 -> PaperTrader execution -> Position Manager stop-loss monitoring.

Execution adapter only. Does not modify the locked strategy, money maker,
AI judge, risk engine, PaperTrader, Position Manager, or database.
"""

from money_team_v1 import evaluate_candidate
from money_maker_01_adapter_v1 import find_candidates
from position_manager import monitor_position


PAPER_TEAM_VERSION = "PAPER_TEAM_V1"


def _find_signal_candle(candles, signal_time):
    for candle in candles:
        if candle["time"] == signal_time:
            return candle
    return None


def _latest_candidate(candles):
    candidates = find_candidates(candles)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["signal_time"])


def evaluate_latest_candidate(candles, trader):
    """Review only the newest Money Maker candidate against current paper state."""
    candidate = _latest_candidate(candles)

    if candidate is None:
        return {
            "paper_team_version": PAPER_TEAM_VERSION,
            "final_decision": "WAIT",
            "reason": "NO_MONEY_MAKER_CANDIDATE",
        }

    signal_candle = _find_signal_candle(candles, candidate["signal_time"])

    if signal_candle is None:
        return {
            "paper_team_version": PAPER_TEAM_VERSION,
            "candidate": candidate,
            "final_decision": "WAIT",
            "reason": "SIGNAL_CANDLE_NOT_FOUND",
        }

    if trader.position is not None:
        return {
            "paper_team_version": PAPER_TEAM_VERSION,
            "candidate": candidate,
            "final_decision": "WAIT",
            "reason": "POSITION_ALREADY_OPEN",
        }

    team_result = evaluate_candidate(
        candidate=candidate,
        signal_candle=signal_candle,
        capital=trader.capital,
        daily_pnl=trader.daily_pnl,
        open_positions=1 if trader.position is not None else 0,
    )

    result = {
        "paper_team_version": PAPER_TEAM_VERSION,
        "team_result": team_result,
        "final_decision": "WAIT",
        "reason": team_result.get("final_reason"),
        "paper_trade": None,
    }

    if team_result.get("final_decision") != "RISK_APPROVED":
        return result

    risk = team_result.get("risk") or {}

    if not risk.get("allowed"):
        result["reason"] = risk.get("reason", "RISK_NOT_ALLOWED")
        return result

    # PaperTrader requires legacy metadata fields, but Money Maker #1
    # does not provide score/confidence/regime. Keep them explicitly None.
    decision = {
        "score": None,
        "confidence": None,
        "regime": None,
        "reasons": [
            candidate["setup"],
            "MONEY_TEAM_RISK_APPROVED",
        ],
    }

    opened, open_result = trader.open_position(
        symbol=candidate["symbol"],
        side=candidate["signal"],
        price=candidate["entry"],
        position_size=risk["position_size"],
        position_value=risk["position_value"],
        stop_loss=risk["stop_loss"],
        decision=decision,
    )

    result["paper_trade"] = {
        "opened": opened,
        "result": open_result,
        "entry": candidate["entry"],
        "position_size": risk["position_size"],
        "position_value": risk["position_value"],
        "stop_loss": risk["stop_loss"],
    }

    if opened:
        result["final_decision"] = "PAPER_POSITION_OPENED"
        result["reason"] = open_result
    else:
        result["reason"] = open_result

    return result


def monitor_paper_position(trader, current_price):
    """Delegate stop-loss monitoring to the locked Position Manager."""
    triggered, result = monitor_position(
        trader=trader,
        current_price=current_price,
    )

    return {
        "paper_team_version": PAPER_TEAM_VERSION,
        "stop_loss_triggered": triggered,
        "result": result,
        "capital": trader.capital,
        "daily_pnl": trader.daily_pnl,
        "position_open": trader.position is not None,
    }


if __name__ == "__main__":
    print("=" * 72)
    print("PAPER TEAM V1")
    print("=" * 72)
    print("Money Team : MONEY_TEAM_V1")
    print("Execution  : PaperTrader")
    print("Exit       : Position Manager / Stop Loss")
    print("Mode       : PAPER ONLY")
