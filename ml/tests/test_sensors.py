"""Tests for the sensor error model.

The point of these is that the corruption is *real*: thermal drift that mimics
ground movement, a crack gauge that ignores compression, a ToF ranger whose signal
is barely above its own noise. If the simulator were cleaner than the hardware,
every model trained on it would be over-optimistic.
"""

from __future__ import annotations

import numpy as np
import pytest

from subnet_proto import (
    TLM_CRACK_FAULT,
    TLM_LOW_BATTERY,
    TLM_TILT_FAULT,
    TLM_TOF_FAULT,
    TLM_UNCALIBRATED,
)
from simulator.sensors import Environment, NodeSensorModel, NoiseProfile


def make(seed: int = 0, **kw) -> NodeSensorModel:
    return NodeSensorModel(addr=0x10, rng=np.random.default_rng(seed), **kw)


def quiet_read(model: NodeSensorModel, env: Environment, **kw):
    defaults = dict(t_epoch=0, tilt_x_mm_per_m=0.0, tilt_y_mm_per_m=0.0,
                    strain_mm_per_m=0.0, subsidence_rate_mm_per_hr=0.0, env=env)
    return model.read(**{**defaults, **kw})


class TestEnvironment:
    def test_hottest_mid_afternoon_coldest_before_dawn(self):
        assert Environment.at_hour(15).temperature_c > Environment.at_hour(3).temperature_c

    def test_no_sun_at_night(self):
        assert Environment.at_hour(2).solar_fraction == 0.0
        assert Environment.at_hour(23).solar_fraction == 0.0

    def test_sun_peaks_at_midday(self):
        assert Environment.at_hour(12).solar_fraction == pytest.approx(1.0, abs=1e-9)


class TestTilt:
    def test_install_offset_is_applied(self):
        """Nodes are planted on uneven ground; deformation is relative to that."""
        m = make(3)
        m.install_pitch_mdeg, m.install_roll_mdeg = 1500, -800
        t = quiet_read(m, Environment(temperature_c=m.reference_temp_c))
        assert t.pitch_mdeg == pytest.approx(1500, abs=250)
        assert t.roll_mdeg == pytest.approx(-800, abs=250)

    def test_ground_tilt_moves_the_reading(self):
        m = make(5)
        m.install_pitch_mdeg = m.install_roll_mdeg = 0
        env = Environment(temperature_c=m.reference_temp_c)
        flat = quiet_read(m, env).pitch_mdeg
        tilted = quiet_read(m, env, tilt_x_mm_per_m=20.0).pitch_mdeg
        # 20 mm/m ~ 1.146 deg ~ 1146 mdeg
        assert tilted - flat == pytest.approx(1146, abs=200)

    def test_thermal_drift_mimics_ground_movement(self):
        """The core false-positive risk: a hot afternoon looks like a tilting node."""
        m = make(11, noise=NoiseProfile(tilt_noise_mdeg=0.0, tilt_random_walk_mdeg=0.0))
        m.install_pitch_mdeg = m.install_roll_mdeg = 0
        cold = quiet_read(m, Environment(temperature_c=20.0)).pitch_mdeg
        hot = quiet_read(m, Environment(temperature_c=38.0)).pitch_mdeg
        assert hot - cold == pytest.approx(18 * 18.0, abs=1)   # dT * drift coefficient
        assert abs(hot - cold) > 300      # comparable to real early-stage movement

    def test_stuck_sensor_reports_install_offset_and_flags(self):
        m = make(7)
        m.inject_fault("tilt")
        t = quiet_read(m, Environment(), tilt_x_mm_per_m=50.0)
        assert t.flags & TLM_TILT_FAULT
        assert t.pitch_mdeg == m.install_pitch_mdeg

    def test_extreme_tilt_is_clamped_not_wrapped(self):
        """A wrapped int16 would read as a huge tilt of the opposite sign."""
        m = make(2)
        t = quiet_read(m, Environment(), tilt_x_mm_per_m=1e9)
        assert t.pitch_mdeg == 32767


class TestDisplacement:
    def test_tof_tracks_strain_over_the_baseline(self):
        m = make(4, noise=NoiseProfile(tof_noise_mm=0.0, tof_drift_mm_per_degc=0.0))
        env = Environment(temperature_c=m.reference_temp_c)
        base = quiet_read(m, env).tof_mm
        # 4 mm/m of tension over a 2500 mm baseline is a 10 mm opening.
        stretched = quiet_read(m, env, strain_mm_per_m=4.0).tof_mm
        assert stretched - base == pytest.approx(10, abs=1)

    def test_tof_signal_is_marginal_against_its_own_noise(self):
        """Honest limitation: at realistic strains ToF is a corroborating signal,
        not a primary one. Tilt carries the detection."""
        m = make(6)
        env = Environment(temperature_c=m.reference_temp_c)
        signal = 2500 * (1.0 / 1000.0)          # 1 mm/m of strain -> 2.5 mm
        assert signal < 1.0 * m.noise.tof_noise_mm * 1.5

    def test_failed_ranging_reports_zero_and_flags(self):
        m = make(8)
        m.inject_fault("tof")
        t = quiet_read(m, Environment(), strain_mm_per_m=5.0)
        assert t.tof_mm == 0
        assert t.flags & TLM_TOF_FAULT


