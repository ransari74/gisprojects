"""Cents <-> Decimal conversion. All storage and arithmetic on the ledger is in integer cents."""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_cents(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_dollars(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENT)


def round_cents(value: Decimal) -> int:
    """Round a Decimal amount expressed in cents to a whole cent."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
