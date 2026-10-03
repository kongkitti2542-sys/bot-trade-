from collections import deque, defaultdict
from datetime import datetime, timezone

from backtest_data_100k import get_historical_candles_100k, validate_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk
from capital_config import STARTING_CAPITAL_USDT


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000

MAX_HOLD_BARS = 240
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"
HISTORY_SIZE = 250


def snapshot_features(features, candles):
    close = features["close"]
    ema20 = features["ema20"]
    ema50 = features["ema50"]
    ema200 = features["ema200"]
    atr14 = features["atr14"]
    bb = features["bollinger"]
    structure = features["structure"]

    def pct_diff(a, b):
        if a is None or b in (None, 0):
            return None
        return (a - b) / b * 100.0

    snapshot = {
        "time": features["time"],
        "close": close,

        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,

        "rsi14": features["rsi14"],
        "atr14": atr14,
        "atr_pct": (
            atr14 / close * 100.0
            if atr14 is not None and close
            else None
        ),

        "relative_volume": features["relative_volume"],

        "bb_width": (
            bb["width"]
            if bb is not None
            else None
        ),

        "price_vs_ema20_pct": pct_diff(close, ema20),
        "price_vs_ema50_pct": pct_diff(close, ema50),
        "price_vs_ema200_pct": pct_diff(close, ema200),

        "ema20_vs_ema50_pct": pct_diff(ema20, ema50),
        "ema50_vs_ema200_pct": pct_diff(ema50, ema200),

        "structure": (
            structure["structure"]
            if structure is not None
            else None
        ),

        "higher_high": (
            structure["higher_high"]
            if structure is not None
            else None
        ),

        "higher_low": (
            structure["higher_low"]
            if structure is not None
            else None
        ),

        "lower_high": (
            structure["lower_high"]
            if structure is not None
            else None
        ),

        "lower_low": (
            structure["lower_low"]
            if structure is not None
            else None
        ),
    }

    # --------------------------------------------------
    # Pullback / recovery snapshot
    # This reproduces the V2 observation window.
    # --------------------------------------------------
    if (
        len(candles) >= 6
        and ema20 is not None
        and ema50 is not None
    ):
        recent = candles[-6:-1]
        current = candles[-1]

        pullback_low = min(c["low"] for c in recent)
        recovery_high = max(c["high"] for c in recent)

        snapshot["pullback_depth_pct"] = (
            (pullback_low - ema20) / ema20 * 100.0
        )

        snapshot["ema50_buffer_pct"] = (
            (pullback_low - ema50) / ema50 * 100.0
        )

        snapshot["recovery_strength_pct"] = (
            (current["close"] - recovery_high)
            / recovery_high
            * 100.0
        )

        snapshot["touched_ema20"] = any(
            c["low"] <= ema20
            for c in recent
        )

        snapshot["held_ema50"] = min(
            c["low"] for c in recent
        ) > ema50

        snapshot["recovery_confirmed"] = (
            current["close"] > recent[-1]["high"]
        )
    else:
        for key in (
            "pullback_depth_pct",
            "ema50_buffer_pct",
            "recovery_strength_pct",
        ):
            snapshot[key] = None

        snapshot["touched_ema20"] = None
        snapshot["held_ema50"] = None
        snapshot["recovery_confirmed"] = None

    return snapshot


def close_position(position, exit_price, exit_time, exit_reason):
    gross_pnl = (
        exit_price - position["entry_price"]
    ) * position["position_size"]

    return {
        "entry_time": position["entry_time"],
        "exit_time": exit_time,
        "side": position["side"],
        "entry_price": position["entry_price"],
        "exit_price": exit_price,
        "position_size": position["position_size"],
        "setup": position["setup"],
        "bars_held": position["bars_held"],
        "gross_pnl": gross_pnl,
        "exit_reason": exit_reason,
        "features": position["features"],
    }


