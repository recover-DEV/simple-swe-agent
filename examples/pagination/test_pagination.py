import pytest

from pagination import paginate


def test_first_page():
    assert paginate(['A', 'B', 'C', 'D', 'E'], 1, 2) == ['A', 'B']


def test_second_page():
    assert paginate(['A', 'B', 'C', 'D', 'E'], 2, 2) == ['C', 'D']


def test_invalid_page():
    with pytest.raises(ValueError):
        paginate(['A'], 0, 2)
