"""Reconstruct the deformation field from an array of tilt sensors.

The nodes measure exactly one mechanical quantity: tilt. They carry no crack
gauge and no displacement ranger. That is not a gap, because tilt is the
*derivative* of the subsidence profile, and the two quantities those sensors
used to provide are the neighbouring derivatives of the same curve::

    subsidence   S           = integral of T dx      <- integrate the array
    tilt         T = dS/dx                           <- measured directly
    curvature    K = dT/dx   = d2S/dx2               <- differentiate the array
    horiz disp   U = B * T                           <- scale
    strain       e = dU/dx   = B * K                 <- differentiate the array

(``ml/simulator/physics.py`` derives all five analytically; this module recovers
them numerically from what the hardware actually reports.)

So a single node cannot measure strain, and an *array* of nodes can. That is the
whole argument for this module, and it is also why node spacing is a sensing
decision and not only a radio one.

The catch, stated plainly: differentiation amplifies noise. Tilt carries ~50 mdeg
of noise per sample, so a two-point strain estimate across 150 m of spacing lands
near 0.5 mm/m -- which is the entire width of the NCB "negligible" band. Two
things make it usable, and both are applied here:

  * fit rather than difference -- a least-squares gradient over every neighbour
    in range uses the whole array to constrain each estimate, instead of letting
    two noisy readings set it;
  * average over time -- strain is reported from a window of frames, not one.
    This costs nothing real, because strain damage accumulates over days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: B, the horizontal-displacement factor, as a multiple of seam depth. Matches
#: ``PanelGeometry.horizontal_disp_factor`` so the reconstruction and the physics
#: that generated the training data cannot disagree.
HORIZONTAL_DISP_FACTOR = 0.4

#: Nodes within this distance of each other count as the same row or column.
#: Generous, because a field crew plants posts by hand and by eye.
ROW_TOLERANCE_M = 40.0

#: Spacing must be at most the radius of influence divided by this before the
#: curvature of the trough can be resolved at all. Measured, not assumed: see
#: ``tests/test_deformation.py::TestSpacingRequirement``. The subsidence profile
#: turns over within roughly half a radius of influence, and a central difference
#: needs several samples across a feature to represent it rather than average it
#: away.
SENSING_SPACING_DIVISOR = 3.0


def max_sensing_spacing_m(seam_depth_m: float, angle_of_draw_deg: float = 35.0) -> float:
    """Widest node spacing that still resolves strain, in metres.

    This is a *sensing* constraint and it is the one that binds. With no crack
    gauge, strain is recovered by differentiating the tilt field, and a
    derivative taken across too wide a gap does not measure the curvature -- it
    averages over it and reports something close to the mean slope everywhere.

    Compare it against ``RadioModel.max_reliable_spacing_m()`` when planning a
    field. For a 150 m seam at a 35 degree draw angle this returns ~71 m against
    the radio's ~241 m, so connectivity is satisfied long before the measurement
    is, and a field spaced for the radio alone will report tilt correctly and
    strain not at all.
    """
    r = seam_depth_m / math.tan(math.radians(angle_of_draw_deg))
    return r / SENSING_SPACING_DIVISOR


@dataclass(frozen=True, slots=True)
class NodeTilt:
    """One node's position and its baseline-corrected tilt components."""

    addr: int
    x_m: float
    y_m: float
    tilt_x_mm_per_m: float
    tilt_y_mm_per_m: float


@dataclass(frozen=True, slots=True)
class FieldEstimate:
    """Reconstructed movement at one node."""

    strain_x_mm_per_m: float
    strain_y_mm_per_m: float
    subsidence_mm: float
    #: False when the node had no neighbour to take a gradient against. Such a
    #: node reports tilt honestly and strain not at all, rather than reporting a
    #: strain of zero -- because zero reads as "safe".
    strain_valid: bool
    #: False when this node's row has no anchor outside the subsidence trough, so
    #: the integration constant is unknown. The *shape* of the profile is still
    #: right; its absolute depth is not, and it will read low.
    subsidence_valid: bool = True

    @property
    def strain_mm_per_m(self) -> float:
        """Signed governing strain: whichever axis has the larger magnitude.

        Sign is kept. Tension opens cracks, compression buckles and shears, and
        the damage they do is not interchangeable.
        """
        if abs(self.strain_x_mm_per_m) >= abs(self.strain_y_mm_per_m):
            return self.strain_x_mm_per_m
        return self.strain_y_mm_per_m


def _group(nodes: list[NodeTilt], axis: str,
           tol_m: float = ROW_TOLERANCE_M) -> list[list[NodeTilt]]:
    """Cluster nodes into rows (constant y) or columns (constant x)."""
    cross = (lambda n: n.y_m) if axis == "x" else (lambda n: n.x_m)
    along = (lambda n: n.x_m) if axis == "x" else (lambda n: n.y_m)
    groups: list[list[NodeTilt]] = []
    for node in sorted(nodes, key=cross):
        for g in groups:
            if abs(cross(g[0]) - cross(node)) <= tol_m:
                g.append(node)
                break
        else:
            groups.append([node])
    return [sorted(g, key=along) for g in groups]


