"""
MONEY MACHINE V2 contracts.

This module defines data contracts only.
It does not modify MONEY_MAKER_01, AI Judge, Risk Engine,
execution, or existing Core logic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AIQualityResult:
    decision: str
    quality: str
    reasons: List[str] = field(default_factory=list)
    source: Optional[str] = None
    model: Optional[str] = None


@dataclass
class RiskResult:
    allowed: bool
    reason: Optional[str] = None
    risk_amount: float = 0.0
    position_value: float = 0.0
    position_size: float = 0.0
    stop_loss: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


@dataclass
class PositionState:
    entry: float
    side: str
    peak_price: float
    mfe_pct: float = 0.0
    giveback_pct: float = 0.0
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    gross_pnl_pct: Optional[float] = None
    net_pnl_pct: Optional[float] = None
    net_pnl_thb: Optional[float] = None


@dataclass
class TradeRecord:
    candidate: Dict[str, Any]
    ai: AIQualityResult
    risk: RiskResult
    position: Optional[PositionState] = None
