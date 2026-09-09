"""Sensor-field layout: where the nodes physically sit above the panel.

Node placement is not arbitrary. Tilt and strain both peak *over the panel edge*
(see physics.TestTilt), so a field that only covers the panel centre would watch
the quietest ground and see movement last. The layouts here deliberately extend
past the panel edge into the draw-angle margin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .physics import PanelGeometry

__all__ = ["NodeSpec", "SitePreset", "SITE_PRESETS", "build_grid_field",
           "build_transect_field", "local_to_wgs84", "max_sensing_spacing_m"]

#: Node spacing must be at most the radius of influence over this before the
#: curvature of the subsidence trough can be resolved. Mirrored by
#: ``backend/app/deformation.py``, which does the reconstruction that depends on
#: it; ``backend/tests/test_deformation.py`` asserts the two agree.
SENSING_SPACING_DIVISOR = 3.0

EARTH_RADIUS_M = 6_378_137.0


def local_to_wgs84(origin_lat: float, origin_lon: float,
                   x_m: float, y_m: float) -> tuple[float, float]:
    """Local ENU metres -> (lat, lon). Equirectangular is exact enough here:
    a monitored panel spans a couple of kilometres, where the error is millimetres.
    """
    lat = origin_lat + math.degrees(y_m / EARTH_RADIUS_M)
    lon = origin_lon + math.degrees(x_m / (EARTH_RADIUS_M * math.cos(math.radians(origin_lat))))
    return lat, lon


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """One deployed sensor node."""

    addr: int              # 16-bit mesh address; 0x0001 is reserved for the gateway
    label: str
    x_m: float             # local metric position over the panel
    y_m: float
    lat: float
    lon: float
    is_edge: bool = False              # sits over the panel rim -> earliest warning


@dataclass(frozen=True, slots=True)
class SitePreset:
    """A real Indian coalfield to anchor the demo geography."""

    slug: str
    name: str
    coalfield: str
    origin_lat: float
    origin_lon: float
    panel: PanelGeometry


SITE_PRESETS: dict[str, SitePreset] = {
    "jharia": SitePreset(
        slug="jharia",
        name="Jharia Panel L-7",
        coalfield="Jharia Coalfield, Jharkhand",
        origin_lat=23.7500, origin_lon=86.4200,
        panel=PanelGeometry(x_start=0, x_end=600, y_min=-150, y_max=150,
                            seam_depth_m=150, extraction_thickness_m=3.0,
                            subsidence_factor=0.65, angle_of_draw_deg=35)),
    "raniganj": SitePreset(
        slug="raniganj",
        name="Raniganj Panel B-3",
        coalfield="Raniganj Coalfield, West Bengal",
        origin_lat=23.6200, origin_lon=87.1300,
        panel=PanelGeometry(x_start=0, x_end=800, y_min=-200, y_max=200,
                            seam_depth_m=220, extraction_thickness_m=2.4,
                            subsidence_factor=0.60, angle_of_draw_deg=32)),
}


def max_sensing_spacing_m(seam_depth_m: float, angle_of_draw_deg: float = 35.0) -> float:
    """Widest node spacing that still resolves strain, in metres.

    With no crack gauge on the node, strain is recovered by differentiating the
    tilt field across the array, and a difference taken across too wide a gap
    averages over the curvature instead of measuring it. That makes spacing a
    *sensing* constraint -- and it is the one that binds: for a 150 m seam it
    demands ~71 m against the radio's ~241 m, so a field planned for
    connectivity alone reports tilt correctly and strain not at all.
    """
    r = seam_depth_m / math.tan(math.radians(angle_of_draw_deg))
    return r / SENSING_SPACING_DIVISOR


def build_transect_field(preset: SitePreset, n_nodes: int = 21,
                         first_addr: int = 0x0010, y_m: float = 0.0,
                         spacing_m: float | None = None) -> list[NodeSpec]:
    """A single dense line of nodes along the direction of face advance.

    This is what a subsidence survey actually looks like. Monitoring practice
    has used survey *lines* over longwall panels for a century, and the reason
    applies exactly to a tilt array: the quantities of interest -- subsidence,
    tilt, curvature, strain -- are derivatives and integrals taken *along* the
    line of advance, so resolution along that line is what buys accuracy, and
    breadth across it mostly buys duplicates.

    It matters here because of arithmetic. Covering the whole panel as a grid at
    the spacing strain reconstruction demands needs several times more nodes
    than a real budget stretches to. The same nodes arranged as one transect
    resolve the full profile properly instead of sampling all of it too coarsely
    to differentiate -- a complete answer along one line, rather than an
    unusable answer everywhere.

    The line deliberately runs from a full radius of influence before the panel
    to a full radius past it: the ends are the undisturbed anchors that make the
    subsidence integral recoverable, and the rim crossings in between are where
    tilt and strain peak.
    """
    if n_nodes < 3:
        raise ValueError("a transect needs at least three nodes")
    p = preset.panel
    r = p.radius_of_influence_m
    lo, hi = p.x_start - r, p.x_end + r
    if spacing_m is None:
        spacing_m = (hi - lo) / (n_nodes - 1)

    required = max_sensing_spacing_m(p.seam_depth_m, p.angle_of_draw_deg)
    if spacing_m > required:
        # Not an error: a coarser line still measures tilt honestly. But strain
        # will not reconstruct, and that should be visible at planning time
        # rather than discovered as a flat line on a dashboard.
        import warnings
        warnings.warn(
            f"transect spacing {spacing_m:.0f} m exceeds the {required:.0f} m "
            f"needed to resolve strain; tilt will be sound, strain will not",
            stacklevel=2)

    edge_band = 0.2 * r
    nodes: list[NodeSpec] = []
    for i in range(n_nodes):
        x = lo + i * spacing_m
        lat, lon = local_to_wgs84(preset.origin_lat, preset.origin_lon, x, y_m)
        nodes.append(NodeSpec(
            addr=first_addr + i, label=f"T-{i + 1:02d}",
            x_m=x, y_m=y_m, lat=lat, lon=lon,
            is_edge=min(abs(x - p.x_start), abs(x - p.x_end)) <= edge_band))
    return nodes


def build_grid_field(preset: SitePreset, cols: int = 5, rows: int = 3,
                     margin_fraction: float = 0.35, first_addr: int = 0x0010,
                     max_spacing_m: float | None = None) -> list[NodeSpec]:
    """Lay out ``cols x rows`` nodes over the panel, anchored on the panel edges.

    Deliberately *not* a uniform grid. Tilt and strain both peak directly above the
    panel boundary, so a uniform grid can straddle the edge and leave the highest-
    signal ground unmonitored -- it would watch the quiet trough centre and detect
    movement late. Instead the outermost rows/columns sit in the draw-angle margin,
    the next ones sit exactly on the panel edges, and any remaining nodes spread
    across the interior. Given a fixed node budget this buys earlier warning for
    free, which matters when nodes cost money and a panel is large.

    ``max_spacing_m`` closes the loop with the two independent constraints on
    spacing, and the node count falls out of them instead of being guessed:

    * *connectivity* -- ``RadioModel().max_reliable_spacing_m()``. Space wider
      than this and frames do not get home.
    * *measurement* -- ``max_sensing_spacing_m()``. Space wider than this and
      strain cannot be reconstructed from the tilt field, because the difference
      between neighbours stops representing the local curvature.

    Pass the smaller of the two. It is the sensing one, by roughly a factor of
    three, which is easy to miss when planning a field around radio range alone.
    Any gap wider than the limit is subdivided until it complies.
    """
    if cols < 2 or rows < 2:
        raise ValueError("a deformation field needs at least a 2x2 grid")

    p = preset.panel
    margin = margin_fraction * p.radius_of_influence_m
    xs = _edge_anchored_positions(p.x_start, p.x_end, margin, cols)
    ys = _edge_anchored_positions(p.y_min, p.y_max, margin, rows)
    if max_spacing_m is not None:
        if max_spacing_m <= 0:
            raise ValueError("max_spacing_m must be positive")
        xs = _enforce_max_spacing(xs, max_spacing_m)
        ys = _enforce_max_spacing(ys, max_spacing_m)

    # A node counts as an edge node when it sits within a fifth of the influence
    # radius of a panel boundary -- that is where tilt and strain peak.
    edge_band = 0.2 * p.radius_of_influence_m

    nodes: list[NodeSpec] = []
    addr = first_addr
    for row, y in enumerate(ys):
        for col, x in enumerate(xs):
            lat, lon = local_to_wgs84(preset.origin_lat, preset.origin_lon, x, y)
            near_x = min(abs(x - p.x_start), abs(x - p.x_end)) <= edge_band
            near_y = min(abs(y - p.y_min), abs(y - p.y_max)) <= edge_band
            nodes.append(NodeSpec(
                addr=addr,
                label=f"N{row + 1}-{col + 1}",
                x_m=x, y_m=y, lat=lat, lon=lon,
                is_edge=near_x or near_y))
            addr += 1
    return nodes


def _edge_anchored_positions(lo: float, hi: float, margin: float, n: int) -> list[float]:
    """``n`` positions across [lo, hi], guaranteeing coverage of both boundaries.

    n == 2 -> the two edges; n == 3 -> edges plus centre; n >= 4 -> a margin point
    outside each edge, the two edges, and the remainder spread across the interior.
    """
    if n == 2:
        return [lo, hi]
    if n == 3:
        return [lo, 0.5 * (lo + hi), hi]
    interior = n - 4
    positions = [lo - margin, lo]
    if interior > 0:
        step = (hi - lo) / (interior + 1)
        positions += [lo + step * (i + 1) for i in range(interior)]
    positions += [hi, hi + margin]
    return positions


def _enforce_max_spacing(positions: list[float], max_spacing: float) -> list[float]:
    """Subdivide any gap wider than ``max_spacing``, keeping the original anchors.

    The edge anchors survive untouched -- they are where the signal is -- and infill
    nodes appear only where the radio actually needs them.
    """
    out = [positions[0]]
    for a, b in zip(positions, positions[1:]):
        gap = b - a
        extra = max(0, math.ceil(gap / max_spacing) - 1)
        out.extend(a + gap * (i + 1) / (extra + 1) for i in range(extra))
        out.append(b)
    return out


def _linspace(a: float, b: float, n: int) -> list[float]:
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]
