def thb_to_usdt(thb_amount: float, usdthb: float) -> float:
    if thb_amount < 0:
        raise ValueError("THB amount cannot be negative")
    if usdthb <= 0:
        raise ValueError("USD/THB rate must be greater than zero")

    return thb_amount / usdthb


def usdt_to_thb(usdt_amount: float, usdthb: float) -> float:
    if usdt_amount < 0:
        raise ValueError("USDT amount cannot be negative")
    if usdthb <= 0:
        raise ValueError("USD/THB rate must be greater than zero")

    return usdt_amount * usdthb
