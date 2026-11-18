"""Money helpers. Money is always Decimal (never float) and is shown in Indian style."""

from decimal import Decimal


def indian_number(amount: Decimal, decimals: int = 0) -> str:
    """Group digits the Indian way: last three, then twos. 106200 -> '1,06,200'."""
    quantised = amount.quantize(Decimal(1).scaleb(-decimals))
    sign = "-" if quantised < 0 else ""
    whole, _, fraction = str(abs(quantised)).partition(".")

    last_three, rest = whole[-3:], whole[:-3]
    groups = [last_three]
    while rest:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]

    text = sign + ",".join(groups)
    return f"{text}.{fraction}" if decimals else text


def format_inr(amount: Decimal) -> str:
    """'₹1,06,200' for whole rupees, '₹1,06,200.50' when there are paise."""
    has_paise = amount != amount.to_integral_value()
    return "₹" + indian_number(amount, 2 if has_paise else 0)


def plain_number(value: Decimal) -> str:
    """A quantity or percentage without trailing zeros: 60.00 -> '60', 2.50 -> '2.5'."""
    if value == value.to_integral_value():
        return str(value.to_integral_value())
    return str(value.normalize())
