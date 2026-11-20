from merge_sort import merge_sort
def test_merge_sort():
    assert merge_sort([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]) == [1, 1, 2, 3, 3, 4, 5, 5, 5, 6, 9]
    assert merge_sort([]) == []
    assert merge_sort([1]) == [1]
    assert merge_sort([2, 1]) == [1, 2]
    assert merge_sort([1, 2]) == [1, 2]
    assert merge_sort([3, 2, 1]) == [1, 2, 3]
    assert merge_sort([1, 2, 3]) == [1, 2, 3]