"""Turn ground movement into what the hardware actually reports.

The physics module says how the ground moves. This module says what an ESP32-S3
with a LIS3DH, a vibration sensor and a NEO-6M would *measure* -- which is a
different and much messier thing: every reading carries installation offsets,
thermal drift, quantisation and noise. Training a model on clean physics and
deploying it against noisy hardware is the classic way to build a system that
demos well and fails in the field, so the corruption here is deliberate and
calibrated to real datasheets.

The node measures tilt, vibration and position. It does *not* measure strain or
displacement -- there is no crack gauge and no ranger. Those are reconstructed
from the tilt field across the array (``strain = B * dT/dx``), which is why the
noise figures below matter so much: the server differentiates this signal, and
differentiation amplifies noise.

Datasheet-derived noise figures
-------------------------------
LIS3DH   +/-2 g, 12-bit -> ~1 mg/LSB -> ~0.06 deg tilt resolution. With on-node
         averaging over a sample window we take ~0.05 deg (50 mdeg) 1-sigma.
LIS3DH   die temperature: coarse, ~0.5 degC 1-sigma after averaging. Good enough,
temp     because it only has to track the *change* that drives post expansion.
NEO-6M   ~2.5 m CEP horizontal. Three orders of magnitude away from a subsidence
         signal, and the model must never let it look otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from subnet_proto import (
    GNSS_FIX_2D,
    GNSS_FIX_3D,
    GNSS_NO_FIX,
    TLM_GNSS_FAULT,
    TLM_LOW_BATTERY,
    TLM_TILT_FAULT,
    TLM_UNCALIBRATED,
    TLM_VIB_FAULT,
    Position,
    Telemetry,
    pack_gnss_status,
)

from .field import local_to_wgs84

__all__ = ["NoiseProfile", "Environment", "NodeSensorModel"]


@dataclass(frozen=True, slots=True)
class NoiseProfile:
    """Sensor error budget. Defaults follow the datasheets above."""

    tilt_noise_mdeg: float = 50.0            # LIS3DH, averaged
    tilt_drift_mdeg_per_degc: float = 18.0   # thermal expansion of the mounting post
    tilt_random_walk_mdeg: float = 2.0       # slow bias wander per sample
    vib_ambient_mg: float = 12.0             # wind, distant plant, background
    vib_ambient_sigma_mg: float = 4.0
    vbat_noise_mv: float = 8.0
    #: LIS3DH die temperature, after on-node averaging. It does not need to be
    #: accurate in absolute terms -- only to track the change that drives the
    #: mounting post's thermal expansion, which is what the server subtracts.
    temp_noise_c: float = 0.5
    #: NEO-6M horizontal CEP. Deliberately large: it is what makes GNSS useless
    #: for subsidence and useful for detecting a node that has physically moved.
    gnss_sigma_m: float = 2.5


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
    reference_temp_c: float = 28.0
    #: True position, from the commissioning survey. GNSS reports this + noise.
    lat: float = 0.0
    lon: float = 0.0
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
    vib_fault: bool = False
    gnss_fault: bool = False
    calibrated: bool = True

    def __post_init__(self) -> None:
        # Nodes are hand-planted on uneven ground: a degree or so of install tilt
        # is normal. Deformation is always measured *relative* to this baseline.
        if self.install_pitch_mdeg == 0 and self.install_roll_mdeg == 0:
            self.install_pitch_mdeg = int(self.rng.normal(0, 900))
            self.install_roll_mdeg = int(self.rng.normal(0, 900))

    # ------------------------------------------------------------------ read
    def read(self, *, t_epoch: int, tilt_x_mm_per_m: float, tilt_y_mm_per_m: float,
             subsidence_rate_mm_per_hr: float,
             env: Environment, rssi: int = -80, snr_db: float = 8.0,
             extra_vibration_mg: float = 0.0, n_samples: int = 32,
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

        # --- die temperature (LIS3DH) ----------------------------------------
        # Reported so the server can undo the drift term added to tilt above.
        # It is the same temperature that caused the drift, which is the whole
        # point: an ambient reading from elsewhere on site would not correlate
        # with this post's expansion and would correct nothing.
        temp_measured = env.temperature_c + self.rng.normal(0, self.noise.temp_noise_c)

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
        if self.vib_fault:
            vib, vibration_peak_hz = 0.0, 0

        # --- battery ---------------------------------------------------------
        vbat = self._battery(env)

        flags = 0
        if self.tilt_fault:
            flags |= TLM_TILT_FAULT
        if self.vib_fault:
            flags |= TLM_VIB_FAULT
        if self.gnss_fault:
            flags |= TLM_GNSS_FAULT
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
            temp_c_x100=_clamp_i16(temp_measured * 100.0),
            n_samples=_clamp_u8(n_samples),
            gnss_status=self._gnss_status(),
            vbat_mv=_clamp_u16(vbat),
            rssi=int(max(-128, min(127, rssi))),
            snr=_clamp_u8((snr_db + 20.0) * 4.0),
            flags=flags,
        )

    # -------------------------------------------------------------- internals
    def _gnss_status(self) -> int:
        """Fix quality and satellite count, as the NEO-6M would report them."""
        if self.gnss_fault:
            return pack_gnss_status(GNSS_NO_FIX, 0)
        sats = int(np.clip(self.rng.normal(9, 2), 0, 20))
        fix = GNSS_FIX_3D if sats >= 4 else (GNSS_FIX_2D if sats == 3 else GNSS_NO_FIX)
        return pack_gnss_status(fix, sats)

    def position(self, t_epoch: int, *, disp_east_m: float = 0.0,
                 disp_north_m: float = 0.0) -> Position:
        """One GNSS report.

        ``disp_*`` is the node's *true* horizontal movement in metres. Ordinary
        subsidence produces millimetres of it, so it vanishes under the 2.5 m
        noise -- correctly, because a NEO-6M genuinely cannot see subsidence. A
        collapse or a theft moves the node metres, and that does show up.
        """
        east = disp_east_m + self.rng.normal(0, self.noise.gnss_sigma_m)
        north = disp_north_m + self.rng.normal(0, self.noise.gnss_sigma_m)
        lat, lon = local_to_wgs84(self.lat, self.lon, east, north)
        return Position(
            t_epoch=int(t_epoch),
            lat_e7=int(round(lat * 1e7)),
            lon_e7=int(round(lon * 1e7)),
            alt_m=0,
            h_acc_cm=_clamp_u16(self.noise.gnss_sigma_m * 100.0),
            gnss_status=self._gnss_status(),
        )

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
            case "vib":
                self.vib_fault = True
            case "gnss":
                self.gnss_fault = True
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
