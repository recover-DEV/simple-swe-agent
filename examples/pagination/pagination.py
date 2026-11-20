"""One-based in-memory pagination used by the repair example."""


def paginate(items: list, page: int, page_size: int) -> list:
    if page < 1 or page_size < 1:
        raise ValueError('page and page_size must be positive')
    start = page * page_size
    return items[start:start + page_size]
