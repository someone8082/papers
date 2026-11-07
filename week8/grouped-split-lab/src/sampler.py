"""Whole-group allocation sampler: exact count, integer-rank decoding, sampling.

Contract: ``SAMPLER-CONTRACT.md``. Nothing here reads images, scores or files;
the unit is a subset of group indices whose sizes sum to the target.

Ranks enumerate legal indicator vectors lexicographically, with exclusion
before inclusion at each group. All counts and probabilities remain exact.
"""

from fractions import Fraction

from .errors import InputError


def _validate(sizes, target, excluded):
    """Materialize inputs once, including one-shot excluded iterators."""
    try:
        sizes = tuple(sizes)
        excluded = tuple(excluded)
    except TypeError as exc:
        raise InputError("sizes and excluded must be iterable") from exc
    if any(isinstance(s, bool) or not isinstance(s, int) or s <= 0
           for s in sizes):
        raise InputError("sizes must be positive integers, not booleans")
    if (isinstance(target, bool) or not isinstance(target, int)
            or not 0 <= target <= sum(sizes)):
        raise InputError("target must be an integer between zero and total size")
    blocked = set()
    for i in excluded:
        if (isinstance(i, bool) or not isinstance(i, int)
                or not 0 <= i < len(sizes) or i in blocked):
            raise InputError("excluded indices must be distinct in-range integers")
        blocked.add(i)
    return sizes, blocked


def _suffix(sizes, target, blocked):
    """D[i][t] counts completions using groups i onward to reach t."""
    table = [[0] * (target + 1) for _ in range(len(sizes) + 1)]
    table[-1][0] = 1
    for i in range(len(sizes) - 1, -1, -1):
        row, following = table[i], table[i + 1]
        size = sizes[i]
        for t in range(target + 1):
            row[t] = following[t]
            if i not in blocked and t >= size:
                row[t] += following[t - size]
    return table


def _decode(sizes, target, rank, blocked, table):
    """Unrank against an already validated completion table."""
    if (isinstance(rank, bool) or not isinstance(rank, int)
            or not 0 <= rank < table[0][target]):
        raise InputError("rank must be an integer in [0, count)")
    selected = []
    remaining = target
    for i, size in enumerate(sizes):
        without = table[i + 1][remaining]
        if rank < without:
            continue
        # For a valid rank, this branch necessarily has a legal completion.
        # Excluded groups have no inclusion branch in the table.
        rank -= without
        remaining -= size
        selected.append(i)
    return tuple(selected)


def count(sizes, target, excluded=()):
    """Number of legal group subsets summing to ``target``.

    ``sizes`` holds positive integers, one per group identity; equal sizes are
    counted separately. ``excluded`` lists group indices that may never be
    selected. Invalid input raises ``InputError``.
    """
    sizes, blocked = _validate(sizes, target, excluded)
    return _suffix(sizes, target, blocked)[0][target]


def decode(sizes, target, rank, excluded=()):
    """The ``rank``-th legal subset, as an ascending tuple of group indices.

    Ranks are ordered by the lexicographic order of the indicator vector
    ``(b_0, .., b_{n-1})`` with ``0 < 1`` and ``b_0`` most significant.
    ``rank`` must satisfy ``0 <= rank < count(...)``.
    """
    sizes, blocked = _validate(sizes, target, excluded)
    return _decode(sizes, target, rank, blocked, _suffix(sizes, target, blocked))


def sample(sizes, target, rng, excluded=()):
    """Draw one legal subset uniformly, using a single ``rng.randrange(count)``.

    ``rng`` is anything with ``randrange(n)``; ``random.Random`` qualifies.
    Coin flips per group, a fixed group count, greedy prefixes and float
    conversions of the total are all forbidden by the contract.
    """
    sizes, blocked = _validate(sizes, target, excluded)
    table = _suffix(sizes, target, blocked)
    total = table[0][target]
    if total == 0:
        raise InputError("no legal allocation to sample")
    rank = rng.randrange(total)
    return _decode(sizes, target, rank, blocked, table)


def inclusion_probabilities(sizes, target, excluded=()):
    """Per-group inclusion probability under the uniform legal distribution.

    Returns a tuple of ``fractions.Fraction`` of length ``len(sizes)``; excluded
    groups have probability exactly 0.
    """
    sizes, blocked = _validate(sizes, target, excluded)
    table = _suffix(sizes, target, blocked)
    total = table[0][target]
    if total == 0:
        return (Fraction(0),) * len(sizes)

    # prefix[u] counts choices before i with sum u. Combining it with the
    # suffix after i counts allocations containing i, without enumerating them.
    prefix = [0] * (target + 1)
    prefix[0] = 1
    probabilities = []
    for i, size in enumerate(sizes):
        if i in blocked:
            probabilities.append(Fraction(0))
            continue
        numerator = sum(prefix[u] * table[i + 1][target - size - u]
                        for u in range(target - size + 1))
        probabilities.append(Fraction(numerator, total))
        for t in range(target, size - 1, -1):
            prefix[t] += prefix[t - size]
    return tuple(probabilities)
