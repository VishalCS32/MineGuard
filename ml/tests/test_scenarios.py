"""Tests for the labelled scenarios.

The headline test is ``TestDiscriminability`` -- it asserts that the negative
scenarios are genuinely hard, so that a model which passes them has learned
something rather than memorised a threshold.
"""

from __future__ import annotations

import numpy as np
import pytest

from simulator.field import SITE_PRESETS, build_grid_field
from simulator.scenarios import (
    SCENARIOS,
    AcceleratingScenario,
    FalseAlarmScenario,
    FieldSimulator,
    SlowCreepScenario,
    StableScenario,
    SuddenCollapseScenario,
)

PRESET = SITE_PRESETS["jharia"]


@pytest.fixture(scope="module")
def nodes():
    return build_grid_field(PRESET, cols=5, rows=3)


def run(scenario_cls, nodes, interval_s=1800, seed=1, days=None):
    sim = FieldSimulator(PRESET, nodes, scenario_cls(PRESET, np.random.default_rng(seed)),
                         seed=seed)
    return list(sim.run(sample_interval_s=interval_s, duration_days=days))


class TestScenarioRegistry:
    def test_all_five_registered(self):
        assert set(SCENARIOS) == {"stable", "slow_creep", "accelerating",
                                  "sudden_collapse", "false_alarm"}

    def test_every_scenario_produces_a_frame_for_every_node(self, nodes):
        for cls in SCENARIOS.values():
            sample = run(cls, nodes, days=0.5)[0]
            assert len(sample.nodes) == len(nodes)
            assert {ns.node.addr for ns in sample.nodes} == {n.addr for n in nodes}


class TestQuietScenarios:
    def test_stable_ground_never_moves(self, nodes):
        for s in run(StableScenario, nodes, days=2):
            assert all(ns.truth.tilt_mm_per_m == 0 for ns in s.nodes)
            assert all(not ns.truth.is_anomalous for ns in s.nodes)

    def test_stable_tilt_readings_still_wander_with_temperature(self, nodes):
        """Ground is still, readings are not -- that is the whole difficulty."""
        samples = run(StableScenario, nodes, days=3)
        addr = nodes[0].addr
        series = [next(ns.telemetry.pitch_mdeg for ns in s.nodes if ns.node.addr == addr)
                  for s in samples]
        assert np.ptp(series) > 150       # over 0.15 deg of apparent movement

    def test_false_alarm_has_no_real_movement(self, nodes):
        for s in run(FalseAlarmScenario, nodes, days=3):
            assert all(ns.truth.tilt_mm_per_m == 0 for ns in s.nodes)
            assert all(not ns.truth.is_anomalous for ns in s.nodes)

    def test_false_alarm_produces_violent_vibration(self, nodes):
        peak = max(ns.telemetry.vib_rms_mg
                   for s in run(FalseAlarmScenario, nodes, interval_s=300, days=3)
                   for ns in s.nodes)
        assert peak > 250


class TestSubsidenceScenarios:
    def test_creep_face_advances_monotonically(self, nodes):
        faces = [s.face_x_m for s in run(SlowCreepScenario, nodes, days=6)]
        assert all(b >= a for a, b in zip(faces, faces[1:]))
        assert faces[-1] > faces[0]

    def test_creep_develops_real_tilt(self, nodes):
        peak = max(ns.truth.tilt_mm_per_m
                   for s in run(SlowCreepScenario, nodes) for ns in s.nodes)
        assert peak > 1.0

    def test_accelerating_outpaces_creep_at_the_same_moment(self, nodes):
        """Both start alike; the accelerating case must pull ahead."""
        day = 8.0
        creep = FieldSimulator(PRESET, nodes, SlowCreepScenario(PRESET), seed=1)
        accel = FieldSimulator(PRESET, nodes, AcceleratingScenario(PRESET), seed=1)
        c = max(ns.truth.subsidence_mm for ns in creep.sample_at(day, 0).nodes)
        a = max(ns.truth.subsidence_mm for ns in accel.sample_at(day, 0).nodes)
        assert a > c * 1.2

    def test_accelerating_rate_increases_over_time(self, nodes):
        """The inflection in subsidence *rate* is the early-warning signal."""
        sim = FieldSimulator(PRESET, nodes, AcceleratingScenario(PRESET), seed=1)
        rates = [max(ns.truth.subsidence_rate_mm_per_hr for ns in sim.sample_at(d, 0).nodes)
                 for d in (2.0, 5.0, 8.0)]
        assert rates[1] > rates[0] and rates[2] > rates[1]


