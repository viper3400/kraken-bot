from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


MONEY_QUANTUM = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.00000001")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
