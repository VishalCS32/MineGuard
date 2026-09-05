"""Tests for the subsidence physics.

These assert published analytical results, not just self-consistency. If the model
stops reproducing the half-subsidence-at-the-edge rule or the tension-at-the-rim
signature, the training data is fiction and the AI is worthless -- so these are the
most important tests in the project.
"""

from __future__ import annotations

import numpy as np
import pytest

from simulator.physics import (
    DamageClass,
    PanelGeometry,
    SubsidenceModel,
    classify_damage,
)


@pytest.fixture
def supercritical() -> SubsidenceModel:
    """A panel wide enough in both axes to develop full S_max at its centre."""
    return SubsidenceModel(PanelGeometry(
        x_start=0, x_end=2000, y_min=-1000, y_max=1000,
        seam_depth_m=150, extraction_thickness_m=3.0,
        subsidence_factor=0.65, angle_of_draw_deg=35))


@pytest.fixture
def standard() -> SubsidenceModel:
    return SubsidenceModel(PanelGeometry())


class TestPanelGeometry:
    def test_s_max_is_factor_times_thickness(self):
        p = PanelGeometry(extraction_thickness_m=3.0, subsidence_factor=0.65)
        assert p.s_max_m == pytest.approx(1.95)

    def test_radius_of_influence_from_angle_of_draw(self):
        """r = H / tan(beta): a 45 degree draw angle puts r exactly at depth."""
        assert PanelGeometry(seam_depth_m=200, angle_of_draw_deg=45
                             ).radius_of_influence_m == pytest.approx(200.0)

    def test_shallower_draw_angle_reaches_further(self):
        shallow = PanelGeometry(angle_of_draw_deg=25).radius_of_influence_m
        steep = PanelGeometry(angle_of_draw_deg=45).radius_of_influence_m
        assert shallow > steep

    @pytest.mark.parametrize("kwargs", [
        {"x_end": -10},
        {"subsidence_factor": 1.4},
        {"subsidence_factor": 0},
        {"angle_of_draw_deg": 0},
        {"angle_of_draw_deg": 95},
        {"seam_depth_m": 0},
        {"extraction_thickness_m": -1},
    ])
    def test_rejects_invalid_geometry(self, kwargs):
        with pytest.raises(ValueError):
            PanelGeometry(**kwargs)


