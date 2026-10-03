from data import get_closed_candles
from features import calculate_features
from regime import detect_regime
from strategy import analyze_market
from capital_config import STARTING_CAPITAL_USDT


# ============================================================
# RISK SETTINGS
# ============================================================

STARTING_CAPITAL = STARTING_CAPITAL_USDT

RISK_PER_TRADE = 0.005       # 0.5%
MAX_DAILY_LOSS = 0.03        # 3%
MAX_POSITION_VALUE = 0.25     # 25% of capital

# Strategy V1 uses explicit quality gating instead of legacy score confidence.
# Kept only for backward compatibility with older callers.
MIN_CONFIDENCE = 0

ATR_STOP_MULTIPLIER = 2.0


# ============================================================
# RISK ENGINE
# ============================================================

def evaluate_risk(
    decision,
    features,
    capital=STARTING_CAPITAL,
    daily_pnl=0.0,
    open_positions=0
):
    reasons = []
    warnings = []

    signal = decision["signal"]
    confidence = decision["confidence"]
    quality = decision.get("quality", "PASSED")

    price = features["close"]
    atr = features["atr14"]

    # --------------------------------------------------------
    # Default result
    # --------------------------------------------------------

    result = {
        "allowed": False,
        "reason": None,
        "risk_amount": 0.0,
        "position_value": 0.0,
        "position_size": 0.0,
        "stop_loss": None,
        "warnings": warnings,
    }

    # --------------------------------------------------------
    # 1. No trade signal
    # --------------------------------------------------------

    if signal == "WAIT":
        result["reason"] = "STRATEGY_WAIT"
        return result

    # --------------------------------------------------------
    # 2. Confidence
    # --------------------------------------------------------

    if confidence < MIN_CONFIDENCE:
        result["reason"] = "CONFIDENCE_TOO_LOW"
        return result

    # --------------------------------------------------------
    # 3. Daily loss protection
    # --------------------------------------------------------

    daily_loss_limit = capital * MAX_DAILY_LOSS

    if daily_pnl <= -daily_loss_limit:
        result["reason"] = "DAILY_LOSS_LIMIT"
        return result

    # --------------------------------------------------------
    # 4. Maximum open positions
    # --------------------------------------------------------

    if open_positions >= 1:
        result["reason"] = "POSITION_LIMIT"
        return result

    # --------------------------------------------------------
    # 5. Validate market data
    # --------------------------------------------------------

    if atr is None or atr <= 0:
        result["reason"] = "INVALID_ATR"
        return result

    if price <= 0:
        result["reason"] = "INVALID_PRICE"
        return result

    # --------------------------------------------------------
    # 6. Calculate risk amount
    # --------------------------------------------------------

    risk_amount = capital * RISK_PER_TRADE

    # --------------------------------------------------------
    # 7. Calculate Stop Loss
    # --------------------------------------------------------

    stop_distance = atr * ATR_STOP_MULTIPLIER

    if signal == "BUY":
        stop_loss = price - stop_distance

    elif signal == "SELL":
        stop_loss = price + stop_distance

    else:
        result["reason"] = "UNKNOWN_SIGNAL"
        return result

    if stop_loss <= 0:
        result["reason"] = "INVALID_STOP_LOSS"
        return result

    # --------------------------------------------------------
    # 8. Position sizing
    # --------------------------------------------------------

    position_size = risk_amount / stop_distance

    position_value = position_size * price

    # --------------------------------------------------------
    # 9. Maximum exposure
    # --------------------------------------------------------

    max_position_value = capital * MAX_POSITION_VALUE

    if position_value > max_position_value:

        position_value = max_position_value

        position_size = position_value / price

        warnings.append(
            "Position size capped by maximum exposure"
        )

    # --------------------------------------------------------
    # 10. Final approval
    # --------------------------------------------------------

    reasons.append("Signal accepted")
    reasons.append("Strategy quality passed")
    reasons.append("Daily loss limit not exceeded")
    reasons.append("Position limit available")
    reasons.append("Market data valid")
    reasons.append("Stop loss calculated")

    result["allowed"] = True
    result["reason"] = "RISK_APPROVED"

    result["risk_amount"] = risk_amount
    result["position_value"] = position_value
    result["position_size"] = position_size
    result["stop_loss"] = stop_loss

    result["reasons"] = reasons

    return result


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    candles = get_closed_candles(
        symbol="BTCUSDT",
        interval="5m",
        limit=250
    )

    features = calculate_features(candles)

    regime = detect_regime(features)

    decision = analyze_market(
        features,
        regime
    )

    risk = evaluate_risk(
        decision=decision,
        features=features,
        capital=STARTING_CAPITAL_USDT,
        daily_pnl=0.0,
        open_positions=0
    )

    print()
    print("BTC/USDT - RISK MANAGER")
    print("=" * 60)

    print(f"Capital:        ${STARTING_CAPITAL_USDT:.2f}")
    print(f"Price:          ${features['close']:.2f}")
    print(f"Signal:         {decision['signal']}")
    print(f"Confidence:     {decision['confidence']}/100")
    print(f"Regime:         {decision['regime']}")

    print()
    print("RISK DECISION")
    print("-" * 60)

    if risk["allowed"]:
        print("🟢 ALLOW")

        print()
        print(f"Risk Amount:    ${risk['risk_amount']:.2f}")
        print(f"Position Value: ${risk['position_value']:.2f}")
        print(f"Position Size:  {risk['position_size']:.8f} BTC")
        print(f"Stop Loss:      ${risk['stop_loss']:.2f}")

    else:
        print("🔴 REJECT")
        print(f"Reason:         {risk['reason']}")

    print()
    print("WARNINGS")
    print("-" * 60)

    if risk["warnings"]:
        for warning in risk["warnings"]:
            print(f"! {warning}")
    else:
        print("None")
