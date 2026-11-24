def checkout_total(subtotal: int) -> int:
    discount = 10 if subtotal > 100 else 0
    shipping = 0 if subtotal >= 100 else 5
    return subtotal - discount + shipping
