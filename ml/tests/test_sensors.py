"""Tests for the sensor error model.

The point of these is that the corruption is *real*: thermal drift that mimics
ground movement, and a GNSS receiver three orders of magnitude too coarse to see
subsidence. If the simulator were cleaner than the hardware, every model trained
on it would be over-optimistic.
"""

from __future__ import annotations

import numpy as np
import pytest

from subnet_proto import (
    GNSS_FIX_3D,
    GNSS_NO_FIX,
    TLM_GNSS_FAULT,
    TLM_LOW_BATTERY,
    TLM_TILT_FAULT,
    TLM_UNCALIBRATED,
    TLM_VIB_FAULT,
)
from simulator.sensors import Environment, NodeSensorModel, NoiseProfile


def make(seed: int = 0, **kw) -> NodeSensorModel:
    return NodeSensorModel(addr=0x10, rng=np.random.default_rng(seed), **kw)


def quiet_read(model: NodeSensorModel, env: Environment, **kw):
    defaults = dict(t_epoch=0, tilt_x_mm_per_m=0.0, tilt_y_mm_per_m=0.0,
                    subsidence_rate_mm_per_hr=0.0, env=env)
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


class TestTemperature:
    """The temperature channel exists for exactly one job: undoing tilt drift."""

    def test_reports_the_ambient_it_was_read_at(self):
        m = make(4, noise=NoiseProfile(temp_noise_c=0.0))
        assert quiet_read(m, Environment(temperature_c=31.5)).temp_c == pytest.approx(31.5)

    def test_sub_zero_temperatures_survive_the_signed_field(self):
        """Winter night shifts exist; an unsigned field would read +327 degC."""
        m = make(5, noise=NoiseProfile(temp_noise_c=0.0))
        assert quiet_read(m, Environment(temperature_c=-4.5)).temp_c == pytest.approx(-4.5)

    def test_thermal_drift_masquerades_as_ground_movement(self):
        """The failure this whole channel exists to prevent.

        A 15 degC swing with no ground movement at all shifts apparent tilt by
        several times the sensor noise. Uncorrected, that is a false alarm every
        afternoon -- and a system that cries wolf daily gets switched off.
        """
        m = make(20, noise=NoiseProfile(tilt_noise_mdeg=0.0, tilt_random_walk_mdeg=0.0,
                                        temp_noise_c=0.0))
        cool = quiet_read(m, Environment(temperature_c=m.reference_temp_c))
        hot = quiet_read(m, Environment(temperature_c=m.reference_temp_c + 15.0))
        apparent = abs(hot.pitch_mdeg - cool.pitch_mdeg)
        assert apparent > 5 * NoiseProfile().tilt_noise_mdeg

    def test_reported_temperature_corrects_the_drift_away(self):
        """And the fix: subtract the drift the reported temperature implies."""
        n = NoiseProfile(tilt_noise_mdeg=0.0, tilt_random_walk_mdeg=0.0, temp_noise_c=0.0)
        m = make(21, noise=n)
        ref = m.reference_temp_c
        cool = quiet_read(m, Environment(temperature_c=ref))
        hot = quiet_read(m, Environment(temperature_c=ref + 15.0))

        def corrected(t):
            return t.pitch_mdeg - (t.temp_c - ref) * n.tilt_drift_mdeg_per_degc

        assert corrected(hot) == pytest.approx(corrected(cool), abs=1.0)

    def test_correction_residual_stays_under_the_tilt_noise(self):
        """With a realistically noisy temperature reading the correction is still
        worth doing: what is left over is smaller than the tilt noise itself."""
        n = NoiseProfile(tilt_noise_mdeg=0.0, tilt_random_walk_mdeg=0.0, temp_noise_c=0.5)
        m = make(22, noise=n)
        ref = m.reference_temp_c
        residuals = []
        for _ in range(200):
            t = quiet_read(m, Environment(temperature_c=ref + 15.0))
            residuals.append(t.pitch_mdeg - (t.temp_c - ref) * n.tilt_drift_mdeg_per_degc
                             - m.install_pitch_mdeg)
        assert np.std(residuals) < NoiseProfile().tilt_noise_mdeg


