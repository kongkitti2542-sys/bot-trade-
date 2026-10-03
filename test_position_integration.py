import sqlite3

from paper_trader import PaperTrader
from position_manager import monitor_position


def reset_state():
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


def get_state():
    connection = sqlite3.connect("trading.db")

    account = connection.execute("""
        SELECT starting_capital, capital, daily_pnl
        FROM account_state
        WHERE id = 1
    """).fetchone()

    positions = connection.execute("""
        SELECT id, symbol, side, entry_price,
               position_size, stop_loss
        FROM open_positions
    """).fetchall()

    trades = connection.execute("""
        SELECT symbol, side, status,
               entry_price, exit_price,
               pnl, exit_reason
        FROM trades
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    connection.close()

    return account, positions, trades


def main():

    print("=" * 60)
    print("POSITION MANAGER INTEGRATION TEST")
    print("=" * 60)

    # --------------------------------------------------
    # 1. RESET
    # --------------------------------------------------

    print("\n[1] RESET STATE")

    reset_state()

    trader1 = PaperTrader()

    print(f"Capital: {trader1.capital}")
    print(f"Position: {trader1.position}")

    # --------------------------------------------------
    # 2. OPEN POSITION
    # --------------------------------------------------

    print("\n[2] OPEN POSITION")

    decision = {
        "score": 80,
        "confidence": 80,
        "regime": "TREND_UP",
        "reasons": [
            "Integration test"
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

    # --------------------------------------------------
    # 3. SIMULATE RESTART
    # --------------------------------------------------

    print("\n[3] SIMULATE RESTART")

    trader2 = PaperTrader()

    print(f"Capital: {trader2.capital}")
    print(f"Position: {trader2.position}")

    # --------------------------------------------------
    # 4. POSITION MANAGER
    # --------------------------------------------------

    print("\n[4] POSITION MANAGER")

    position_loaded = trader2.position is not None

    closed, result = monitor_position(
        trader=trader2,
        current_price=82500.0,
    )

    print(f"Closed: {closed}")

    if closed:
        print(f"P/L: ${result['pnl']:.4f}")
        print(f"Exit Reason: {result['exit_reason']}")

    # --------------------------------------------------
    # 5. DATABASE
    # --------------------------------------------------

    print("\n[5] DATABASE STATE")

    account, positions, trade = get_state()

    print(f"Account: {account}")
    print(f"Open Positions: {positions}")
    print(f"Last Trade: {trade}")

    # --------------------------------------------------
    # 6. ASSERTIONS
    # --------------------------------------------------

    passed = (
        opened is True
        and position_loaded is True
        and closed is True
        and result["pnl"] == -0.5
        and result["exit_reason"] == "STOP_LOSS"
        and trader2.position is None
        and positions == []
        and abs(account[1] - 999.38414995) < 1e-9
        and abs(account[2] - (-0.61585005)) < 1e-9
        and trade[2] == "CLOSED"
        and trade[5] == -0.5
        and trade[6] == "STOP_LOSS"
    )

    print("\n" + "=" * 60)

    if passed:
        print("INTEGRATION RESULT: PASS")
    else:
        print("INTEGRATION RESULT: FAIL")

    print("=" * 60)


if __name__ == "__main__":
    main()
