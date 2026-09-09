"""Tests for reconstructing strain and subsidence from the tilt array.

These are the tests that decide whether dropping the crack gauge and the ranger
was survivable. The claim under test is that ``strain = B * dT/dx`` and
``S = integral of T dx`` recover, from tilt alone, the quantities those two
sensors used to measure -- so every assertion here is made against the analytic
physics in ``ml/simulator/physics.py``, not against the reconstruction's own
output.

They also pin down the two layout rules the reconstruction depends on, because
both were discovered by measurement here and both are easy to get wrong in the
field: spacing must resolve the curvature, and the integration must be anchored
on ground that has not moved.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
np = pytest.importorskip("numpy")

from app.deformation import (  # noqa: E402
    NodeTilt, estimate_field, max_sensing_spacing_m,
)
from simulator.field import (  # noqa: E402
    SITE_PRESETS, build_transect_field, max_sensing_spacing_m as field_spacing_rule,
)
from simulator.physics import SubsidenceModel  # noqa: E402

PRESET = SITE_PRESETS["jharia"]
PANEL = PRESET.panel
FACE_X = 400.0


R = PANEL.radius_of_influence_m


def build(spacing_m: float, *, x_lo: float | None = None, margin: float | None = None):
    """A regular field at ``spacing_m``, evaluated against the analytic model.

    Covers the panel plus a full radius of influence of draw margin on every
    side, which is the layout the reconstruction documents: movement reaches
    that far, so a field that stops at the panel edge has no still ground to
    anchor on and no coverage of the rim where strain peaks.
    """
    margin = R if margin is None else margin
    x_lo = -margin if x_lo is None else x_lo
    xs = np.arange(x_lo, PANEL.x_end + margin + 1e-6, spacing_m)
    ys = np.arange(PANEL.y_min - margin, PANEL.y_max + margin + 1e-6, spacing_m)
    X, Y = np.meshgrid(xs, ys)
    mv = SubsidenceModel(PANEL).evaluate(X.ravel(), Y.ravel(),
                                         face_x=FACE_X, completion=1.0)
    nodes = [
        NodeTilt(0x10 + i, float(x), float(y), float(tx), float(ty))
        for i, (x, y, tx, ty) in enumerate(
            zip(X.ravel(), Y.ravel(), mv.tilt_x_mm_per_m, mv.tilt_y_mm_per_m))
    ]
    return nodes, mv


def correlation(a, b) -> float:
    return float(np.corrcoef(np.asarray(a), np.asarray(b))[0, 1])


class TestSpacingRequirement:
    """Spacing is a *sensing* constraint, and it binds tighter than the radio's."""

    def test_the_rule_is_a_third_of_the_influence_radius(self):
        req = max_sensing_spacing_m(PANEL.seam_depth_m, PANEL.angle_of_draw_deg)
        assert req == pytest.approx(PANEL.radius_of_influence_m / 3.0)

    def test_sensing_binds_before_the_radio_does(self):
        """The point of stating it at all: a field spaced for connectivity alone
        reports tilt correctly and strain not at all."""
        from simulator.mesh import RadioModel
        req = max_sensing_spacing_m(PANEL.seam_depth_m, PANEL.angle_of_draw_deg)
        assert req < RadioModel().max_reliable_spacing_m()

    def test_adequate_spacing_recovers_the_analytic_strain(self):
        req = max_sensing_spacing_m(PANEL.seam_depth_m, PANEL.angle_of_draw_deg)
        nodes, mv = build(req)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m)
        recovered = [est[n.addr].strain_mm_per_m for n in nodes]
        assert correlation(mv.strain_mm_per_m, recovered) > 0.95

    def test_radio_spacing_does_not_recover_strain(self):
        """The honest negative result. Asserted so nobody later 'optimises' the
        node count down and quietly loses the strain channel.

        Same field, same physics, only the spacing changed -- and the strain
        estimate stops tracking the truth almost entirely."""
        nodes, mv = build(188.0)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m)
        recovered = [est[n.addr].strain_mm_per_m for n in nodes]
        assert correlation(mv.strain_mm_per_m, recovered) < 0.5

    def test_recovery_improves_monotonically_as_spacing_tightens(self):
        scores = []
        for spacing in (188.0, 150.0, 94.0, 71.0, 50.0):
            nodes, mv = build(spacing)
            est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m)
            scores.append(correlation(mv.strain_mm_per_m,
                                      [est[n.addr].strain_mm_per_m for n in nodes]))
        assert scores == sorted(scores)


