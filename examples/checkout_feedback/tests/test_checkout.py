from checkout import checkout_total


def test_checkout_at_discount_and_free_shipping_thresholds():
    assert checkout_total(100) == 95
    assert checkout_total(109) == 104
    assert checkout_total(110) == 100


def test_checkout_below_discount_threshold():
    assert checkout_total(99) == 104
