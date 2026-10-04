"""
MONEY MACHINE V2 - Pot Manager.

Pot changes only from validated net P/L.
No strategy logic.
No AI logic.
No risk logic.
No exit logic.
"""

from dataclasses import dataclass


@dataclass
class PotManager:
    pot_thb: float

    def apply_net_pnl(self, net_pnl_thb: float) -> float:
        """
        Apply one completed trade's validated net P/L to the Pot.
        """

        self.pot_thb += net_pnl_thb

        return self.pot_thb

    def current_pot(self) -> float:
        return self.pot_thb
