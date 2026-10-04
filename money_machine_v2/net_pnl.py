"""
MONEY MACHINE V2 - Net P/L calculator.

Uses the existing execution-cost assumptions.
Tax is intentionally not included until an explicit, validated
tax rule is provided.
"""

from capital_config import FEE_RATE, SLIPPAGE_RATE


def calculate_net_pnl_pct(
    gross_pnl_pct: float,
    fee_rate: float = FEE_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
) -> float:
    """
    Calculate research net P/L percentage.

    Round-trip cost:
        entry fee + exit fee
        entry slippage + exit slippage

    No tax is assumed here.
    """

    round_trip_cost = (
        2 * fee_rate
        + 2 * slippage_rate
    )

    return gross_pnl_pct - round_trip_cost


def calculate_net_pnl_thb(
    gross_pnl_pct: float,
    position_value_thb: float,
    fee_rate: float = FEE_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
) -> float:
    """
    Convert research net P/L percentage into THB.
    """

    net_pnl_pct = calculate_net_pnl_pct(
        gross_pnl_pct=gross_pnl_pct,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )

    return position_value_thb * net_pnl_pct