class TestSuddenCollapse:
    def test_nothing_happens_before_the_collapse(self, nodes):
        sim = FieldSimulator(PRESET, nodes, SuddenCollapseScenario(PRESET), seed=1)
        before = sim.sample_at(SuddenCollapseScenario.collapse_day - 0.5, 0)
        after = sim.sample_at(SuddenCollapseScenario.collapse_day + 0.05, 0)
        assert max(ns.telemetry.vib_rms_mg for ns in after.nodes) > \
               max(ns.telemetry.vib_rms_mg for ns in before.nodes) + 100

    def test_pothole_forms_over_the_goaf_not_ahead_of_the_face(self):
        """Physical validity: unmined ground cannot collapse into a void that does
        not exist yet. Placing the pothole ahead of the face would silently teach
        the model an impossible signature."""
        sc = SuddenCollapseScenario(PRESET)
        assert PRESET.panel.x_start <= sc.cx <= sc.goaf_end_at_collapse

    def test_collapse_is_spatially_localised(self, nodes):
        """A single node cannot tell a pothole from a knock; the field can.

        The nearest node must see far more movement than the farthest -- that
        spatial contrast is exactly what the mesh buys us.
        """
        sc = SuddenCollapseScenario(PRESET)
        sim = FieldSimulator(PRESET, nodes, sc, seed=1)
        s = sim.sample_at(sc.collapse_day + 0.06, 0)
        by_dist = sorted(s.nodes, key=lambda ns: np.hypot(ns.node.x_m - sc.cx,
                                                          ns.node.y_m - sc.cy))
        nearest, farthest = by_dist[0], by_dist[-1]
        assert nearest.truth.subsidence_mm > farthest.truth.subsidence_mm + 100

    def test_collapse_reaches_full_depth_and_holds(self, nodes):
        sc = SuddenCollapseScenario(PRESET)
        sim = FieldSimulator(PRESET, nodes, sc, seed=1)
        late = sim.sample_at(sc.collapse_day + 1.0, 0)
        peak = max(ns.truth.subsidence_mm for ns in late.nodes)
        assert peak > sc.collapse_depth_mm * 0.5


class TestDiscriminability:
    """The tests that make the AI's job honest."""

    def test_benign_blasting_out_vibrates_genuine_creeping_subsidence(self, nodes):
        """The crux of the design, and the case for multi-sensor nodes.

        A violent pothole collapse does shake the ground hard -- but by then the
        ground has already failed and early warning has been missed. The cases
        worth catching early, slow creep and accelerating subsidence, are almost
        silent: they move the ground without shaking it. Meanwhile routine
        blasting is loud and entirely benign.

        So any vibration threshold is trapped. Set it low enough to react to real
        subsidence and it fires on every blast; set it above blasting and it stays
        silent through the entire run-up to failure. Vibration cannot carry the
        detection on its own -- tilt and strain must.
        """
        blast_peak = max(ns.telemetry.vib_rms_mg
                         for s in run(FalseAlarmScenario, nodes, interval_s=300, days=3)
                         for ns in s.nodes)
        creeping_peak = max(ns.telemetry.vib_rms_mg
                            for s in run(AcceleratingScenario, nodes, interval_s=300)
                            for ns in s.nodes)
        assert blast_peak > creeping_peak * 5

    def test_a_violent_collapse_does_shake_the_ground(self, nodes):
        """Stated for completeness: once the roof actually goes, vibration is
        unmistakable. That is confirmation, not early warning."""
        collapse_peak = max(ns.telemetry.vib_rms_mg
                            for s in run(SuddenCollapseScenario, nodes, interval_s=300)
                            for ns in s.nodes)
        assert collapse_peak > 800

    def test_but_tilt_separates_them_cleanly(self, nodes):
        blast_tilt = max(ns.truth.tilt_mm_per_m
                         for s in run(FalseAlarmScenario, nodes, days=3) for ns in s.nodes)
        collapse_tilt = max(ns.truth.tilt_mm_per_m
                            for s in run(SuddenCollapseScenario, nodes) for ns in s.nodes)
        assert blast_tilt == 0.0
        assert collapse_tilt > 1.0

    def test_negative_scenarios_carry_no_positive_labels(self, nodes):
        """Guards the label generator itself: a leaked positive here would teach
        the model that blasting means subsidence."""
        for cls in (StableScenario, FalseAlarmScenario):
            assert not any(ns.truth.is_anomalous
                           for s in run(cls, nodes, days=3) for ns in s.nodes)

    def test_positive_scenarios_do_carry_positive_labels(self, nodes):
        for cls in (SlowCreepScenario, AcceleratingScenario, SuddenCollapseScenario):
            assert any(ns.truth.is_anomalous for s in run(cls, nodes) for ns in s.nodes)


class TestLinkQuality:
    def test_distant_nodes_have_weaker_links(self, nodes):
        """Path loss must be real enough that far nodes genuinely need a relay."""
        sim = FieldSimulator(PRESET, nodes, StableScenario(PRESET), seed=1)
        gx, gy = sim.gateway_xy
        s = sim.sample_at(0.0, 0)
        ranked = sorted(s.nodes, key=lambda ns: np.hypot(ns.node.x_m - gx, ns.node.y_m - gy))
        assert ranked[0].telemetry.rssi > ranked[-1].telemetry.rssi + 10

    def test_rssi_stays_in_physical_range(self, nodes):
        for s in run(StableScenario, nodes, days=1):
            for ns in s.nodes:
                assert -128 <= ns.telemetry.rssi <= 0
                assert -20 <= ns.telemetry.snr_db <= 32