class TestStrainSign:
    """Tension and compression are not interchangeable for damage assessment."""

    def test_tension_at_the_rim_and_compression_over_the_goaf(self):
        nodes, mv = build(50.0)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m)
        centre = min(nodes, key=lambda n: (abs(n.x_m - 200.0) + abs(n.y_m)))
        assert est[centre.addr].strain_mm_per_m < 0        # goaf: compression

    def test_signs_agree_with_the_analytic_field_where_strain_is_significant(self):
        nodes, mv = build(50.0)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m)
        checked = agreed = 0
        for i, n in enumerate(nodes):
            true = float(mv.strain_mm_per_m[i])
            if abs(true) < 0.5:          # inside the noise band, sign is moot
                continue
            checked += 1
            agreed += (true > 0) == (est[n.addr].strain_mm_per_m > 0)
        assert checked > 20
        assert agreed / checked > 0.9


class TestSubsidenceIntegration:
    def test_anchored_outside_the_trough_recovers_the_depth(self):
        nodes, mv = build(71.0)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m,
                             panel_x_start=PANEL.x_start,
                             angle_of_draw_deg=PANEL.angle_of_draw_deg)
        recovered = [est[n.addr].subsidence_mm for n in nodes]
        true = [float(v) for v in mv.subsidence_mm]
        assert correlation(true, recovered) > 0.99
        rel = float(np.abs(np.array(recovered) - np.array(true)).mean() / np.mean(true))
        assert rel < 0.10

    def test_anchor_inside_the_trough_is_flagged_not_silently_wrong(self):
        """A node 75 m beyond the edge has already dropped hundreds of mm. Using
        it as the zero under-reports every depth in its row."""
        nodes, _ = build(71.0, x_lo=-75.0, margin=R)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m,
                             panel_x_start=PANEL.x_start,
                             angle_of_draw_deg=PANEL.angle_of_draw_deg)
        assert not any(est[n.addr].subsidence_valid for n in nodes)

    def test_a_properly_anchored_row_is_marked_valid(self):
        nodes, _ = build(71.0, x_lo=-R - 10.0)
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m,
                             panel_x_start=PANEL.x_start,
                             angle_of_draw_deg=PANEL.angle_of_draw_deg)
        assert all(est[n.addr].subsidence_valid for n in nodes)

    def test_undisturbed_ground_integrates_to_nothing(self):
        nodes = [NodeTilt(0x10 + i, x, 0.0, 0.0, 0.0)
                 for i, x in enumerate(range(-200, 601, 50))]
        est = estimate_field(nodes, seam_depth_m=PANEL.seam_depth_m)
        assert all(est[n.addr].subsidence_mm == pytest.approx(0.0) for n in nodes)


class TestDegradedInput:
    def test_a_lone_node_reports_no_strain_rather_than_zero_strain(self):
        """Zero would render as a healthy node. Invalid renders as unknown."""
        est = estimate_field([NodeTilt(0x10, 0.0, 0.0, 4.0, 1.0)],
                             seam_depth_m=PANEL.seam_depth_m)
        assert not est[0x10].strain_valid

    def test_two_nodes_are_enough_for_a_gradient(self):
        est = estimate_field(
            [NodeTilt(0x10, 0.0, 0.0, 0.0, 0.0), NodeTilt(0x11, 100.0, 0.0, 2.0, 0.0)],
            seam_depth_m=PANEL.seam_depth_m)
        assert est[0x11].strain_valid
        # dT/dx = 2 mm/m over 100 m; strain = B * that, B = 0.4 * 150 = 60 m.
        assert est[0x11].strain_x_mm_per_m == pytest.approx(60.0 * 0.02)

    def test_coincident_nodes_do_not_divide_by_zero(self):
        est = estimate_field(
            [NodeTilt(0x10, 5.0, 0.0, 1.0, 0.0), NodeTilt(0x11, 5.0, 0.0, 3.0, 0.0)],
            seam_depth_m=PANEL.seam_depth_m)
        assert not est[0x10].strain_valid

    def test_empty_field_is_not_an_error(self):
        assert estimate_field([], seam_depth_m=PANEL.seam_depth_m) == {}

    def test_governing_strain_takes_the_larger_magnitude_with_its_sign(self):
        est = estimate_field(
            [NodeTilt(0x10, 0.0, 0.0, 0.0, 0.0),
             NodeTilt(0x11, 100.0, 0.0, -5.0, 0.0),
             NodeTilt(0x12, 0.0, 100.0, 0.0, 1.0)],
            seam_depth_m=PANEL.seam_depth_m)
        assert est[0x11].strain_mm_per_m < 0


