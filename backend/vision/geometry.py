"""Planar polygon helpers in pixel coordinates (pure; no CV dependencies).

Image coordinates: x to the right, y downwards. Polygons are sequences of
``(x, y)`` vertices in drawing order (either orientation).
"""

from __future__ import annotations

from collections.abc import Sequence

Point = tuple[float, float]
Polygon = Sequence[Point]


def cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def polygon_area(poly: Polygon) -> float:
    """Unsigned shoelace area."""
    n = len(poly)
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2.0


def _on_segment(p: Point, a: Point, b: Point, eps: float = 1e-9) -> bool:
    if abs(cross(a, b, p)) > eps * max(1.0, abs(b[0] - a[0]) + abs(b[1] - a[1])):
        return False
    return min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps


def point_in_polygon(p: Point, poly: Polygon) -> bool:
    """Even-odd rule; points on the boundary count as inside."""
    n = len(poly)
    inside = False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if _on_segment(p, a, b):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                inside = not inside
    return inside


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """True when the closed segments share at least one point."""
    d1, d2 = cross(q1, q2, p1), cross(q1, q2, p2)
    d3, d4 = cross(p1, p2, q1), cross(p1, p2, q2)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return (
        (d1 == 0 and _on_segment(p1, q1, q2))
        or (d2 == 0 and _on_segment(p2, q1, q2))
        or (d3 == 0 and _on_segment(q1, p1, p2))
        or (d4 == 0 and _on_segment(q2, p1, p2))
    )


def is_simple(poly: Polygon) -> bool:
    """No two non-adjacent edges touch and no vertex repeats."""
    n = len(poly)
    if len(set(map(tuple, poly))) != n:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if segments_intersect(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return False
    return True


def is_convex(poly: Polygon) -> bool:
    signs = {cross(poly[i], poly[(i + 1) % len(poly)], poly[(i + 2) % len(poly)]) > 0
             for i in range(len(poly)) if cross(poly[i], poly[(i + 1) % len(poly)], poly[(i + 2) % len(poly)]) != 0}
    return len(signs) <= 1


def polygons_overlap(a: Polygon, b: Polygon) -> bool:
    """True when the polygons share any area or boundary point."""
    for i in range(len(a)):
        for j in range(len(b)):
            if segments_intersect(a[i], a[(i + 1) % len(a)], b[j], b[(j + 1) % len(b)]):
                return True
    return point_in_polygon(a[0], b) or point_in_polygon(b[0], a)


def convex_hull(points: Sequence[Point]) -> list[Point]:
    """Andrew's monotone chain; counter-clockwise in a y-up frame, without collinear points."""
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 2:
        return list(pts)
    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_width(poly: Polygon) -> float:
    """Minimum width of the convex hull (smallest distance between parallel supporting lines).

    For a gate drawn across lanes this is its depth along the direction of travel.
    """
    hull = convex_hull(poly)
    if len(hull) < 3:
        return 0.0
    best = float("inf")
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if length == 0:
            continue
        best = min(best, max(abs(cross(a, b, p)) / length for p in hull))
    return best


def centroid(poly: Polygon) -> Point:
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
