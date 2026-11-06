"""Connected components over image keys.

Contract
--------
``group_components(keys, edges)`` returns *all* connected components of the
undirected graph induced by ``keys`` and ``edges``.

* ``keys`` is a sequence of distinct, non-empty strings; each key is one image.
* ``edges`` is a sequence of ``(a, b)`` key pairs. Edges are undirected. A
  duplicated edge, or the same edge with endpoints swapped, must not change the
  result. A self-loop ``(a, a)`` must not change the result either.
* A duplicated node key must be rejected explicitly.
* An edge endpoint that is not in ``keys`` must be rejected explicitly.
* Every key appears in exactly one group, including keys with no edge.
* Members of a group are sorted ascending; groups are sorted by their smallest
  member. Output therefore depends only on the graph, never on input order.

The first round needs nothing else: no similarity threshold, no edge rule over
real images, no scoring.
"""

from .errors import InputError


def group_components(keys, edges):
    """Return the connected components of the undirected graph.

    Raises:
        InputError: invalid or duplicated key, malformed edge, or unknown endpoint.
    """
    adjacency = {}
    for key in keys:
        if not isinstance(key, str) or not key:
            raise InputError("keys must be non-empty strings")
        if key in adjacency:
            raise InputError(f"duplicate key: {key!r}")
        adjacency[key] = set()

    for edge in edges:
        if not isinstance(edge, (tuple, list)) or len(edge) != 2:
            raise InputError("each edge must be a pair of keys")
        a, b = edge
        if (not isinstance(a, str) or not isinstance(b, str)
                or a not in adjacency or b not in adjacency):
            raise InputError(f"unknown edge endpoint: {edge!r}")
        adjacency[a].add(b)
        adjacency[b].add(a)

    seen = set()
    groups = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        seen.add(start)
        pending = [start]
        members = []
        while pending:
            key = pending.pop()
            members.append(key)
            for neighbor in adjacency[key]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        groups.append(sorted(members))
    # Sorted starts ensure components are already ordered by their minimum key.
    return groups
