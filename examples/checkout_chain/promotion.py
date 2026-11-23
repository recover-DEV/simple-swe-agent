def discount_cents(subtotal: int) -> int:
    """Calculate the discount in cents from the order subtotal."""
    return 1_000 if subtotal > 10_000 else 0
