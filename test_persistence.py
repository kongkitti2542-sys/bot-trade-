import sqlite3

from paper_trader import PaperTrader


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


def get_db_state():
    connection = sqlite3.connect("trading.db")

    account = connection.execute("""
        SELECT starting_capital, capital, daily_pnl
        FROM account_state
        WHERE id = 1
    """).fetchone()

    position = connection.execute("""
        SELECT id, symbol, side, entry_price, position_size
        FROM open_positions
    """).fetchall()

    connection.close()

    return account, position


def main():

    print("=" * 60)
    print("PAPER TRADER PERSISTENCE TEST")
    print("=" * 60)

    print("\n[1] RESET TEST STATE")
    reset_test_state()

    trader1 = PaperTrader()

    print(f"Capital: {trader1.capital}")
    print(f"Position: {trader1.position}")

    print("\n[2] OPEN SYNTHETIC POSITION")

    decision = {
        "score": 80,
        "confidence": 80,
        "regime": "TREND_UP",
        "reasons": [
            "Persistence test"
        ],
    }

    opened, message = trader1.open_position(
        symbol="BTCUSDT",
        side="BUY",
        price=83000.0,
        position_size=0.001,
        position_value=83.0,
        stop_loss=82600.0,
        decision=decision,
    )

    print(f"Opened: {opened}")
    print(f"Message: {message}")

    account, positions = get_db_state()

    print("\n[3] DATABASE AFTER OPEN")
    print(f"Account: {account}")
    print(f"Positions: {positions}")

    print("\n[4] CREATE NEW TRADER INSTANCE")

    trader2 = PaperTrader()

    print(f"Capital: {trader2.capital}")
    print(f"Position: {trader2.position}")

    print("\n[5] CLOSE POSITION FROM NEW INSTANCE")

    closed, result = trader2.close_position(
        price=83500.0,
        exit_reason="PERSISTENCE_TEST",
    )

    print(f"Closed: {closed}")

    if closed:
        print(f"P/L: ${result['pnl']:.4f}")
        print(f"Capital: ${trader2.capital:.4f}")

    account, positions = get_db_state()

    print("\n[6] DATABASE AFTER CLOSE")
    print(f"Account: {account}")
    print(f"Positions: {positions}")

    print("\n" + "=" * 60)

    if (
        trader1.position is not None
        and closed
        and trader2.position is None
        and positions == []
        and abs(account[1] - 1000.38345005) < 1e-9
        and abs(account[2] - 0.38345005) < 1e-9
    ):
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")

    print("=" * 60)


if __name__ == "__main__":
    main()
