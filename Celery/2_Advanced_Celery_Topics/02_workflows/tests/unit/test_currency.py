"""Unit tests for safe currency management, Money class, and minor unit arithmetic."""

from decimal import Decimal
import pytest

from app.currency import (
    Money,
    cents_to_decimal,
    decimal_to_cents,
    parse_currency_to_cents,
    parse_currency_to_decimal,
    safe_divide_ratio,
)


class TestMoneyClass:
    """Test Money value object operations, conversions, and comparisons."""

    def test_money_initialization_and_properties(self) -> None:
        """Money initializes from integer cents or Decimal cents with correct properties."""
        m1 = Money(150000)
        assert m1.cents == 150000
        assert m1.currency == "USD"
        assert m1.to_decimal() == Decimal("1500.00")
        assert m1.to_major_float() == 1500.00
        assert str(m1) == "$1,500.00"
        assert "Money(150000 USD cents" in repr(m1)

        m2 = Money(Decimal("150000.4"), currency="eur")
        assert m2.cents == 150000
        assert m2.currency == "EUR"

    def test_money_from_major(self) -> None:
        """Money.from_major handles Decimal, str, float, and int without precision loss."""
        assert Money.from_major("250,000.50").cents == 25000050
        assert Money.from_major("$1,450,000.00").cents == 145000000
        assert Money.from_major(Decimal("100.25")).cents == 10025
        assert Money.from_major(500).cents == 50000
        assert Money.from_major(100.25).cents == 10025

    def test_money_zero_and_from_cents(self) -> None:
        """Money.zero and Money.from_cents create valid instances."""
        z = Money.zero()
        assert z.cents == 0
        assert z.to_decimal() == Decimal("0.00")

        c = Money.from_cents(5000)
        assert c.cents == 5000
        assert c.to_decimal() == Decimal("50.00")

    def test_money_addition_and_subtraction(self) -> None:
        """Money supports addition and subtraction with currency check."""
        m1 = Money(10000)  # $100.00
        m2 = Money(5050)   # $50.50

        add_res = m1 + m2
        assert add_res.cents == 15050
        assert add_res.to_decimal() == Decimal("150.50")

        sub_res = m1 - m2
        assert sub_res.cents == 4950
        assert sub_res.to_decimal() == Decimal("49.50")

        # Incompatible currency raises ValueError
        m_eur = Money(1000, currency="EUR")
        with pytest.raises(ValueError, match="Cannot add different currencies"):
            _ = m1 + m_eur
        with pytest.raises(ValueError, match="Cannot subtract different currencies"):
            _ = m1 - m_eur

        # Incompatible type returns NotImplemented
        assert m1.__add__(50) is NotImplemented
        assert m1.__sub__(50) is NotImplemented

    def test_money_multiplication_and_division(self) -> None:
        """Money supports multiplication and division by scalar or other Money."""
        m = Money(10000)

        # Mul by int and Decimal
        assert (m * 2).cents == 20000
        assert (m * Decimal("1.5")).cents == 15000
        assert m.__mul__("invalid") is NotImplemented

        # Div by int and Decimal
        assert (m / 2).cents == 5000
        assert (m / Decimal("4")).cents == 2500
        with pytest.raises(ZeroDivisionError):
            _ = m / 0

        # Div by Money returns Decimal ratio
        m2 = Money(5000)
        ratio = m / m2
        assert isinstance(ratio, Decimal)
        assert ratio == Decimal("2")

        with pytest.raises(ZeroDivisionError):
            _ = m / Money.zero()

        m_eur = Money(5000, currency="EUR")
        with pytest.raises(ValueError, match="Cannot divide different currencies"):
            _ = m / m_eur

        assert m.__truediv__("invalid") is NotImplemented

    def test_money_comparisons(self) -> None:
        """Money supports rich comparisons (<, <=, ==, >, >=) and validates currency."""
        m1 = Money(10000)
        m2 = Money(10000)
        m3 = Money(20000)

        assert m1 == m2
        assert m1 != m3
        assert m1 != "not-money"
        assert m1 < m3
        assert m1 <= m2
        assert m3 > m1
        assert m3 >= m2

        m_eur = Money(10000, currency="EUR")
        assert m1 != m_eur
        with pytest.raises(ValueError, match="Cannot compare different currencies"):
            _ = m1 < m_eur
        with pytest.raises(ValueError, match="Cannot compare different currencies"):
            _ = m1 <= m_eur
        with pytest.raises(ValueError, match="Cannot compare different currencies"):
            _ = m1 > m_eur
        with pytest.raises(ValueError, match="Cannot compare different currencies"):
            _ = m1 >= m_eur

        assert m1.__lt__("invalid") is NotImplemented
        assert m1.__le__("invalid") is NotImplemented
        assert m1.__gt__("invalid") is NotImplemented
        assert m1.__ge__("invalid") is NotImplemented


class TestCurrencyUtilities:
    """Test helper functions for parsing, conversions, and financial ratios."""

    def test_parse_currency_to_cents(self) -> None:
        """parse_currency_to_cents parses formatted strings to integer cents."""
        assert parse_currency_to_cents(None) is None
        assert parse_currency_to_cents("") is None
        assert parse_currency_to_cents("   ") is None
        assert parse_currency_to_cents("NOT_A_NUM") is None

        assert parse_currency_to_cents("$1,450,000.00") == 145000000
        assert parse_currency_to_cents("+$32,549.50") == 3254950
        assert parse_currency_to_cents("480000") == 48000000
        assert parse_currency_to_cents("-500.25") == -50025

    def test_parse_currency_to_decimal(self) -> None:
        """parse_currency_to_decimal parses strings to 2-decimal-place Decimal."""
        assert parse_currency_to_decimal(None) is None
        assert parse_currency_to_decimal("") is None
        assert parse_currency_to_decimal("$1,250.75") == Decimal("1250.75")

    def test_cents_to_decimal_and_reverse(self) -> None:
        """cents_to_decimal and decimal_to_cents accurately convert values."""
        assert cents_to_decimal(None) is None
        assert cents_to_decimal(125075) == Decimal("1250.75")

        assert decimal_to_cents(None) is None
        assert decimal_to_cents(100) == 10000
        assert decimal_to_cents(100.25) == 10025
        assert decimal_to_cents(Decimal("1250.75")) == 125075

    def test_safe_divide_ratio(self) -> None:
        """safe_divide_ratio calculates ratios with Decimal precision and handles div by zero."""
        assert safe_divide_ratio(100000, 0) == Decimal("0.000")
        assert safe_divide_ratio(24450000, 7523077, precision=2) == Decimal("3.25")
        assert safe_divide_ratio(24450000, 7523077, precision=3) == Decimal("3.250")