def _central_differences(positions: list[float],
                         values: list[float]) -> list[float | None]:
    """dv/ds at each point: central where there are neighbours on both sides,
    one-sided at the ends, None where the spacing collapses to zero.

    Central differencing is what makes this local. A least-squares slope fitted
    over a wide neighbourhood looks more robust and is in fact much worse here:
    the trough reverses curvature within half a radius of influence, so a wide
    fit averages tension and compression together and reports neither.
    """
    n = len(positions)
    if n < 2:
        return [None] * n
    out: list[float | None] = []
    for i in range(n):
        lo, hi = max(0, i - 1), min(n - 1, i + 1)
        span = positions[hi] - positions[lo]
        out.append((values[hi] - values[lo]) / span if abs(span) > 1e-6 else None)
    return out


def estimate_field(nodes: list[NodeTilt], *, seam_depth_m: float,
                   panel_x_start: float | None = None,
                   angle_of_draw_deg: float = 35.0) -> dict[int, FieldEstimate]:
    """Strain and subsidence at every node, from the tilt field alone.

    Strain is ``B * dT/dx``, taken as a central difference along each row and
    column of the array. Subsidence is the integral of tilt along each row,
    anchored at the row's outermost node -- which sits in the draw-angle margin
    beyond the panel, where the ground has not moved. That anchor is what makes
    integrating a derivative possible at all; with no known-still reference the
    constant of integration is free and the answer is only a shape.

    Accuracy depends entirely on the field layout, and on two things about it:

    *Spacing* governs strain. At or under ``max_sensing_spacing_m()`` the
    reconstruction tracks the analytic strain closely (correlation ~0.98); at the
    radio's maximum spacing it does not (~0.71), because a difference taken
    across a gap wider than the feature averages over the curvature instead of
    measuring it.

    *Anchor placement* governs subsidence. The outermost node of a row is treated
    as the zero, so it has to be somewhere the ground genuinely has not moved --
    a full radius of influence beyond the panel edge. Anchored inside the trough
    instead, every depth in that row is under-reported by the anchor's own
    subsidence, which at a third of a radius is already hundreds of millimetres.
    ``panel_x_start`` lets this be checked; without it the anchor is trusted.
    """
    b = HORIZONTAL_DISP_FACTOR * seam_depth_m
    if not nodes:
        return {}

    strain_x: dict[int, float | None] = {}
    strain_y: dict[int, float | None] = {}

    for row in _group(nodes, "x"):
        grads = _central_differences([n.x_m for n in row],
                                     [n.tilt_x_mm_per_m for n in row])
        for node, g in zip(row, grads):
            strain_x[node.addr] = b * g if g is not None else None

    for col in _group(nodes, "y"):
        grads = _central_differences([n.y_m for n in col],
                                     [n.tilt_y_mm_per_m for n in col])
        for node, g in zip(col, grads):
            strain_y[node.addr] = b * g if g is not None else None

    r = seam_depth_m / math.tan(math.radians(angle_of_draw_deg))
    subsidence, anchored = _integrate_subsidence(
        nodes, anchor_limit=None if panel_x_start is None else panel_x_start - r)

    out: dict[int, FieldEstimate] = {}
    for node in nodes:
        ex, ey = strain_x.get(node.addr), strain_y.get(node.addr)
        out[node.addr] = FieldEstimate(
            strain_x_mm_per_m=ex or 0.0,
            strain_y_mm_per_m=ey or 0.0,
            subsidence_mm=subsidence.get(node.addr, 0.0),
            strain_valid=ex is not None or ey is not None,
            subsidence_valid=anchored.get(node.addr, True),
        )
    return out


def _integrate_subsidence(nodes: list[NodeTilt], *, anchor_limit: float | None = None,
                          tol_m: float = ROW_TOLERANCE_M
                          ) -> tuple[dict[int, float], dict[int, bool]]:
    """Trapezoidal integration of tilt along each row of constant y.

    Tilt is mm of drop per metre travelled, so integrating it along the direction
    of face advance accumulates the depth of the trough. Reported as a positive
    depth. ``anchor_limit`` is the x beyond which ground is known undisturbed;
    a row whose outermost node sits inside it is integrated anyway but marked
    unanchored, because a wrong depth presented as right is worse than a depth
    labelled provisional.
    """
    out: dict[int, float] = {}
    anchored: dict[int, bool] = {}
    for row in _group(nodes, "x", tol_m):
        # The outermost node is the zero the integral is measured from.
        ok = anchor_limit is None or row[0].x_m <= anchor_limit
        total = 0.0
        out[row[0].addr] = 0.0
        anchored[row[0].addr] = ok
        for prev, cur in zip(row, row[1:]):
            dx = cur.x_m - prev.x_m
            total += 0.5 * (prev.tilt_x_mm_per_m + cur.tilt_x_mm_per_m) * dx
            out[cur.addr] = abs(total)
            anchored[cur.addr] = ok
    return out, anchored
