import tempfile
from pathlib import Path

import database
from paper_trader import PaperTrader


def main():
    original_db = database.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "test.db"

        trader = PaperTrader(starting_capital=1000.0)
        decision = {
            "score": 80,
            "confidence": 80,
            "regime": "TREND_UP",
            "reasons": ["test"],
        }

        ok, message = trader.open_position(
            symbol="BTCUSDT",
            side="BUY",
            price=100.0,
            position_size=1.0,
            position_value=100.0,
            stop_loss=90.0,
            decision=decision,
        )
        assert ok and message == "POSITION_OPENED"

        ok, trade = trader.close_position(110.0, "TEST")
        assert ok

        # Research-validated assumptions: 0.05% fee + 0.02% slippage each side.
        entry_exec = 100.0 * 1.0002
        exit_exec = 110.0 * 0.9998
        expected_slippage = abs(entry_exec - 100.0) + abs(exit_exec - 110.0)
        expected_fees = (entry_exec + exit_exec) * 0.0005
        expected_net = (exit_exec - entry_exec) - expected_fees

        assert abs(trade["pnl"] - 10.0) < 1e-12
        assert abs(trade["slippage"] - expected_slippage) < 1e-12
        assert abs(trade["fees"] - expected_fees) < 1e-12
        assert abs(trade["net_pnl"] - expected_net) < 1e-12
        assert abs(trader.capital - (1000.0 + expected_net)) < 1e-12
        assert abs(trader.daily_pnl - expected_net) < 1e-12

        row = database.get_account_state()
        assert abs(row["capital"] - trader.capital) < 1e-12

    database.DB_PATH = original_db
    print("NET P/L TEST: PASS")


if __name__ == "__main__":
    main()
