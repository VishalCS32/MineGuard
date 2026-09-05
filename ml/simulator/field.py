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

__all__ = ["NodeSpec", "SitePreset", "SITE_PRESETS", "build_grid_field", "local_to_wgs84"]

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
    ref_post_distance_mm: int = 2500   # ToF baseline to its reference post
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


def build_grid_field(preset: SitePreset, cols: int = 5, rows: int = 3,
                     margin_fraction: float = 0.35, first_addr: int = 0x0010,
                     ref_post_distance_mm: int = 2500) -> list[NodeSpec]:
    """Lay out ``cols x rows`` nodes over the panel, anchored on the panel edges.

    Deliberately *not* a uniform grid. Tilt and strain both peak directly above the
    panel boundary, so a uniform grid can straddle the edge and leave the highest-
    signal ground unmonitored -- it would watch the quiet trough centre and detect
    movement late. Instead the outermost rows/columns sit in the draw-angle margin,
    the next ones sit exactly on the panel edges, and any remaining nodes spread
    across the interior. Given a fixed node budget this buys earlier warning for
    free, which matters when nodes cost money and a panel is large.
    """
    if cols < 2 or rows < 2:
        raise ValueError("a deformation field needs at least a 2x2 grid")

    p = preset.panel
    margin = margin_fraction * p.radius_of_influence_m
    xs = _edge_anchored_positions(p.x_start, p.x_end, margin, cols)
    ys = _edge_anchored_positions(p.y_min, p.y_max, margin, rows)

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
                ref_post_distance_mm=ref_post_distance_mm,
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


def _linspace(a: float, b: float, n: int) -> list[float]:
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]
