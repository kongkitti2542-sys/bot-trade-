import requests
from datetime import date


FX_URL = "https://api.frankfurter.app/latest?from=USD&to=THB"


def get_usdthb(timeout: int = 10) -> dict:
    response = requests.get(FX_URL, timeout=timeout)
    response.raise_for_status()

    data = response.json()

    if data.get("base") != "USD":
        raise ValueError("INVALID_FX_BASE")

    rates = data.get("rates")
    if not isinstance(rates, dict):
        raise ValueError("INVALID_FX_RATES")

    if "THB" not in rates:
        raise ValueError("THB_RATE_NOT_FOUND")

    usdthb = float(rates["THB"])

    if usdthb <= 0:
        raise ValueError("INVALID_USDTHB")

    rate_date = data.get("date")
    if not rate_date:
        raise ValueError("MISSING_RATE_DATE")

    return {
        "provider": "frankfurter.app",
        "base": "USD",
        "quote": "THB",
        "usdthb": usdthb,
        "rate_date": rate_date,
        "fetched_at": date.today().isoformat(),
    }


if __name__ == "__main__":
    result = get_usdthb()

    print("FX PROVIDER TEST")
    print("Provider:", result["provider"])
    print("USD/THB:", result["usdthb"])
    print("Rate Date:", result["rate_date"])
    print("PASS")