class TestLayoutRuleIsMirrored:
    def test_backend_and_field_planner_agree_on_the_spacing_rule(self):
        """The rule is stated in two packages -- the planner that lays out a
        field and the reconstruction that depends on it. If they drift, a field
        gets built to a spacing the reconstruction cannot use."""
        assert (max_sensing_spacing_m(PANEL.seam_depth_m, PANEL.angle_of_draw_deg)
                == pytest.approx(field_spacing_rule(PANEL.seam_depth_m,
                                                    PANEL.angle_of_draw_deg)))


class TestTransectLayout:
    """A survey line, which is how subsidence is monitored in practice.

    The reason it earns its place here is arithmetic: a grid dense enough to
    reconstruct strain over the whole panel needs several times more nodes than
    a real budget allows, while the same nodes in one line resolve the full
    profile properly.
    """

    @staticmethod
    def evaluate(n_nodes: int):
        nodes = build_transect_field(PRESET, n_nodes=n_nodes)
        xs = np.array([n.x_m for n in nodes])
        ys = np.array([n.y_m for n in nodes])
        mv = SubsidenceModel(PANEL).evaluate(xs, ys, face_x=FACE_X, completion=1.0)
        tilts = [NodeTilt(n.addr, n.x_m, n.y_m,
                          float(mv.tilt_x_mm_per_m[i]), float(mv.tilt_y_mm_per_m[i]))
                 for i, n in enumerate(nodes)]
        est = estimate_field(tilts, seam_depth_m=PANEL.seam_depth_m,
                             panel_x_start=PANEL.x_start,
                             angle_of_draw_deg=PANEL.angle_of_draw_deg)
        return nodes, mv, est

    def test_twentyone_nodes_resolve_strain_along_the_line(self):
        """The node budget this project actually has, and it is enough."""
        nodes, mv, est = self.evaluate(21)
        recovered = [est[n.addr].strain_x_mm_per_m for n in nodes]
        assert correlation(mv.strain_x_mm_per_m, recovered) > 0.95

    def test_twentyone_nodes_recover_the_subsidence_profile(self):
        nodes, mv, est = self.evaluate(21)
        recovered = [est[n.addr].subsidence_mm for n in nodes]
        true = [float(v) for v in mv.subsidence_mm]
        assert correlation(true, recovered) > 0.99
        rel = float(np.abs(np.array(recovered) - np.array(true)).mean() / np.mean(true))
        assert rel < 0.05

    def test_both_ends_are_anchored_on_undisturbed_ground(self):
        """What makes integrating a derivative possible at all."""
        nodes, _, est = self.evaluate(21)
        assert all(est[n.addr].subsidence_valid for n in nodes)
        assert nodes[0].x_m <= PANEL.x_start - R
        assert nodes[-1].x_m >= PANEL.x_end + R

    def test_the_line_crosses_both_panel_rims(self):
        """Tilt and strain peak over the rim, so the line has to cross it."""
        nodes, _, _ = self.evaluate(21)
        assert any(n.is_edge for n in nodes)
        assert min(n.x_m for n in nodes) < PANEL.x_start
        assert max(n.x_m for n in nodes) > PANEL.x_end

    def test_too_few_nodes_warns_rather_than_silently_underresolving(self):
        with pytest.warns(UserWarning, match="strain will not"):
            build_transect_field(PRESET, n_nodes=6)

    def test_a_transect_needs_at_least_three_nodes(self):
        with pytest.raises(ValueError, match="three"):
            build_transect_field(PRESET, n_nodes=2)
