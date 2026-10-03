from currency_layer import thb_to_usdt
from execution_constraints import validate_order
from risk import evaluate_risk


def build_trade_plan(
    decision,
    features,
    thb_capital,
    usdthb,
    min_qty,
    step_size,
    min_notional,
):
    usdt_capital = thb_to_usdt(thb_capital, usdthb)

    risk = evaluate_risk(
        decision=decision,
        features=features,
        capital=usdt_capital,
        daily_pnl=0.0,
        open_positions=0,
    )

    plan = {
        "allowed": False,
        "reason": risk["reason"],
        "thb_capital": thb_capital,
        "usdt_capital": usdt_capital,
        "risk": risk,
    }

    if not risk["allowed"]:
        return plan

    constraints = validate_order(
        quantity=risk["position_size"],
        price=features["close"],
        min_qty=min_qty,
        step_size=step_size,
        min_notional=min_notional,
    )

    plan["constraints"] = constraints

    if not constraints["allowed"]:
        plan["reason"] = constraints["reason"]
        return plan

    final_quantity = constraints["quantity"]
    final_notional = constraints["notional"]

    if decision["signal"] == "BUY":
        final_stop = risk["stop_loss"]
    elif decision["signal"] == "SELL":
        final_stop = risk["stop_loss"]
    else:
        plan["reason"] = "INVALID_EXECUTION_SIGNAL"
        return plan

    final_risk_usdt = abs(
        features["close"] - final_stop
    ) * final_quantity

    plan.update({
        "allowed": True,
        "reason": "TRADE_PLAN_APPROVED",
        "signal": decision["signal"],
        "entry_price": features["close"],
        "stop_loss": final_stop,
        "position_size": final_quantity,
        "position_value_usdt": final_notional,
        "position_value_thb": final_notional * usdthb,
        "risk_usdt": final_risk_usdt,
        "risk_thb": final_risk_usdt * usdthb,
    })

    return plan
