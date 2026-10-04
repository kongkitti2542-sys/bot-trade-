"""
MONEY MACHINE V2 - Trade lifecycle state.

Tracks an already-approved position.
No signal generation.
No AI decision.
No risk calculation.
No Profit Lock decision.
"""

from .contracts import PositionState


class TradeManager:
    def __init__(self):
        self.position = None

    @property
    def has_position(self):
        return self.position is not None

    def open_position(self, entry: float, side: str = "BUY"):
        if self.position is not None:
            raise RuntimeError("POSITION_ALREADY_OPEN")

        if entry <= 0:
            raise ValueError("INVALID_ENTRY")

        if side not in {"BUY", "SELL"}:
            raise ValueError("INVALID_SIDE")

        self.position = PositionState(
            entry=entry,
            side=side,
            peak_price=entry,
        )

    def update(self, high: float, low: float):
        if self.position is None:
            raise RuntimeError("NO_OPEN_POSITION")

        if high <= 0 or low <= 0:
            raise ValueError("INVALID_PRICE")

        entry = self.position.entry

        if self.position.side == "BUY":
            favorable_price = high
            adverse_price = low

            self.position.peak_price = max(
                self.position.peak_price,
                favorable_price,
            )

            self.position.mfe_pct = (
                self.position.peak_price / entry
            ) - 1

            current_gross_pct = (
                adverse_price / entry
            ) - 1

        else:
            favorable_price = low
            adverse_price = high

            self.position.peak_price = min(
                self.position.peak_price,
                favorable_price,
            )

            self.position.mfe_pct = (
                entry / self.position.peak_price
            ) - 1

            current_gross_pct = (
                entry / adverse_price
            ) - 1

        self.position.giveback_pct = (
            self.position.mfe_pct - current_gross_pct
        )

        return self.position

    def close(
        self,
        exit_price: float,
        exit_reason: str,
    ):
        if self.position is None:
            raise RuntimeError("NO_OPEN_POSITION")

        if exit_price <= 0:
            raise ValueError("INVALID_EXIT_PRICE")

        if self.position.side == "BUY":
            gross_pnl_pct = (exit_price / self.position.entry) - 1
        else:
            gross_pnl_pct = (self.position.entry / exit_price) - 1

        self.position.exit_price = exit_price
        self.position.exit_reason = exit_reason
        self.position.gross_pnl_pct = gross_pnl_pct

        closed = self.position
        self.position = None

        return closed
