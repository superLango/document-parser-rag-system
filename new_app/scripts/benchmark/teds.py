"""Ordered-tree edit distance (Zhang-Shasha) and TEDS for table grids.

Tables are compared as ``table -> tr -> td`` trees.  TEDS is
``1 - tree_edit_distance / max(nodes_a, nodes_b)``, matching the standard
TEDS definition at the cell/structure level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def normalize(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


@dataclass
class Node:
    label: str
    children: list["Node"] = field(default_factory=list)


def grid_tree(rows: list[list[str]]) -> Node:
    root = Node("table")
    for row in rows:
        tr = Node("tr")
        for cell in row:
            tr.children.append(Node(normalize(cell)))
        root.children.append(tr)
    return root


def _postorder(root: Node) -> tuple[list[Node], list[int]]:
    """Return nodes in 1-based postorder plus leftmost-descendant indices."""
    nodes: list[Node] = []
    leftmost: list[int] = []

    def visit(node: Node) -> int:
        first = len(nodes) + 1
        for child in node.children:
            first = min(first, visit(child))
        nodes.append(node)
        leftmost.append(first)
        return first

    visit(root)
    return nodes, leftmost


def _key_roots(leftmost: list[int], n: int) -> list[int]:
    roots: dict[int, int] = {}
    for index in range(1, n + 1):
        roots[leftmost[index - 1]] = index
    return sorted(roots.values())


def tree_edit_distance(a: Node, b: Node) -> int:
    nodes_a, lmd_a = _postorder(a)
    nodes_b, lmd_b = _postorder(b)
    n, m = len(nodes_a), len(nodes_b)
    treedist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        treedist[i][0] = i
    for j in range(1, m + 1):
        treedist[0][j] = j

    for i in _key_roots(lmd_a, n):
        for j in _key_roots(lmd_b, m):
            li, lj = lmd_a[i - 1], lmd_b[j - 1]
            fd = [[0] * (m + 1) for _ in range(n + 1)]
            for x in range(li, i + 1):
                fd[x][lj - 1] = fd[x - 1][lj - 1] + 1
            for y in range(lj, j + 1):
                fd[li - 1][y] = fd[li - 1][y - 1] + 1
            for x in range(li, i + 1):
                for y in range(lj, j + 1):
                    if lmd_a[x - 1] == li and lmd_b[y - 1] == lj:
                        cost = 0 if nodes_a[x - 1].label == nodes_b[y - 1].label else 1
                        fd[x][y] = min(
                            fd[x - 1][y] + 1,
                            fd[x][y - 1] + 1,
                            fd[x - 1][y - 1] + cost,
                        )
                        treedist[x][y] = fd[x][y]
                    else:
                        fd[x][y] = min(
                            fd[x - 1][y] + 1,
                            fd[x][y - 1] + 1,
                            fd[lmd_a[x - 1] - 1][lmd_b[y - 1] - 1]
                            + treedist[x][y],
                        )
    return treedist[n][m]


def teds_score(expected: list[list[str]], actual: list[list[str]]) -> float:
    if not expected and not actual:
        return 1.0
    tree_a = grid_tree(expected)
    tree_b = grid_tree(actual)
    size_a = _node_count(tree_a)
    size_b = _node_count(tree_b)
    if size_a == 0 and size_b == 0:
        return 1.0
    distance = tree_edit_distance(tree_a, tree_b)
    return max(0.0, 1.0 - distance / max(size_a, size_b))


def _node_count(node: Node) -> int:
    return 1 + sum(_node_count(child) for child in node.children)