class TestSubsidenceProfile:
    def test_supercritical_panel_reaches_full_s_max(self, supercritical):
        centre = supercritical.evaluate(np.array([1000.0]), np.array([0.0]), face_x=2000)
        assert centre.subsidence_mm[0] == pytest.approx(1950.0, rel=1e-3)

    def test_subcritical_panel_falls_short_of_s_max(self):
        """A narrow panel cannot develop full subsidence -- a real safety-relevant
        effect, and the reason panel width matters as much as extraction height."""
        model = SubsidenceModel(PanelGeometry(y_min=-50, y_max=50))
        assert model.panel.is_subcritical
        peak = model.evaluate(np.array([300.0]), np.array([0.0]), face_x=600).subsidence_mm[0]
        assert peak < 0.5 * model.panel.s_max_m * 1000

    def test_half_subsidence_over_the_panel_edge(self, supercritical):
        """The classic result: directly above the edge, S = S_max / 2."""
        pts = np.array([1000.0, 2000.0])
        mv = supercritical.evaluate(pts, np.zeros(2), face_x=2000)
        assert mv.subsidence_mm[1] == pytest.approx(mv.subsidence_mm[0] / 2, rel=1e-3)

    def test_profile_is_symmetric_about_panel_centre(self, standard):
        offsets = np.array([50.0, 150.0, 250.0, 400.0])
        left = standard.evaluate(300 - offsets, np.zeros(4), face_x=600).subsidence_mm
        right = standard.evaluate(300 + offsets, np.zeros(4), face_x=600).subsidence_mm
        assert left == pytest.approx(right, rel=1e-9)

    def test_subsidence_decays_far_outside_the_draw_angle(self, standard):
        r = standard.panel.radius_of_influence_m
        far = standard.evaluate(np.array([-3 * r]), np.array([0.0]), face_x=600)
        assert far.subsidence_mm[0] < 1.0        # sub-millimetre: undisturbed

    def test_monotonic_from_rim_to_centre(self, standard):
        x = np.linspace(-300, 300, 40)
        s = standard.evaluate(x, np.zeros_like(x), face_x=600).subsidence_mm
        assert np.all(np.diff(s) > 0)

    def test_no_movement_before_extraction_begins(self, standard):
        x = np.linspace(-200, 800, 20)
        mv = standard.evaluate(x, np.zeros_like(x), face_x=0.0)
        assert np.all(mv.subsidence_mm == 0)
        assert np.all(mv.tilt_mm_per_m == 0)

    def test_subsidence_grows_as_the_face_advances(self, standard):
        """The core temporal signal the early-warning system detects."""
        pt, zero = np.array([200.0]), np.array([0.0])
        series = [standard.evaluate(pt, zero, face_x=f).subsidence_mm[0]
                  for f in (100, 200, 300, 400, 500, 600)]
        assert all(b > a for a, b in zip(series, series[1:]))

    def test_completion_scales_the_whole_field(self, standard):
        x, y = np.array([250.0]), np.array([0.0])
        full = standard.evaluate(x, y, face_x=600, completion=1.0)
        half = standard.evaluate(x, y, face_x=600, completion=0.5)
        assert half.subsidence_mm[0] == pytest.approx(full.subsidence_mm[0] / 2)

    @pytest.mark.parametrize("completion", [-0.1, 1.1])
    def test_rejects_out_of_range_completion(self, standard, completion):
        with pytest.raises(ValueError, match="completion"):
            standard.evaluate(np.array([0.0]), np.array([0.0]), 600, completion)

    def test_rejects_mismatched_point_arrays(self, standard):
        with pytest.raises(ValueError, match="share a shape"):
            standard.evaluate(np.zeros(3), np.zeros(4), face_x=600)


class TestTilt:
    def test_tilt_vanishes_at_the_trough_centre(self, standard):
        mv = standard.evaluate(np.array([300.0]), np.array([0.0]), face_x=600)
        assert mv.tilt_mm_per_m[0] == pytest.approx(0.0, abs=1e-9)

    def test_tilt_peaks_over_the_panel_edge(self, standard):
        """Maximum tilt sits above the edge -- so edge nodes see movement first."""
        x = np.linspace(-200, 300, 200)
        tilt = standard.evaluate(x, np.zeros_like(x), face_x=600).tilt_mm_per_m
        assert x[int(np.argmax(tilt))] == pytest.approx(0.0, abs=5.0)

    def test_tilt_sign_inverts_across_the_trough(self, standard):
        """The mesh signature a single node can never see: tilt flips direction
        between the two flanks of the trough."""
        mv = standard.evaluate(np.array([100.0, 500.0]), np.zeros(2), face_x=600)
        assert mv.tilt_x_mm_per_m[0] * mv.tilt_x_mm_per_m[1] < 0

    def test_tilt_degrees_agree_with_gradient(self, standard):
        mv = standard.evaluate(np.array([0.0]), np.array([0.0]), face_x=600)
        expected = np.degrees(np.arctan(mv.tilt_mm_per_m[0] / 1000.0))
        assert mv.tilt_deg[0] == pytest.approx(expected)


