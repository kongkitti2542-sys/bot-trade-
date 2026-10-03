from decimal import Decimal, ROUND_DOWN


def floor_to_step(quantity: float, step_size: float) -> float:
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    if step_size <= 0:
        raise ValueError("step_size must be greater than zero")

    q = Decimal(str(quantity))
    step = Decimal(str(step_size))

    result = (q / step).to_integral_value(rounding=ROUND_DOWN) * step
    return float(result)


def validate_order(
    quantity: float,
    price: float,
    min_qty: float,
    step_size: float,
    min_notional: float,
) -> dict:
    if quantity <= 0:
        return {
            "allowed": False,
            "reason": "INVALID_QUANTITY",
            "quantity": 0.0,
            "notional": 0.0,
        }

    if price <= 0:
        return {
            "allowed": False,
            "reason": "INVALID_PRICE",
            "quantity": 0.0,
            "notional": 0.0,
        }

    adjusted_quantity = floor_to_step(quantity, step_size)
    notional = adjusted_quantity * price

    if adjusted_quantity < min_qty:
        return {
            "allowed": False,
            "reason": "MIN_QTY",
            "quantity": adjusted_quantity,
            "notional": notional,
        }

    if notional < min_notional:
        return {
            "allowed": False,
            "reason": "MIN_NOTIONAL",
            "quantity": adjusted_quantity,
            "notional": notional,
        }

    return {
        "allowed": True,
        "reason": "ORDER_CONSTRAINTS_APPROVED",
        "quantity": adjusted_quantity,
        "notional": notional,
    }
