def subtotal_cents(items: list[tuple[int, int]]) -> int:
    """Sum the line amounts for (unit price in cents, quantity) pairs."""
    return sum(unit_price for unit_price, quantity in items)
