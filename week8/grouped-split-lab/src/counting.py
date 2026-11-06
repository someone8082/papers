"""Exact counting of whole-group allocations.

Contract
--------
``count_allocations(sizes, target)`` counts the subsets of groups whose sizes
sum to exactly ``target``. Each position in ``sizes`` is a group of distinct
identity, so two groups of the same size are counted separately: for
``[2, 2, 2]`` and target 2 the answer is 3, not 1.

* ``sizes`` holds positive integers. Non-positive sizes, non-integers, and
  booleans must be rejected explicitly.
* ``target`` is an integer. Negative targets, non-integers, booleans, and
  targets larger than ``sum(sizes)`` must be rejected explicitly.
* ``sizes == []`` with target 0 has exactly one allocation, the empty set.
* A non-empty valid input with target 0 also yields 1.
* A valid input with no subset reaching ``target`` yields 0: genuinely
  infeasible, not an error.
* The result is an arbitrary-precision non-negative integer; sizes of order
  93 must be exact, e.g. 93 groups of size 1 with target 32 equals C(93, 32).

The calibration side is the complement of the chosen group set and is never
split, so counting whole-group allocations is all this round needs.
"""

from .errors import InputError


def count_allocations(sizes, target):
    """Return the number of subsets of ``sizes`` summing to ``target``.

    Raises:
        InputError: invalid group size or invalid target.
    """
    sizes = list(sizes)
    for size in sizes:
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise InputError("group sizes must be positive integers, not booleans")
    if isinstance(target, bool) or not isinstance(target, int):
        raise InputError("target must be an integer, not a boolean")
    if not 0 <= target <= sum(sizes):
        raise InputError("target must lie between zero and the total size")

    ways = [0] * (target + 1)
    ways[0] = 1
    for size in sizes:
        # Descending updates use each distinct group at most once. Equal sizes
        # still get separate updates; Python integers retain exact counts.
        for subtotal in range(target, size - 1, -1):
            ways[subtotal] += ways[subtotal - size]
    return ways[target]
