def quick_sort(arr):
    # 基线条件：数组长度<=1直接返回
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]  # 选中间元素作为基准
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + quick_sort(right)