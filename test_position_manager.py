import sqlite3

from paper_trader import PaperTrader
from position_manager import check_stop_loss, monitor_position


def reset_test_state():
    connection = sqlite3.connect("trading.db")

    connection.execute("""
        UPDATE account_state
        SET starting_capital = 1000.0,
            capital = 1000.0,
            daily_pnl = 0.0
        WHERE id = 1
    """)

    connection.execute("DELETE FROM open_positions")

    connection.commit()
    connection.close()


def get_open_positions():
    connection = sqlite3.connect("trading.db")

    rows = connection.execute("""
        SELECT id, symbol, side, entry_price,
               position_size, stop_loss
        FROM open_positions
    """).fetchall()

    connection.close()

    return rows


def get_account():
    connection = sqlite3.connect("trading.db")

    row = connection.execute("""
        SELECT starting_capital, capital, daily_pnl
        FROM account_state
        WHERE id = 1
    """).fetchone()

    connection.close()

    return row


def create_test_position():

    trader = PaperTrader()

    decision = {
        "score": 80,
        "confidence": 80,
        "regime": "TREND_UP",
        "reasons": [
            "Stop loss test"
        ],
    }

    opened, message = trader.open_position(
        symbol="BTCUSDT",
        side="BUY",
        price=83000.0,
        position_size=0.001,
        position_value=83.0,
        stop_loss=82600.0,
        decision=decision,
    )

    if not opened:
        raise RuntimeError(
            f"Could not create test position: {message}"
        )

    return trader


def test_stop_not_hit():

    print("\n[TEST 1] STOP LOSS NOT HIT")

    reset_test_state()

    trader = create_test_position()

    triggered, reason = check_stop_loss(
        position=trader.position,
        current_price=83000.0,
    )

    print(f"Triggered: {triggered}")
    print(f"Reason: {reason}")
    print(f"Position exists: {trader.position is not None}")

    passed = (
        triggered is False
        and reason == "STOP_NOT_HIT"
        and trader.position is not None
        and len(get_open_positions()) == 1
    )

    print(
        "RESULT:",
        "PASS" if passed else "FAIL"
    )

    return passed


def test_stop_hit():

    print("\n[TEST 2] STOP LOSS HIT")

    reset_test_state()

    trader = create_test_position()

    closed, result = monitor_position(
        trader=trader,
        current_price=82500.0,
    )

    print(f"Closed: {closed}")

    if closed:
        print(f"P/L: ${result['pnl']:.4f}")
        print(
            f"Exit Reason: {result['exit_reason']}"
        )

    account = get_account()
    positions = get_open_positions()

    print(f"Account: {account}")
    print(f"Open Positions: {positions}")

    passed = (
        closed is True
        and result["pnl"] == -0.5
        and result["exit_reason"] == "STOP_LOSS"
        and trader.position is None
        and len(positions) == 0
        and abs(account[1] - 999.38414995) < 1e-9
        and abs(account[2] - (-0.61585005)) < 1e-9
    )

    print(
        "RESULT:",
        "PASS" if passed else "FAIL"
    )

    return passed


def main():

    print("=" * 60)
    print("POSITION MANAGER V2.0 TEST")
    print("=" * 60)

    test_1 = test_stop_not_hit()
    test_2 = test_stop_hit()

    print("\n" + "=" * 60)

    if test_1 and test_2:
        print("OVERALL RESULT: PASS")
    else:
        print("OVERALL RESULT: FAIL")

    print("=" * 60)


if __name__ == "__main__":
    main()
