"""Turn ground movement into what the hardware actually reports.

The physics module says how the ground moves. This module says what an ESP32-S3
with a LIS3DH, a VL53L1X and a crack gauge would *measure* -- which is a different
and much messier thing: every reading carries installation offsets, thermal drift,
quantisation and noise. Training a model on clean physics and deploying it against
noisy hardware is the classic way to build a system that demos well and fails in
the field, so the corruption here is deliberate and calibrated to real datasheets.

Datasheet-derived noise figures
-------------------------------
LIS3DH   +/-2 g, 12-bit -> ~1 mg/LSB -> ~0.06 deg tilt resolution. With on-node
         averaging over a sample window we take ~0.05 deg (50 mdeg) 1-sigma.
VL53L1X  ~+/-5 mm ranging error at 2.5 m; averaging brings 1-sigma to ~3 mm.
Crack    resistive gauge, nominal 1 kOhm, ~1% reading noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from subnet_proto import (
    TLM_CRACK_FAULT,
    TLM_LOW_BATTERY,
    TLM_TILT_FAULT,
    TLM_TOF_FAULT,
    TLM_UNCALIBRATED,
    Telemetry,
)

__all__ = ["NoiseProfile", "Environment", "NodeSensorModel"]


@dataclass(frozen=True, slots=True)
class NoiseProfile:
    """Sensor error budget. Defaults follow the datasheets above."""

    tilt_noise_mdeg: float = 50.0            # LIS3DH, averaged
    tilt_drift_mdeg_per_degc: float = 18.0   # thermal expansion of the mounting post
    tilt_random_walk_mdeg: float = 2.0       # slow bias wander per sample
    tof_noise_mm: float = 3.0                # VL53L1X, averaged
    tof_drift_mm_per_degc: float = 0.35
    crack_noise_fraction: float = 0.01
    vib_ambient_mg: float = 12.0             # wind, distant plant, background
    vib_ambient_sigma_mg: float = 4.0
    vbat_noise_mv: float = 8.0

    # Crack gauge response: resistance climbs once ground goes into tension.
    crack_nominal_ohm: float = 1000.0
    crack_strain_threshold_mm_per_m: float = 1.5
    crack_gain: float = 900.0
    crack_exponent: float = 1.6


@dataclass(slots=True)
class Environment:
    """Site conditions shared by every node at a given instant."""

    temperature_c: float = 28.0
    solar_fraction: float = 0.0   # 0 at night, 1 at solar noon
    rain: bool = False

    @classmethod
    def at_hour(cls, hour_of_day: float, mean_c: float = 28.0,
                swing_c: float = 9.0) -> "Environment":
        """Diurnal cycle: coldest before dawn, hottest mid-afternoon.

        Thermal drift is the single largest false-positive source in a real tilt
        deployment, so the demo has to show the system living with it.
        """
        phase = 2 * math.pi * (hour_of_day - 15.0) / 24.0
        temp = mean_c + 0.5 * swing_c * math.cos(phase)
        solar = max(0.0, math.sin(math.pi * (hour_of_day - 6.0) / 12.0))
        return cls(temperature_c=temp, solar_fraction=solar)


@dataclass(slots=True)
class NodeSensorModel:
    """Per-node sensor state: installation offsets, drift, battery, faults.

    State persists across reads because that is what makes the data realistic --
    bias wanders, batteries deplete, and a node that develops a sensor fault keeps
    it. A memoryless noise model would be far easier for the AI than reality.
    """

    addr: int
    ref_post_distance_mm: int = 2500
    reference_temp_c: float = 28.0
    noise: NoiseProfile = field(default_factory=NoiseProfile)
    rng: np.random.Generator = field(default_factory=np.random.default_rng)

    # -- installation state, fixed at commissioning ---------------------------
    install_pitch_mdeg: int = 0
    install_roll_mdeg: int = 0
    # -- evolving state -------------------------------------------------------
    bias_pitch_mdeg: float = 0.0
    bias_roll_mdeg: float = 0.0
    soc: float = 0.95                # battery state of charge, 0..1
    tilt_fault: bool = False
    tof_fault: bool = False
    crack_fault: bool = False
    calibrated: bool = True
    crack_fractured: bool = False    # once the gauge parts, it stays parted

    def __post_init__(self) -> None:
        # Nodes are hand-planted on uneven ground: a degree or so of install tilt
        # is normal. Deformation is always measured *relative* to this baseline.
        if self.install_pitch_mdeg == 0 and self.install_roll_mdeg == 0:
            self.install_pitch_mdeg = int(self.rng.normal(0, 900))
            self.install_roll_mdeg = int(self.rng.normal(0, 900))

    # ------------------------------------------------------------------ read
    def read(self, *, t_epoch: int, tilt_x_mm_per_m: float, tilt_y_mm_per_m: float,
             strain_mm_per_m: float, subsidence_rate_mm_per_hr: float,
             env: Environment, rssi: int = -80, snr_db: float = 8.0,
             extra_vibration_mg: float = 0.0,
             vibration_peak_hz: int | None = None) -> Telemetry:
        """Produce one telemetry frame for this node at this instant."""
        d_temp = env.temperature_c - self.reference_temp_c

        # --- tilt (LIS3DH) --------------------------------------------------
        # Ground movement is a gradient in mm/m; the accelerometer sees an angle.
        true_pitch = math.degrees(math.atan(tilt_x_mm_per_m / 1000.0)) * 1000.0
        true_roll = math.degrees(math.atan(tilt_y_mm_per_m / 1000.0)) * 1000.0

        self.bias_pitch_mdeg += self.rng.normal(0, self.noise.tilt_random_walk_mdeg)
        self.bias_roll_mdeg += self.rng.normal(0, self.noise.tilt_random_walk_mdeg)

        pitch = (self.install_pitch_mdeg + true_pitch + self.bias_pitch_mdeg
                 + d_temp * self.noise.tilt_drift_mdeg_per_degc
                 + self.rng.normal(0, self.noise.tilt_noise_mdeg))
        roll = (self.install_roll_mdeg + true_roll + self.bias_roll_mdeg
                + d_temp * self.noise.tilt_drift_mdeg_per_degc * 0.6
                + self.rng.normal(0, self.noise.tilt_noise_mdeg))

        if self.tilt_fault:      # stuck axis -- reports its last install offset
            pitch, roll = float(self.install_pitch_mdeg), float(self.install_roll_mdeg)

        # --- displacement (VL53L1X to the reference post) --------------------
        # Strain is a fractional length change, so the ranger sees baseline*strain.
        tof = (self.ref_post_distance_mm * (1.0 + strain_mm_per_m / 1000.0)
               + d_temp * self.noise.tof_drift_mm_per_degc
               + self.rng.normal(0, self.noise.tof_noise_mm))
        if self.tof_fault:
            tof = 0.0            # VL53L1X reports 0 on a failed ranging attempt

        # --- crack gauge -----------------------------------------------------
        crack_ohm_raw = self._crack_resistance(strain_mm_per_m)

        # --- vibration (LIS3DH high-rate FIFO) -------------------------------
        # Active subsidence generates continuous micro-seismic noise; the louder
        # transients (blasting, vehicles) are injected by the caller.
        settlement_mg = 3.0 * abs(subsidence_rate_mm_per_hr)
        vib = (self.noise.vib_ambient_mg
               + abs(self.rng.normal(0, self.noise.vib_ambient_sigma_mg))
               + settlement_mg + extra_vibration_mg)
        if env.rain:
            vib += abs(self.rng.normal(0, 6.0))
        if vibration_peak_hz is None:
            # Ground settlement concentrates energy low; ambient sits higher.
            vibration_peak_hz = int(self.rng.uniform(6, 14) if settlement_mg > 5
                                    else self.rng.uniform(18, 55))

        # --- battery ---------------------------------------------------------
        vbat = self._battery(env)

        flags = 0
        if self.tilt_fault:
            flags |= TLM_TILT_FAULT
        if self.tof_fault:
            flags |= TLM_TOF_FAULT
        if self.crack_fault:
            flags |= TLM_CRACK_FAULT
        if not self.calibrated:
            flags |= TLM_UNCALIBRATED
        if vbat < 3500:
            flags |= TLM_LOW_BATTERY

        return Telemetry(
            t_epoch=int(t_epoch),
            pitch_mdeg=_clamp_i16(pitch),
            roll_mdeg=_clamp_i16(roll),
            vib_rms_mg=_clamp_u16(vib),
            vib_peak_hz=_clamp_u16(vibration_peak_hz),
            tof_mm=_clamp_u16(tof),
            crack_ohm=crack_ohm_raw,
            vbat_mv=_clamp_u16(vbat),
            rssi=int(max(-128, min(127, rssi))),
            snr=_clamp_u8((snr_db + 20.0) * 4.0),
            flags=flags,
        )

    # -------------------------------------------------------------- internals
    def _crack_resistance(self, strain_mm_per_m: float) -> int:
        """Gauge resistance in units of 10 ohm (the wire format's scaling).

        A bonded resistive gauge is flat until the ground goes into tension past
        its threshold, then climbs steeply as micro-cracks propagate through the
        conductive film, and finally goes open-circuit when the crack parts it.
        Compression does not open a crack, so negative strain reads nominal.
        """
        if self.crack_fault:
            return 0
        n = self.noise
        if self.crack_fractured:
            return 65535
        excess = strain_mm_per_m - n.crack_strain_threshold_mm_per_m
        ohms = n.crack_nominal_ohm
        if excess > 0:
            ohms += n.crack_gain * (excess ** n.crack_exponent)
            if excess > 8.0:               # the gauge physically tears
                self.crack_fractured = True
                return 65535
        ohms *= 1.0 + self.rng.normal(0, n.crack_noise_fraction)
        return _clamp_u16(ohms / 10.0)

    def _battery(self, env: Environment) -> float:
        """18650 + small solar panel. Charges by day, drains slowly at night."""
        self.soc += 0.004 * env.solar_fraction - 0.0012
        self.soc = float(np.clip(self.soc, 0.05, 1.0))
        # Li-ion terminal voltage: ~3.3 V empty to ~4.2 V full, mildly non-linear.
        volts = 3300.0 + 900.0 * (self.soc ** 0.75)
        return volts + self.rng.normal(0, self.noise.vbat_noise_mv)

    # ------------------------------------------------------------ fault injection
    def inject_fault(self, kind: str) -> None:
        """Force a sensor fault, so the demo can show graceful degradation."""
        match kind:
            case "tilt":
                self.tilt_fault = True
            case "tof":
                self.tof_fault = True
            case "crack":
                self.crack_fault = True
            case "uncalibrated":
                self.calibrated = False
            case _:
                raise ValueError(f"unknown fault kind: {kind!r}")


def _clamp_i16(v: float) -> int:
    return int(max(-32768, min(32767, round(v))))


def _clamp_u16(v: float) -> int:
    return int(max(0, min(65535, round(v))))


def _clamp_u8(v: float) -> int:
    return int(max(0, min(255, round(v))))