class TestCrackGauge:
    def test_flat_below_the_cracking_threshold(self):
        m = make(9)
        env = Environment(temperature_c=m.reference_temp_c)
        low = quiet_read(m, env, strain_mm_per_m=0.5).crack_ohms
        assert low == pytest.approx(1000.0, rel=0.05)

    def test_compression_does_not_open_a_crack(self):
        """Ground squeezed together cannot part a bonded gauge."""
        m = make(10)
        env = Environment(temperature_c=m.reference_temp_c)
        assert quiet_read(m, env, strain_mm_per_m=-6.0).crack_ohms == pytest.approx(
            1000.0, rel=0.05)

    def test_resistance_climbs_with_tension(self):
        m = make(12)
        env = Environment(temperature_c=m.reference_temp_c)
        series = [quiet_read(m, env, strain_mm_per_m=s).crack_ohms
                  for s in (2.0, 3.0, 5.0, 7.0)]
        assert all(b > a for a, b in zip(series, series[1:]))

    def test_gauge_tears_permanently_at_extreme_strain(self):
        m = make(13)
        env = Environment(temperature_c=m.reference_temp_c)
        assert quiet_read(m, env, strain_mm_per_m=12.0).crack_ohm == 65535
        # Once parted it stays parted, even if the ground relaxes.
        assert m.crack_fractured
        assert quiet_read(m, env, strain_mm_per_m=0.0).crack_ohm == 65535

    def test_faulted_gauge_reads_zero_and_flags(self):
        m = make(14)
        m.inject_fault("crack")
        t = quiet_read(m, Environment(), strain_mm_per_m=5.0)
        assert t.crack_ohm == 0
        assert t.flags & TLM_CRACK_FAULT


class TestVibration:
    def test_ambient_floor_when_nothing_is_happening(self):
        m = make(15)
        vals = [quiet_read(m, Environment()).vib_rms_mg for _ in range(50)]
        assert 5 < np.mean(vals) < 40

    def test_settlement_raises_the_floor(self):
        m = make(16)
        env = Environment()
        quiet = np.mean([quiet_read(m, env).vib_rms_mg for _ in range(30)])
        active = np.mean([quiet_read(m, env, subsidence_rate_mm_per_hr=20.0).vib_rms_mg
                          for _ in range(30)])
        assert active > quiet + 30

    def test_injected_transient_dominates(self):
        m = make(17)
        t = quiet_read(m, Environment(), extra_vibration_mg=600.0)
        assert t.vib_rms_mg > 550

    def test_settlement_energy_is_low_frequency(self):
        """Roof failure radiates low; ambient and traffic sit higher."""
        m = make(18)
        env = Environment()
        settling = [quiet_read(m, env, subsidence_rate_mm_per_hr=30.0).vib_peak_hz
                    for _ in range(30)]
        ambient = [quiet_read(m, env).vib_peak_hz for _ in range(30)]
        assert np.mean(settling) < np.mean(ambient)


class TestBattery:
    def test_charges_during_the_day(self):
        m = make(19)
        m.soc = 0.5
        for _ in range(20):
            quiet_read(m, Environment(solar_fraction=1.0))
        assert m.soc > 0.5

    def test_drains_overnight(self):
        m = make(20)
        m.soc = 0.5
        for _ in range(20):
            quiet_read(m, Environment(solar_fraction=0.0))
        assert m.soc < 0.5

    def test_low_battery_flag_raised(self):
        m = make(21)
        m.soc = 0.05
        t = quiet_read(m, Environment())
        assert t.vbat_mv < 3500
        assert t.flags & TLM_LOW_BATTERY

    def test_soc_never_leaves_physical_range(self):
        m = make(22)
        for _ in range(500):
            quiet_read(m, Environment(solar_fraction=1.0))
        assert m.soc <= 1.0
        for _ in range(3000):
            quiet_read(m, Environment(solar_fraction=0.0))
        assert m.soc >= 0.05


class TestFaultInjection:
    def test_uncalibrated_flag(self):
        m = make(23)
        m.inject_fault("uncalibrated")
        assert quiet_read(m, Environment()).flags & TLM_UNCALIBRATED

    def test_unknown_fault_rejected(self):
        with pytest.raises(ValueError, match="unknown fault kind"):
            make(24).inject_fault("gremlins")


class TestWireFormatSafety:
    def test_every_reading_survives_a_protocol_round_trip(self):
        """Whatever the sensor model emits must fit the wire format -- otherwise
        the simulator can produce frames the real radio never could."""
        from subnet_proto import decode

        m = make(25)
        for strain in (-8.0, 0.0, 3.0, 15.0):
            for tilt in (-500.0, 0.0, 500.0):
                t = m.read(t_epoch=1_767_225_600, tilt_x_mm_per_m=tilt,
                           tilt_y_mm_per_m=-tilt, strain_mm_per_m=strain,
                           subsidence_rate_mm_per_hr=5.0,
                           env=Environment.at_hour(14), extra_vibration_mg=900.0)
                _, decoded = decode(t.frame(src=m.addr, seq=1))
                assert decoded == t