class TestStrain:
    def test_tensile_outside_the_edge_compressive_over_the_goaf(self, standard):
        """The signature that makes crack sensors work: ground is pulled apart at
        the rim and squeezed at the centre."""
        mv = standard.evaluate(np.array([-120.0, 300.0]), np.zeros(2), face_x=600)
        assert mv.strain_x_mm_per_m[0] > 0      # rim: tension, cracks open
        assert mv.strain_x_mm_per_m[1] < 0      # centre: compression

    def test_governing_strain_keeps_its_sign(self, standard):
        mv = standard.evaluate(np.array([-120.0]), np.array([0.0]), face_x=600)
        assert mv.strain_mm_per_m[0] > 0

    def test_governing_strain_takes_the_larger_axis(self, standard):
        x = np.linspace(-200, 800, 50)
        mv = standard.evaluate(x, np.full_like(x, 20.0), face_x=600)
        governing = np.abs(mv.strain_mm_per_m)
        assert np.all(governing >= np.abs(mv.strain_x_mm_per_m) - 1e-12)
        assert np.all(governing >= np.abs(mv.strain_y_mm_per_m) - 1e-12)

    def test_horizontal_displacement_is_b_times_tilt(self, standard):
        mv = standard.evaluate(np.array([50.0]), np.array([0.0]), face_x=600)
        b = standard.panel.b_coefficient_m
        assert mv.disp_x_mm[0] == pytest.approx(b * mv.tilt_x_mm_per_m[0])


class TestDerivativesAreConsistent:
    """Analytic derivatives must match finite differences of the surface itself.

    This is the check that catches an algebra slip in the closed forms -- the kind
    of bug that would otherwise quietly poison every training sample.
    """

    def test_tilt_matches_numerical_gradient(self, standard):
        x = np.linspace(-150, 750, 60)
        h = 0.05
        s_plus = standard.evaluate(x + h, np.zeros_like(x), face_x=600).subsidence_mm
        s_minus = standard.evaluate(x - h, np.zeros_like(x), face_x=600).subsidence_mm
        numerical = (s_plus - s_minus) / (2 * h)
        analytic = standard.evaluate(x, np.zeros_like(x), face_x=600).tilt_x_mm_per_m
        assert analytic == pytest.approx(numerical, abs=1e-6)

    def test_strain_matches_second_numerical_derivative(self, standard):
        x = np.linspace(-150, 750, 60)
        h = 0.5
        zero = np.zeros_like(x)
        s_p = standard.evaluate(x + h, zero, face_x=600).subsidence_mm
        s_0 = standard.evaluate(x, zero, face_x=600).subsidence_mm
        s_m = standard.evaluate(x - h, zero, face_x=600).subsidence_mm
        numerical = standard.panel.b_coefficient_m * (s_p - 2 * s_0 + s_m) / h**2
        analytic = standard.evaluate(x, zero, face_x=600).strain_x_mm_per_m
        assert analytic == pytest.approx(numerical, abs=1e-4)

    def test_y_axis_derivatives_match_too(self, standard):
        y = np.linspace(-250, 250, 40)
        h = 0.05
        x = np.full_like(y, 300.0)
        s_p = standard.evaluate(x, y + h, face_x=600).subsidence_mm
        s_m = standard.evaluate(x, y - h, face_x=600).subsidence_mm
        analytic = standard.evaluate(x, y, face_x=600).tilt_y_mm_per_m
        assert analytic == pytest.approx((s_p - s_m) / (2 * h), abs=1e-6)


class TestDamageClassification:
    @pytest.mark.parametrize("strain,expected", [
        (0.0, DamageClass.NEGLIGIBLE),
        (0.4, DamageClass.NEGLIGIBLE),
        (1.0, DamageClass.SLIGHT),
        (2.5, DamageClass.APPRECIABLE),
        (4.0, DamageClass.SEVERE),
        (9.0, DamageClass.VERY_SEVERE),
    ])
    def test_bands(self, strain, expected):
        assert classify_damage(strain) == expected

    def test_compression_is_classified_by_magnitude(self):
        """Compressive strain buckles structures; it is not benign."""
        assert classify_damage(-4.0) == classify_damage(4.0) == DamageClass.SEVERE

    def test_high_tilt_escalates_one_band(self):
        assert classify_damage(1.0, tilt_mm_per_m=2.0) == DamageClass.SLIGHT
        assert classify_damage(1.0, tilt_mm_per_m=15.0) == DamageClass.APPRECIABLE

    def test_escalation_saturates_at_the_top_band(self):
        assert classify_damage(20.0, tilt_mm_per_m=50.0) == DamageClass.VERY_SEVERE
