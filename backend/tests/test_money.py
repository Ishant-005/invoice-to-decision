from decimal import Decimal

import pytest

from app.money import format_inr, indian_number


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0", "0"),
        ("999", "999"),
        ("1000", "1,000"),
        ("85904", "85,904"),
        ("106200", "1,06,200"),
        ("1234567", "12,34,567"),
        ("123456789", "12,34,56,789"),
        ("-106200", "-1,06,200"),
    ],
)
def test_indian_number_grouping(amount, expected):
    assert indian_number(Decimal(amount)) == expected


def test_indian_number_with_decimals():
    assert indian_number(Decimal(212400), decimals=2) == "2,12,400.00"


def test_format_inr_hides_zero_paise_and_shows_real_paise():
    assert format_inr(Decimal("106200.00")) == "₹1,06,200"
    assert format_inr(Decimal("106200.50")) == "₹1,06,200.50"
