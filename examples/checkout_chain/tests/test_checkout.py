from checkout import total_cents
from items import subtotal_cents
from promotion import discount_cents
from shipping import shipping_cents


def test_subtotal_counts_quantity():
    assert subtotal_cents([(5_000, 2), (1_000, 1)]) == 11_000


def test_discount_at_threshold():
    assert discount_cents(9_999) == 0
    assert discount_cents(10_000) == 1_000


def test_shipping_below_threshold():
    assert shipping_cents(9_000) == 500
    assert shipping_cents(10_000) == 0


def test_checkout_at_discount_threshold():
    assert total_cents([(5_000, 2)]) == 9_500


def test_small_order():
    assert total_cents([(1_500, 1)]) == 2_000
