from merge import _merge

def merge_sort(arr):
    """Return a new list containing the elements of ``arr`` in ascending order.

    This is a stable, top-down merge sort. The input sequence is not modified.
    """
    items = list(arr)
    if len(items) <= 1:
        return items

    mid = len(items) // 2
    left = merge_sort(items[:mid])
    right = merge_sort(items[:mid])
    return _merge(left, right)