from currency_layer import thb_to_usdt, usdt_to_thb


class PaperCapitalAdapter:
    def __init__(self, thb_budget: float, usdthb: float):
        if thb_budget <= 0:
            raise ValueError("THB budget must be greater than zero")
        if usdthb <= 0:
            raise ValueError("USD/THB rate must be greater than zero")

        self.thb_budget = thb_budget
        self.usdthb = usdthb
        self.usdt_budget = thb_to_usdt(thb_budget, usdthb)

    def usdt_to_thb(self, amount: float) -> float:
        return usdt_to_thb(amount, self.usdthb)

    def thb_to_usdt(self, amount: float) -> float:
        return thb_to_usdt(amount, self.usdthb)


if __name__ == "__main__":
    adapter = PaperCapitalAdapter(
        thb_budget=1500.0,
        usdthb=33.58,
    )

    print("=" * 60)
    print("PAPER CAPITAL ADAPTER TEST")
    print("=" * 60)
    print(f"THB Budget  : {adapter.thb_budget:.2f}")
    print(f"USD/THB     : {adapter.usdthb:.2f}")
    print(f"USDT Budget : {adapter.usdt_budget:.6f}")

    round_trip = adapter.usdt_to_thb(adapter.usdt_budget)
    print(f"Round Trip  : {round_trip:.2f} THB")

    assert abs(adapter.usdt_budget - (1500.0 / 33.58)) < 0.000001
    assert abs(round_trip - 1500.0) < 0.000001

    print("PAPER CAPITAL ADAPTER TEST: PASS")
