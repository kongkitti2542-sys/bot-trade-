from paper_trader import PaperTrader


def execute_paper_plan(trader: PaperTrader, plan: dict, decision: dict):
    if not plan.get("allowed"):
        return False, plan.get("reason", "PLAN_NOT_APPROVED")

    required = (
        "signal",
        "entry_price",
        "position_size",
        "position_value_usdt",
        "stop_loss",
    )

    for key in required:
        if key not in plan:
            return False, f"MISSING_PLAN_FIELD:{key}"

    if plan["signal"] not in ("BUY", "SELL"):
        return False, "INVALID_SIGNAL"

    opened, result = trader.open_position(
        symbol="BTCUSDT",
        side=plan["signal"],
        price=plan["entry_price"],
        position_size=plan["position_size"],
        position_value=plan["position_value_usdt"],
        stop_loss=plan["stop_loss"],
        decision=decision,
    )

    return opened, result
