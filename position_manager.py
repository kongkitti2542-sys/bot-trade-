from paper_trader import PaperTrader


def check_stop_loss(position, current_price):
    """
    ตรวจว่า Position ถูก Stop Loss หรือยัง

    BUY:
        current_price <= stop_loss

    SELL:
        current_price >= stop_loss
    """

    if position is None:
        return False, "NO_POSITION"

    side = position["side"]
    stop_loss = position["stop_loss"]

    if current_price <= 0:
        return False, "INVALID_PRICE"

    if stop_loss <= 0:
        return False, "INVALID_STOP_LOSS"

    if side == "BUY":
        if current_price <= stop_loss:
            return True, "STOP_LOSS"

        return False, "STOP_NOT_HIT"

    if side == "SELL":
        if current_price >= stop_loss:
            return True, "STOP_LOSS"

        return False, "STOP_NOT_HIT"

    return False, "INVALID_SIDE"


def monitor_position(trader, current_price):
    """
    ตรวจ Position ปัจจุบันของ PaperTrader
    และปิด Position เมื่อ Stop Loss ถูก hit
    """

    position = trader.position

    if position is None:
        return False, "NO_POSITION"

    triggered, reason = check_stop_loss(
        position=position,
        current_price=current_price,
    )

    if not triggered:
        return False, reason

    closed, result = trader.close_position(
        price=current_price,
        exit_reason="STOP_LOSS",
    )

    if not closed:
        return False, result

    return True, result


if __name__ == "__main__":
    print("Position Manager V2.0")
    print("Stop Loss monitoring only.")
