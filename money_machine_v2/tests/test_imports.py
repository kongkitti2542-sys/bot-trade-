"""Smoke tests for MONEY MACHINE V2 modules."""

from money_machine_v2.ai_quality import review_candidate
from money_machine_v2.contracts import (
    AIQualityResult,
    PositionState,
    RiskResult,
    TradeRecord,
)
from money_machine_v2.net_pnl import (
    calculate_net_pnl_pct,
    calculate_net_pnl_thb,
)
from money_machine_v2.pot_manager import PotManager
from money_machine_v2.risk_engine import evaluate
from money_machine_v2.trade_manager import TradeManager


def main():
    print("MONEY MACHINE V2 SMOKE TEST")
    print("=" * 60)

    # Contract construction
    ai = AIQualityResult(
        decision="WAIT",
        quality="LOW",
        reasons=["test"],
    )
    assert ai.decision == "WAIT"

    risk = RiskResult(
        allowed=False,
        reason="TEST",
    )
    assert risk.allowed is False

    # P/L calculation
    net_pct = calculate_net_pnl_pct(0.01)
    assert abs(net_pct - 0.0086) < 1e-12

    net_thb = calculate_net_pnl_thb(
        gross_pnl_pct=0.01,
        position_value_thb=1000.0,
    )
    assert abs(net_thb - 8.6) < 1e-9

    # Pot
    pot = PotManager(1500.0)
    assert pot.current_pot() == 1500.0

    pot.apply_net_pnl(8.6)
    assert abs(pot.current_pot() - 1508.6) < 1e-9

    # Trade manager
    manager = TradeManager()
    assert manager.has_position is False

    manager.open_position(
        entry=100.0,
        side="BUY",
    )

    manager.update(
        high=101.0,
        low=99.5,
    )

    assert manager.has_position is True
    assert manager.position.mfe_pct > 0

    closed = manager.close(
        exit_price=100.5,
        exit_reason="TEST",
    )

    assert closed.gross_pnl_pct > 0
    assert manager.has_position is False

    print("PASS: contracts")
    print("PASS: net P/L")
    print("PASS: Pot")
    print("PASS: Trade Manager")
    print()
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
