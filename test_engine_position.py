import sqlite3
from unittest.mock import patch

from paper_trader import PaperTrader
from engine import run_engine


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


def create_position():

    trader = PaperTrader()

    decision = {
        "score": 80,
        "confidence": 80,
        "regime": "TREND_UP",
        "reasons": [
            "Engine integration test"
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
        raise RuntimeError(message)


def get_position_count():

    connection = sqlite3.connect("trading.db")

    count = connection.execute("""
        SELECT COUNT(*)
        FROM open_positions
    """).fetchone()[0]

    connection.close()

    return count


def main():

    print("=" * 60)
    print("ENGINE POSITION INTEGRATION TEST")
    print("=" * 60)

    print("\n[1] RESET STATE")

    reset_state()

    print(
        "Open Positions:",
        get_position_count()
    )

    print("\n[2] CREATE EXISTING POSITION")

    create_position()

    print(
        "Open Positions:",
        get_position_count()
    )

    print("\n[3] RUN ENGINE WITH EXISTING POSITION")

    fake_candles = [
        {
            "time": "TEST",
            "open": 82500.0,
            "high": 83100.0,
            "low": 82400.0,
            "close": 82500.0,
            "volume": 1000.0,
        }
    ]

    with patch(
        "engine.get_closed_candles",
        return_value=fake_candles,
    ):
        run_engine()

    print("\n[4] VERIFY DATABASE")

    position_count = get_position_count()

    print(
        "Open Positions:",
        position_count
    )

    passed = position_count == 0

    print("\n" + "=" * 60)

    if passed:
        print("ENGINE POSITION TEST: PASS")
    else:
        print("ENGINE POSITION TEST: FAIL")

    print("=" * 60)


if __name__ == "__main__":
    main()
