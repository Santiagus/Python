"""Safe financial currency management and minor unit (cents) arithmetic.

Provides the immutable Money value object and utility functions for exact,
lossless currency handling, string parsing, and ratio calculations using
integer minor units (cents for USD) and python's decimal.Decimal.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Self


class Money:
    """Immutable monetary amount backed by an integer minor unit (cents for USD)."""

    __slots__ = ("_cents", "_currency")

    def __init__(self, cents: int | Decimal, currency: str = "USD") -> None:
        if isinstance(cents, Decimal):
            self._cents: int = int(cents.to_integral_exact(rounding=ROUND_HALF_UP))
        else:
            self._cents = int(cents)
        self._currency: str = currency.upper()

    @classmethod
    def from_cents(cls, cents: int, currency: str = "USD") -> Self:
        """Instantiate Money directly from minor unit integer cents."""
        return cls(cents=cents, currency=currency)

    @classmethod
    def from_major(cls, amount: Decimal | str | int | float, currency: str = "USD") -> Self:
        """Instantiate Money from major unit amount (e.g. $1,450,000.00).

        Uses exact Decimal string parsing to avoid IEEE 754 binary floating-point drift.
        """
        if isinstance(amount, float):
            d = Decimal(str(amount))
        elif isinstance(amount, Decimal):
            d = amount
        else:
            clean = str(amount).replace("$", "").replace(",", "").strip().replace("+", "")
            d = Decimal(clean)
        cents = int((d * Decimal(100)).to_integral_exact(rounding=ROUND_HALF_UP))
        return cls(cents=cents, currency=currency)

    @classmethod
    def zero(cls, currency: str = "USD") -> Self:
        """Return a zero-value Money instance."""
        return cls(cents=0, currency=currency)

    @property
    def cents(self) -> int:
        """Return integer amount in minor units (cents)."""
        return self._cents

    @property
    def currency(self) -> str:
        """Return three-letter ISO currency code."""
        return self._currency

    def to_decimal(self) -> Decimal:
        """Convert minor units back to major units as a 2-decimal-place Decimal."""
        return (Decimal(self._cents) / Decimal(100)).quantize(Decimal("0.01"))

    def to_major_float(self) -> float:
        """Convert to standard Python float for legacy serialization boundaries."""
        return float(self.to_decimal())

    def format(self) -> str:
        """Format as a human-readable USD currency string (e.g. '$1,250.75')."""
        dec = self.to_decimal()
        return f"${dec:,.2f}"

    def __add__(self, other: Any) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise ValueError(f"Cannot add different currencies: {self._currency} and {other._currency}")
        return Money(self._cents + other._cents, self._currency)

    def __sub__(self, other: Any) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise ValueError(f"Cannot subtract different currencies: {self._currency} and {other._currency}")
        return Money(self._cents - other._cents, self._currency)

    def __mul__(self, other: int | Decimal) -> Money:
        if isinstance(other, int):
            return Money(self._cents * other, self._currency)
        if isinstance(other, Decimal):
            new_cents = int((Decimal(self._cents) * other).to_integral_exact(rounding=ROUND_HALF_UP))
            return Money(new_cents, self._currency)
        return NotImplemented

    def __truediv__(self, other: int | Decimal | Money) -> Any:
        if isinstance(other, (int, Decimal)):
            if other == 0:
                raise ZeroDivisionError("division by zero")
            new_cents = int((Decimal(self._cents) / Decimal(other)).to_integral_exact(rounding=ROUND_HALF_UP))
            return Money(new_cents, self._currency)
        if isinstance(other, Money):
            if other._cents == 0:
                raise ZeroDivisionError("division by zero")
            if self._currency != other._currency:
                raise ValueError(f"Cannot divide different currencies: {self._currency} and {other._currency}")
            return Decimal(self._cents) / Decimal(other._cents)
        return NotImplemented

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Money):
            return self._cents == other._cents and self._currency == other._currency
        return False

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise ValueError(f"Cannot compare different currencies: {self._currency} and {other._currency}")
        return self._cents < other._cents

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise ValueError(f"Cannot compare different currencies: {self._currency} and {other._currency}")
        return self._cents <= other._cents

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise ValueError(f"Cannot compare different currencies: {self._currency} and {other._currency}")
        return self._cents > other._cents

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise ValueError(f"Cannot compare different currencies: {self._currency} and {other._currency}")
        return self._cents >= other._cents

    def __repr__(self) -> str:
        return f"Money({self._cents} {self._currency} cents, {self.format()})"

    def __str__(self) -> str:
        return self.format()


def parse_currency_to_cents(val_str: str | None) -> int | None:
    """Parse raw text currency string directly to minor unit integer cents.

    Returns None if input is empty, None, or unparseable.
    """
    if not val_str:
        return None
    clean = val_str.replace("$", "").replace(",", "").strip().replace("+", "")
    if not clean:
        return None
    try:
        d = Decimal(clean)
        return int((d * Decimal(100)).to_integral_exact(rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def parse_currency_to_decimal(val_str: str | None) -> Decimal | None:
    """Parse raw text currency string to 2-decimal-place major unit Decimal."""
    cents = parse_currency_to_cents(val_str)
    return cents_to_decimal(cents)


def cents_to_decimal(cents: int | None) -> Decimal | None:
    """Losslessly convert minor unit integer cents to 2-decimal-place Decimal."""
    if cents is None:
        return None
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def decimal_to_cents(d: Decimal | float | int | None) -> int | None:
    """Convert major unit Decimal, int, or float to minor unit integer cents."""
    if d is None:
        return None
    if isinstance(d, int):
        return d * 100
    if isinstance(d, float):
        d = Decimal(str(d))
    return int((d * Decimal(100)).to_integral_exact(rounding=ROUND_HALF_UP))


def safe_divide_ratio(
    numerator_cents: int,
    denominator_cents: int,
    precision: int = 3,
) -> Decimal:
    """Calculate a dimensionless financial ratio (e.g. DSCR) using Decimal division.

    Uses ROUND_HALF_UP rounding to eliminate floating-point drift.
    """
    if denominator_cents == 0:
        quant = Decimal("1." + "0" * precision)
        return Decimal(0).quantize(quant)
    ratio = Decimal(numerator_cents) / Decimal(denominator_cents)
    quant = Decimal("1." + "0" * precision)
    return ratio.quantize(quant, rounding=ROUND_HALF_UP)

