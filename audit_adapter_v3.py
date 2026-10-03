from data import get_closed_candles
from money_maker_01_adapter_v1 import find_candidates

print("=" * 72)
print("MONEY MAKER #1 ADAPTER AUDIT V3")
print("=" * 72)

candles = get_closed_candles(
    symbol="BTCUSDT",
    interval="5m",
    limit=10000,
)

print(f"Candles : {len(candles)}")
print(f"Latest  : {candles[-1]['time']}")
print()

candidates = find_candidates(candles)

print(f"Candidates found : {len(candidates)}")
print()

if not candidates:
    print("NO CANDIDATES")
else:
    print("LATEST 10 CANDIDATES")
    print("-" * 72)

    for candidate in candidates[-10:]:
        print(
            f"Signal       : {candidate['signal_time']} | "
            f"Entry        : {candidate['entry_time']} | "
            f"Entry Price  : {candidate['entry']:.2f}"
        )

    print()
    print("-" * 72)

    latest = candidates[-1]

    print("LATEST CANDIDATE")
    print(f"Signal       : {latest['signal_time']}")
    print(f"Entry        : {latest['entry_time']}")
    print(f"Price        : {latest['entry']:.2f}")
    print(f"Setup        : {latest['setup']}")

    print()
    print("FEATURES")
    for key, value in latest["features"].items():
        print(f"{key:24}: {value}")

    print()
    print("=" * 72)
    print("COMPARISON")
    print("=" * 72)
    print(f"Latest candle       : {candles[-1]['time']}")
    print(f"Latest candidate    : {latest['signal_time']}")
    print(
        f"Candidate == latest : "
        f"{latest['signal_time'] == candles[-1]['time']}"
    )

print("=" * 72)
