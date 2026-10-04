"""
MONEY MACHINE V2 - Risk adapter.

Delegates all risk calculation to the existing locked risk.py.
No new risk rules are introduced here.
"""

from risk import evaluate_risk

from .contracts import RiskResult


def evaluate(
    decision: dict,
    features: dict,
    capital: float,
    daily_pnl: float = 0.0,
    open_positions: int = 0,
) -> RiskResult:
    """
    Delegate risk evaluation to the existing Risk Engine.
    """

    result = evaluate_risk(
        decision=decision,
        features=features,
        capital=capital,
        daily_pnl=daily_pnl,
        open_positions=open_positions,
    )

    return RiskResult(
        allowed=bool(result.get("allowed", False)),
        reason=result.get("reason"),
        risk_amount=float(result.get("risk_amount", 0.0)),
        position_value=float(result.get("position_value", 0.0)),
        position_size=float(result.get("position_size", 0.0)),
        stop_loss=result.get("stop_loss"),
        warnings=list(result.get("warnings", [])),
        reasons=list(result.get("reasons", [])),
    )
