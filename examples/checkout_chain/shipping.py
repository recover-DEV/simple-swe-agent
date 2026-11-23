def shipping_cents(amount_after_discount: int) -> int:
    """Calculate shipping from the amount after the discount."""
    return 0 if amount_after_discount >= 9_000 else 500