class TestGnss:
    def test_reports_fix_quality_and_satellite_count(self):
        t = quiet_read(make(30), Environment())
        assert t.gnss_fix == GNSS_FIX_3D
        assert 4 <= t.gnss_sats <= 20

    def test_faulted_receiver_reports_no_fix_and_flags(self):
        m = make(31)
        m.inject_fault("gnss")
        t = quiet_read(m, Environment())
        assert t.gnss_fix == GNSS_NO_FIX
        assert t.gnss_sats == 0
        assert t.flags & TLM_GNSS_FAULT

    def test_cannot_see_subsidence_scale_movement(self):
        """The honest limitation, asserted rather than hand-waved.

        Subsidence moves a node millimetres horizontally. A NEO-6M's own noise is
        metres. Any claim that this hardware measures subsidence would be false,
        so the model must not accidentally make it look true.
        """
        m = make(32, lat=23.75, lon=86.42)
        still = [m.position(0) for _ in range(60)]
        moved = [m.position(0, disp_east_m=0.010) for _ in range(60)]   # 10 mm
        spread = np.std([p.lat_e7 for p in still])
        shift = abs(np.mean([p.lon_e7 for p in moved])
                    - np.mean([p.lon_e7 for p in still]))
        assert shift < spread          # the signal is lost inside the noise

    def test_can_see_a_collapse(self):
        """What it *is* good for: a node that has physically moved metres."""
        m = make(33, lat=23.75, lon=86.42)
        base = np.mean([m.position(0).lat_e7 for _ in range(40)])
        after = np.mean([m.position(0, disp_north_m=30.0).lat_e7 for _ in range(40)])
        moved_m = (after - base) / 1e7 * 111_320
        assert moved_m == pytest.approx(30.0, abs=3.0)

    def test_accuracy_estimate_is_reported_honestly(self):
        p = make(34, lat=23.75, lon=86.42).position(0)
        assert p.h_acc_m == pytest.approx(NoiseProfile().gnss_sigma_m, abs=0.01)


class TestSampleCount:
    def test_sample_count_is_reported(self):
        """The server divides by sqrt(n) to know this reading's noise."""
        assert quiet_read(make(40), Environment(), n_samples=64).n_samples == 64

    def test_sample_count_saturates_at_the_byte_limit(self):
        assert quiet_read(make(41), Environment(), n_samples=9999).n_samples == 255


class TestVibration:
    def test_faulted_sensor_reads_zero_and_flags(self):
        m = make(15)
        m.inject_fault("vib")
        t = quiet_read(m, Environment(), extra_vibration_mg=400.0)
        assert t.vib_rms_mg == 0
        assert t.flags & TLM_VIB_FAULT

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

        m = make(25, lat=23.75, lon=86.42)
        for temp in (-10.0, 0.0, 28.0, 55.0):
            for tilt in (-500.0, 0.0, 500.0):
                t = m.read(t_epoch=1_767_225_600, tilt_x_mm_per_m=tilt,
                           tilt_y_mm_per_m=-tilt,
                           subsidence_rate_mm_per_hr=5.0, n_samples=64,
                           env=Environment(temperature_c=temp),
                           extra_vibration_mg=900.0)
                _, decoded = decode(t.frame(src=m.addr, seq=1))
                assert decoded == t

    def test_position_reports_survive_a_round_trip(self):
        from subnet_proto import decode

        m = make(26, lat=-23.75, lon=86.42)
        for east, north in ((0.0, 0.0), (250.0, -250.0), (-1000.0, 1000.0)):
            pos = m.position(1_767_225_600, disp_east_m=east, disp_north_m=north)
            _, decoded = decode(pos.frame(src=m.addr, seq=1))
            assert decoded == pos
