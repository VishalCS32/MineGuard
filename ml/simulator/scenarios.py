"""Labelled scenarios: the ground truth the AI learns from and is judged against.

Five scenarios, chosen so that the model is forced to be *specific* as well as
sensitive. Two of them contain no subsidence at all:

  stable          quiet ground, thermal drift only        -> must NOT alert
  false_alarm     blasting + heavy vehicles, no movement  -> must NOT alert
  slow_creep      normal face advance, gradual trough     -> should alert, early
  accelerating    advance rate climbing, trough deepening -> must alert with lead time
  sudden_collapse localised pothole over a goaf void      -> must alert immediately

A system that fires on every passing dumper is worse than useless in a working
mine -- operators switch it off. ``false_alarm`` exists to make precision testable,
not just recall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from subnet_proto import Telemetry

from .field import NodeSpec, SitePreset
from .physics import SubsidenceModel, classify_damage
from .sensors import Environment, NodeSensorModel

__all__ = ["Scenario", "StableScenario", "SlowCreepScenario", "AcceleratingScenario",
           "SuddenCollapseScenario", "FalseAlarmScenario", "SCENARIOS",
           "GroundTruth", "NodeSample", "FieldSample", "FieldSimulator"]

SECONDS_PER_DAY = 86_400


@dataclass(slots=True)
class Perturbation:
    """A non-subsidence disturbance layered on top of the physics."""

    extra_vib_mg: float = 0.0
    vib_peak_hz: int | None = None
    extra_tilt_x: float = 0.0      # mm/m
    extra_tilt_y: float = 0.0
    extra_strain: float = 0.0
    extra_subsidence_mm: float = 0.0
    extra_rate_mm_per_hr: float = 0.0


@dataclass(slots=True)
class GroundTruth:
    """What is really happening at a node -- known exactly, because we built it."""

    subsidence_mm: float
    tilt_mm_per_m: float
    strain_mm_per_m: float
    subsidence_rate_mm_per_hr: float
    damage_class: str
    is_anomalous: bool          # is genuine ground movement under way here?


@dataclass(slots=True)
class NodeSample:
    node: NodeSpec
    telemetry: Telemetry
    truth: GroundTruth


@dataclass(slots=True)
class FieldSample:
    """One sweep of the whole field at a single instant."""

    t_epoch: int
    day: float
    face_x_m: float
    scenario: str
    temperature_c: float
    nodes: list[NodeSample] = field(default_factory=list)


# ================================================================= scenarios
class Scenario:
    """Base scenario. Subclasses describe how the face advances and what else
    is happening on the surface."""

    name = "base"
    description = ""
    duration_days = 10.0
    #: Genuine ground movement above this tilt is considered a real event, and is
    #: what an alert is expected to catch. Below it, the ground is merely settling.
    anomaly_tilt_mm_per_m = 1.0

    def __init__(self, preset: SitePreset, rng: np.random.Generator | None = None):
        self.preset = preset
        self.panel = preset.panel
        self.rng = rng if rng is not None else np.random.default_rng()

    # -- what the mine is doing ------------------------------------------------
    def face_x(self, day: float) -> float:
        """Position of the working face at ``day``."""
        return self.panel.x_start

    def completion(self, day: float) -> float:
        """How far the surface has caught up with the extraction beneath it."""
        return 1.0

    # -- what else is going on -------------------------------------------------
    def perturb(self, day: float, node: NodeSpec) -> Perturbation:
        return Perturbation()

    def environment(self, day: float) -> Environment:
        return Environment.at_hour((day * 24.0) % 24.0)


class StableScenario(Scenario):
    """No extraction. Ground is quiet; only thermal drift and sensor noise move.

    The hardest negative case: tilt readings *do* wander by a tenth of a degree
    across a day, and a naive threshold on raw tilt will fire on sunshine.
    """

    name = "stable"
    description = "Quiet ground, diurnal thermal drift only"
    duration_days = 7.0


class SlowCreepScenario(Scenario):
    """Routine longwall advance. A trough forms gradually over days."""

    name = "slow_creep"
    description = "Normal face advance at 4 m/day, gradual trough development"
    duration_days = 21.0

    advance_m_per_day = 4.0

    def face_x(self, day: float) -> float:
        return self.panel.x_start + self.advance_m_per_day * day

    def completion(self, day: float) -> float:
        # Knothe time lag: the surface trails the face and asymptotes to its final
        # shape, so early movement is smaller than the geometry alone implies.
        return 1.0 - math.exp(-0.35 * max(day, 0.0))


class AcceleratingScenario(SlowCreepScenario):
    """Advance rate climbing -- the case the system exists to catch.

    Subsidence rate rises super-linearly, so tilt rate has a detectable inflection
    well before any absolute threshold is crossed. That gap is the lead time.
    """

    name = "accelerating"
    description = "Face advance accelerating; subsidence rate climbing toward failure"
    duration_days = 14.0

    def face_x(self, day: float) -> float:
        # Quadratic advance: 4 m/day baseline, ramping through the run.
        return self.panel.x_start + self.advance_m_per_day * day * (1.0 + 0.12 * day)

    def completion(self, day: float) -> float:
        return 1.0 - math.exp(-0.55 * max(day, 0.0))


class SuddenCollapseScenario(SlowCreepScenario):
    """A localised pothole opens above a goaf void.

    Unlike the smooth regional trough this is sharp and local: one or two nodes see
    a violent step in tilt and strain plus a burst of low-frequency energy, while
    the rest of the field stays calm. Detecting it needs the *spatial* pattern --
    a single node cannot distinguish this from being knocked by a cow.
    """

    name = "sudden_collapse"
    description = "Localised pothole collapse over a goaf void"
    duration_days = 12.0

    collapse_day = 8.0
    collapse_duration_days = 0.08      # ~2 hours from first movement to full depth
    collapse_depth_mm = 900.0
    collapse_sigma_m = 45.0

    def __init__(self, preset: SitePreset, rng: np.random.Generator | None = None,
                 centre: tuple[float, float] | None = None):
        super().__init__(preset, rng)
        p = self.panel
        if centre is not None:
            self.cx, self.cy = centre
        else:
            # A pothole can only open over ground that has actually been mined out,
            # so the centre is placed back inside the goaf relative to wherever the
            # face has reached by collapse day -- never ahead of it, over solid coal.
            goaf_end = self.face_x(self.collapse_day)
            self.cx = p.x_start + 0.4 * (goaf_end - p.x_start)
            # Offset off the panel centreline so the collapse does not land exactly
            # on top of a node. Real failures do not oblige us that way, and the
            # system has to localise from surrounding nodes by interpolation.
            self.cy = 0.5 * (p.y_min + p.y_max) + 0.5 * self.collapse_sigma_m

    @property
    def goaf_end_at_collapse(self) -> float:
        """Face position when the collapse begins -- the pothole must sit behind it."""
        return self.face_x(self.collapse_day)

    def _ramp(self, day: float) -> float:
        if day < self.collapse_day:
            return 0.0
        progress = (day - self.collapse_day) / self.collapse_duration_days
        return float(min(1.0, progress))

    def perturb(self, day: float, node: NodeSpec) -> Perturbation:
        ramp = self._ramp(day)
        if ramp <= 0.0:
            return Perturbation()

        dx, dy = node.x_m - self.cx, node.y_m - self.cy
        s2 = self.collapse_sigma_m**2
        bump = math.exp(-(dx * dx + dy * dy) / (2 * s2))
        depth = self.collapse_depth_mm * ramp

        # Analytic derivatives of the Gaussian pothole.
        extra_sub = depth * bump
        tilt_x = -depth * bump * dx / s2          # mm per m
        tilt_y = -depth * bump * dy / s2
        curvature_x = depth * bump * (dx * dx / (s2 * s2) - 1.0 / s2)
        strain = self.panel.b_coefficient_m * curvature_x

        # Rate is the whole depth arriving inside the collapse window.
        rate = (self.collapse_depth_mm * bump
                / (self.collapse_duration_days * 24.0)) if ramp < 1.0 else 0.0
        # Roof failure radiates low-frequency energy, strongest at the pothole.
        vib = 260.0 * bump if ramp < 1.0 else 25.0 * bump

        return Perturbation(extra_vib_mg=vib,
                            vib_peak_hz=int(self.rng.uniform(4, 11)) if vib > 40 else None,
                            extra_tilt_x=tilt_x, extra_tilt_y=tilt_y,
                            extra_strain=strain, extra_subsidence_mm=extra_sub,
                            extra_rate_mm_per_hr=rate)


class FalseAlarmScenario(Scenario):
    """Quiet ground, noisy surface: production blasting and haul-road traffic.

    Big vibration transients with *no* accompanying tilt or strain change. Any
    model that keys on vibration alone fails here -- and in a real mine that means
    nuisance alerts every shift until someone disables the system.
    """

    name = "false_alarm"
    description = "Blasting and haul traffic; strong vibration, zero ground movement"
    duration_days = 7.0

    def __init__(self, preset: SitePreset, rng: np.random.Generator | None = None):
        super().__init__(preset, rng)
        # Blasts happen on shift boundaries, traffic through the working day.
        self.blast_days = [d + 0.60 for d in range(int(self.duration_days))]

    def perturb(self, day: float, node: NodeSpec) -> Perturbation:
        for blast in self.blast_days:
            dt_hours = (day - blast) * 24.0
            if 0 <= dt_hours < 0.25:           # a 15-minute decaying ring-down
                amplitude = 700.0 * math.exp(-dt_hours / 0.05)
                return Perturbation(extra_vib_mg=amplitude,
                                    vib_peak_hz=int(self.rng.uniform(28, 80)))

        hour = (day * 24.0) % 24.0
        if 7.0 <= hour <= 19.0 and self.rng.random() < 0.05:
            return Perturbation(extra_vib_mg=float(self.rng.uniform(90, 320)),
                                vib_peak_hz=int(self.rng.uniform(15, 45)))
        return Perturbation()


SCENARIOS: dict[str, type[Scenario]] = {
    s.name: s for s in (StableScenario, SlowCreepScenario, AcceleratingScenario,
                        SuddenCollapseScenario, FalseAlarmScenario)
}


# ================================================================== simulator
class FieldSimulator:
    """Drives a scenario across a node field, producing labelled telemetry."""

    def __init__(self, preset: SitePreset, nodes: list[NodeSpec], scenario: Scenario,
                 seed: int = 0, gateway_xy: tuple[float, float] | None = None):
        self.preset = preset
        self.nodes = nodes
        self.scenario = scenario
        self.model = SubsidenceModel(preset.panel)
        self.rng = np.random.default_rng(seed)
        self.gateway_xy = gateway_xy if gateway_xy is not None else (
            preset.panel.x_start - 0.5 * preset.panel.radius_of_influence_m, 0.0)
        self.sensors = {
            n.addr: NodeSensorModel(addr=n.addr, lat=n.lat, lon=n.lon,
                                    rng=np.random.default_rng(seed + n.addr))
            for n in nodes
        }
        self._xs = np.array([n.x_m for n in nodes])
        self._ys = np.array([n.y_m for n in nodes])

    def sample_at(self, day: float, t_epoch: int) -> FieldSample:
        """Evaluate the whole field at one instant."""
        sc = self.scenario
        face_x = sc.face_x(day)
        completion = sc.completion(day)
        env = sc.environment(day)

        mv = self.model.evaluate(self._xs, self._ys, face_x=face_x, completion=completion)
        # Subsidence rate from a short finite difference of the evolving surface.
        dt_day = 1.0 / 24.0
        prev = self.model.evaluate(self._xs, self._ys,
                                   face_x=sc.face_x(day - dt_day),
                                   completion=sc.completion(day - dt_day))
        rate_mm_per_hr = (mv.subsidence_mm - prev.subsidence_mm) / (dt_day * 24.0)

        sample = FieldSample(t_epoch=t_epoch, day=day, face_x_m=face_x,
                             scenario=sc.name, temperature_c=env.temperature_c)

        tilt_mag = mv.tilt_mm_per_m
        strain = mv.strain_mm_per_m

        for i, node in enumerate(self.nodes):
            pert = sc.perturb(day, node)
            tx = float(mv.tilt_x_mm_per_m[i]) + pert.extra_tilt_x
            ty = float(mv.tilt_y_mm_per_m[i]) + pert.extra_tilt_y
            st = float(strain[i]) + pert.extra_strain
            sub = float(mv.subsidence_mm[i]) + pert.extra_subsidence_mm
            rate = float(rate_mm_per_hr[i]) + pert.extra_rate_mm_per_hr
            total_tilt = math.hypot(tx, ty)

            rssi, snr = self._link_quality(node)
            tlm = self.sensors[node.addr].read(
                t_epoch=t_epoch, tilt_x_mm_per_m=tx, tilt_y_mm_per_m=ty,
                subsidence_rate_mm_per_hr=rate, env=env,
                rssi=rssi, snr_db=snr,
                extra_vibration_mg=pert.extra_vib_mg,
                vibration_peak_hz=pert.vib_peak_hz)

            truth = GroundTruth(
                subsidence_mm=sub,
                tilt_mm_per_m=total_tilt,
                strain_mm_per_m=st,
                subsidence_rate_mm_per_hr=rate,
                damage_class=classify_damage(st, total_tilt),
                is_anomalous=total_tilt >= sc.anomaly_tilt_mm_per_m,
            )
            sample.nodes.append(NodeSample(node=node, telemetry=tlm, truth=truth))

        return sample

    def run(self, sample_interval_s: int = 300, start_epoch: int = 1_767_225_600,
            duration_days: float | None = None) -> Iterator[FieldSample]:
        """Play the scenario start to finish, yielding one FieldSample per interval."""
        total = duration_days if duration_days is not None else self.scenario.duration_days
        steps = int(total * SECONDS_PER_DAY / sample_interval_s)
        for i in range(steps):
            t = start_epoch + i * sample_interval_s
            yield self.sample_at(day=i * sample_interval_s / SECONDS_PER_DAY, t_epoch=t)

    def _link_quality(self, node: NodeSpec) -> tuple[int, float]:
        """Log-distance path loss to the gateway, with shadowing.

        Realistic enough that distant nodes genuinely need a relay hop, which is
        what makes the mesh earn its place rather than being decoration.
        """
        gx, gy = self.gateway_xy
        d = max(1.0, math.hypot(node.x_m - gx, node.y_m - gy))
        rssi = -43.0 - 10 * 2.7 * math.log10(d) + self.rng.normal(0, 3.0)
        snr = float(np.clip(14.0 + (rssi + 100) * 0.25 + self.rng.normal(0, 1.2), -18, 30))
        return int(np.clip(rssi, -128, 0)), snr