def run(candles, boundary):
    capital = STARTING_CAPITAL_USDT
    position = None
    trades = []

    feature_engine = IncrementalFeatures()
    candle_history = deque(maxlen=HISTORY_SIZE)

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)
        candle_history.append(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        # --------------------------------------------------
        # Manage existing position first
        # --------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

            if candle["low"] <= position["stop_loss"]:
                trade = close_position(
                    position,
                    position["stop_loss"],
                    candle_time,
                    "STOP_LOSS",
                )
                capital += trade["gross_pnl"]
                trades.append(trade)
                position = None
                continue

            if position["bars_held"] >= MAX_HOLD_BARS:
                trade = close_position(
                    position,
                    candle["close"],
                    candle_time,
                    "TIME_EXIT",
                )
                capital += trade["gross_pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        # --------------------------------------------------
        # OOS boundary
        # --------------------------------------------------
        if candle_time < boundary:
            continue

        regime = detect_regime(features)

        decision = analyze_market(
            list(candle_history),
            features,
            regime,
        )

        # Only the exact candidate under investigation.
        if (
            decision.get("signal") != "BUY"
            or decision.get("setup") != "TREND_PULLBACK"
        ):
            continue

        risk = evaluate_risk(
            decision,
            features,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            continue

        position = {
            "side": "BUY",
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "setup": decision["setup"],
            "bars_held": 0,

            # Critical: snapshot ONLY at entry.
            "features": snapshot_features(
                features,
                list(candle_history),
            ),
        }

    return capital, trades


def mean(values):
    values = [
        x for x in values
        if x is not None
    ]
    return (
        sum(values) / len(values)
        if values
        else None
    )


def print_metric(label, winner_values, loser_values):
    w = mean(winner_values)
    l = mean(loser_values)

    if w is None or l is None:
        print(f"{label:<30} Winner=N/A  Loser=N/A")
        return

    print(
        f"{label:<30} "
        f"Winner={w:>10.5f}  "
        f"Loser={l:>10.5f}  "
        f"Diff={w-l:>10.5f}"
    )


def main():
    print("=" * 100)
    print("TREND_PULLBACK + BUY — EDGE FINGERPRINT")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {valid}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY}")
    print(f"Starting Pot:   ${STARTING_CAPITAL_USDT:.4f}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY
    ).astimezone(timezone.utc)

    final_capital, trades = run(
        candles,
        boundary,
    )

    winners = [
        t for t in trades
        if t["gross_pnl"] > 0
    ]

    losers = [
        t for t in trades
        if t["gross_pnl"] < 0
    ]

    print()
    print("=" * 100)
    print("CANDIDATE RESULT")
    print("=" * 100)

    print(f"Trades:             {len(trades)}")
    print(f"Winners:            {len(winners)}")
    print(f"Losers:             {len(losers)}")
    print(
        f"Gross P/L:          "
        f"${sum(t['gross_pnl'] for t in trades):.6f}"
    )
    print(
        f"Ending Gross Pot:   "
        f"${final_capital:.6f}"
    )

    print()
    print("=" * 100)
    print("ENTRY FINGERPRINT — WINNER VS LOSER")
    print("=" * 100)

    feature_fields = [
        ("RSI14", "rsi14"),
        ("ATR%", "atr_pct"),
        ("Relative Volume", "relative_volume"),
        ("BB Width", "bb_width"),

        ("Price vs EMA20 %", "price_vs_ema20_pct"),
        ("Price vs EMA50 %", "price_vs_ema50_pct"),
        ("Price vs EMA200 %", "price_vs_ema200_pct"),

        ("EMA20 vs EMA50 %", "ema20_vs_ema50_pct"),
        ("EMA50 vs EMA200 %", "ema50_vs_ema200_pct"),

        ("Pullback Depth %", "pullback_depth_pct"),
        ("EMA50 Buffer %", "ema50_buffer_pct"),
        ("Recovery Strength %", "recovery_strength_pct"),
    ]

    for label, field in feature_fields:
        print_metric(
            label,
            [
                t["features"][field]
                for t in winners
            ],
            [
                t["features"][field]
                for t in losers
            ],
        )

    print()
    print("=" * 100)
    print("ENTRY STRUCTURE")
    print("=" * 100)

    for name, key in (
        ("Structure", "structure"),
        ("Touched EMA20", "touched_ema20"),
        ("Held EMA50", "held_ema50"),
        ("Recovery Confirmed", "recovery_confirmed"),
    ):
        winner_counts = defaultdict(int)
        loser_counts = defaultdict(int)

        for trade in winners:
            winner_counts[trade["features"][key]] += 1

        for trade in losers:
            loser_counts[trade["features"][key]] += 1

        categories = sorted(
            set(winner_counts) | set(loser_counts),
            key=lambda x: str(x),
        )

        print()
        print(name)

        for category in categories:
            wc = winner_counts[category]
            lc = loser_counts[category]

            wp = (
                wc / len(winners) * 100
                if winners
                else 0
            )

            lp = (
                lc / len(losers) * 100
                if losers
                else 0
            )

            print(
                f"  {str(category):<20} "
                f"Winner {wc:>3} ({wp:>6.2f}%) | "
                f"Loser {lc:>3} ({lp:>6.2f}%)"
            )

    print()
    print("=" * 100)
    print("EXIT BREAKDOWN")
    print("=" * 100)

    for group_name, group in (
        ("WINNERS", winners),
        ("LOSERS", losers),
    ):
        stops = sum(
            t["exit_reason"] == "STOP_LOSS"
            for t in group
        )

        times = sum(
            t["exit_reason"] == "TIME_EXIT"
            for t in group
        )

        print(
            f"{group_name:<10} "
            f"STOP={stops:>3}  "
            f"TIME={times:>3}"
        )

    print()
    print("=" * 100)
    print("IMPORTANT")
    print("=" * 100)
    print(
        "These are descriptive entry fingerprints only."
    )
    print(
        "No threshold was optimized from this output."
    )
    print(
        "No future trade information was used in the entry snapshot."
    )
    print(
        "No Core files were modified."
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
