from items import subtotal_cents
from promotion import discount_cents
from shipping import shipping_cents


def total_cents(items: list[tuple[int, int]]) -> int:
    subtotal = subtotal_cents(items)
    payable = subtotal - discount_cents(subtotal)
    return payable + shipping_cents(payable)
