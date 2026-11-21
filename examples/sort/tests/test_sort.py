from sort import quick_sort

def test_quick_sort():
    assert quick_sort([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]) == [1, 1, 2, 3, 3, 4, 5, 5, 5, 6, 9]
    assert quick_sort([]) == []
    assert quick_sort([1]) == [1]
    assert quick_sort([2, 1]) == [1, 2]
    assert quick_sort([1, 2]) == [1, 2]
    assert quick_sort([3, 2, 1]) == [1, 2, 3]
    assert quick_sort([1, 2, 3]) == [1, 2, 3]