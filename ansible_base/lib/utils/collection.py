"""
Utilities for Python collections
"""


def first_matching(predicate, collection, default=StopIteration("No item matched the predicate.")):
    """
    Return the first element from `collection` that satisfies `predicate`.
    If `default` is an exception, raise it if no element satisfies `predicate`.
    If `default` is not an exception, return it if no element satisfies `predicate`.

    :param predicate: A function that takes an element from `collection` and returns a boolean.
    :param collection: An iterable.
    :param default: The value to return if no element satisfies `predicate`.
    :return: The first element from `collection` that satisfies `predicate`.
             If no element satisfies `predicate`, return `default`, or raise an exception if `default` is an exception.
    """

    for i in collection:
        if predicate(i):
            return i

    if isinstance(default, Exception):
        raise default

    return default
