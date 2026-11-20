def _merge(left, right):
    """Merge two already-sorted lists into a single sorted list."""
    merged = []
    i = j = 0
    while i < len(left) and j < len(right):
        # Use <= so that equal elements keep their original relative order.
        if left[i] <= right[j]:
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1

    return merged
