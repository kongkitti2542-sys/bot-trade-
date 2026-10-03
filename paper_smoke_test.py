from paper_trader import PaperTrader
from position_manager import monitor_position


class SmokeTrader(PaperTrader):
    def __init__(self):
        self.starting_capital = 1000.0
        self.capital = 1000.0
        self.daily_pnl = 0.0
        self.position = None

    def open_position(
        self,
        symbol,
        side,
        price,
        position_size,
        position_value,
        stop_loss,
        decision,
    ):
        self.position = {
            "id": 999,
            "symbol": symbol,
            "side": side,
            "entry_price": price,
            "position_size": position_size,
            "position_value": position_value,
            "stop_loss": stop_loss,
            "strategy_score": decision["score"],
            "confidence": decision["confidence"],
            "regime": decision["regime"],
            "reason": ", ".join(decision["reasons"]),
            "opened_at": "SMOKE_TEST",
        }
        return True, "POSITION_OPENED"

    def close_position(self, price, exit_reason):
        if self.position is None:
            return False, "NO_POSITION"

        position = self.position

        if position["side"] == "BUY":
            pnl = (price - position["entry_price"]) * position["position_size"]
        else:
            pnl = (position["entry_price"] - price) * position["position_size"]

        self.capital += pnl
        self.daily_pnl += pnl
        self.position = None

        return True, {
            "pnl": pnl,
            "exit_reason": exit_reason,
        }


def main():
    print("=" * 60)
    print("PAPER SMOKE TEST")
    print("=" * 60)

    trader = SmokeTrader()

    decision = {
        "score": 80,
        "confidence": 80,
        "regime": "TREND_UP",
        "reasons": ["Synthetic smoke test"],
    }

    entry_price = 100.0
    stop_loss = 98.0
    position_size = 1.0

    opened, message = trader.open_position(
        symbol="SMOKE",
        side="BUY",
        price=entry_price,
        position_size=position_size,
        position_value=100.0,
        stop_loss=stop_loss,
        decision=decision,
    )

    assert opened
    assert trader.position is not None

    print(f"ENTRY:       ${entry_price:.2f}")
    print(f"STOP LOSS:   ${stop_loss:.2f}")
    print(f"POSITION:    {trader.position['symbol']} {trader.position['side']}")

    closed, result = monitor_position(
        trader=trader,
        current_price=98.0,
    )

    assert closed
    assert result["exit_reason"] == "STOP_LOSS"
    assert trader.position is None
    assert trader.capital == 998.0

    print(f"EXIT:        $98.00")
    print(f"EXIT REASON: {result['exit_reason']}")
    print(f"P/L:         ${result['pnl']:.2f}")
    print(f"CAPITAL:     ${trader.capital:.2f}")
    print()
    print("SMOKE TEST: PASS")


if __name__ == "__main__":
    main()
