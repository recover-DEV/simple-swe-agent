from merge import _merge
def test_merge():
    assert _merge([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]
    assert _merge([], []) == []
    assert _merge([1], []) == [1]
    assert _merge([], [1]) == [1]
    assert _merge([1], [2]) == [1, 2]
    assert _merge([2], [1]) == [1, 2]