"""Risk scoring and damage classification.

Deliberately server-side. The web dashboard and the Android app must never be
able to disagree about whether a node is in trouble, so the judgement is made
once, here, and both clients render the same answer. It also means thresholds
can be retuned without shipping new apps.

Damage bands follow the NCB-style structural criteria keyed on horizontal
strain, which is the vocabulary mine planners and regulators already use.

What the node measures, and what it does not
--------------------------------------------
A node carries an IMU, a vibration sensor and a GNSS receiver. It measures
*tilt*, and it measures it well. It does not measure strain, displacement or
subsidence, because it has no crack gauge and no ranger. Those come from
``deformation.py``, which reconstructs them from the tilt of the whole array --
so strain arrives here as an argument, already estimated, and may be absent.

That shapes the scoring. Three signals carry the judgement:

    tilt        directly measured, per node, every frame
    tilt rate   the precursor. Ground that is accelerating is failing, and rate
                crosses a threshold well before absolute tilt does
    strain      reconstructed across the array; the NCB damage bands need it

and vibration contributes a small corroborating term, as it always did.
"""

from __future__ import annotations

from dataclasses import dataclass

# Ordered least to most severe; index doubles as the numeric severity.
RISK_BANDS = ("low", "medium", "high", "critical")

DAMAGE_ORDER = ("negligible", "slight", "appreciable", "severe", "very_severe")
_DAMAGE_THRESHOLDS = ((0.5, "negligible"), (1.5, "slight"), (3.0, "appreciable"), (6.0, "severe"))

#: Apparent tilt added per degree C by thermal expansion of the mounting post.
#: This is the largest single error in the whole chain -- over a 15 degC day it
#: produces several times the sensor's own noise, and unlike noise it does not
#: average away. It is a property of how the post is built, so a commissioning
#: thermal soak should measure it per node; this is the design default.
TILT_DRIFT_MDEG_PER_C = 18.0


def classify_damage(strain_mm_per_m: float, tilt_mm_per_m: float = 0.0) -> str:
    """Damage band from strain magnitude, escalated one step by disruptive tilt.

    Compression damages structures too, so magnitude is what is banded; tilt
    above 10 mm/m independently disrupts services, drainage and rail, and lifts
    the classification without ever lowering it.
    """
    magnitude = abs(strain_mm_per_m)
    damage = DAMAGE_ORDER[-1]
    for limit, label in _DAMAGE_THRESHOLDS:
        if magnitude < limit:
            damage = label
            break
    if tilt_mm_per_m > 10.0:
        damage = DAMAGE_ORDER[min(DAMAGE_ORDER.index(damage) + 1, len(DAMAGE_ORDER) - 1)]
    return damage


def band(score: float) -> str:
    if score < 0.35:
        return "low"
    if score < 0.60:
        return "medium"
    if score < 0.85:
        return "high"
    return "critical"


def severity_of(band_name: str) -> int:
    return RISK_BANDS.index(band_name)


def corrected_tilt_mdeg(raw_mdeg: int, baseline_mdeg: int, temp_c: float | None,
                        baseline_temp_c: float | None,
                        drift_mdeg_per_c: float = TILT_DRIFT_MDEG_PER_C) -> float:
    """Tilt relative to commissioning, with thermal drift removed.

    Two corrections, and both are necessary:

    *Baseline* -- a node is hand-planted on uneven ground, so its raw attitude
    mostly describes how the post was hammered in. Subtracting the commissioning
    attitude is what turns a reading into a deformation measurement.

    *Temperature* -- the post expands and contracts, swinging apparent tilt by
    far more than the sensor's noise across a single day. Left in, it produces a
    false alarm every afternoon and a system nobody trusts. Removed, what is left
    is ground movement. When no temperature is available the correction is
    skipped rather than guessed, because a wrong correction is worse than none.
    """
    tilt = float(raw_mdeg - baseline_mdeg)
    if temp_c is not None and baseline_temp_c is not None:
        tilt -= (temp_c - baseline_temp_c) * drift_mdeg_per_c
    return tilt


@dataclass(frozen=True, slots=True)
class Thresholds:
    tilt_deg: float
    strain_mm_per_m: float
    vibration_mg: float
    #: Degrees per hour. Tighter than the node's own trigger, because the server
    #: has the temperature correction and a longer baseline to measure against.
    tilt_rate_deg_per_h: float = 0.05


@dataclass(frozen=True, slots=True)
class Assessment:
    score: float
    band: str
    damage_class: str
    tilt_deg: float
    tilt_rate_deg_per_h: float
    strain_mm_per_m: float
    #: False when the array could not support a strain estimate for this node.
    #: The damage class is then based on tilt alone and is a floor, not a verdict.
    strain_valid: bool


def assess(*, pitch_mdeg: int, roll_mdeg: int, vib_rms_mg: int,
           thresholds: Thresholds,
           baseline_pitch_mdeg: int = 0, baseline_roll_mdeg: int = 0,
           temp_c: float | None = None, baseline_temp_c: float | None = None,
           tilt_rate_deg_per_h: float = 0.0,
           strain_mm_per_m: float = 0.0, strain_valid: bool = False,
           drift_mdeg_per_c: float = TILT_DRIFT_MDEG_PER_C) -> Assessment:
    """Score one node's current state.

    ``strain_mm_per_m`` comes from ``deformation.estimate_field`` over the whole
    array, not from this node. When it is unavailable the score falls back to
    tilt, tilt rate and vibration -- which still detects movement, but cannot
    put a defensible NCB damage class on it.
    """
    d_pitch = corrected_tilt_mdeg(pitch_mdeg, baseline_pitch_mdeg,
                                  temp_c, baseline_temp_c, drift_mdeg_per_c) / 1000.0
    d_roll = corrected_tilt_mdeg(roll_mdeg, baseline_roll_mdeg,
                                 temp_c, baseline_temp_c, drift_mdeg_per_c) / 1000.0
    tilt_deg = (d_pitch ** 2 + d_roll ** 2) ** 0.5
    tilt_mm_per_m = tilt_deg * 1000.0 * 3.14159265 / 180.0

    # The governing term is whichever criterion is closest to its limit. Summing
    # them would let two comfortable readings average away one dangerous one.
    governing = max(
        tilt_deg / thresholds.tilt_deg,
        abs(tilt_rate_deg_per_h) / thresholds.tilt_rate_deg_per_h,
        (abs(strain_mm_per_m) / thresholds.strain_mm_per_m) if strain_valid else 0.0,
    )
    score = min(1.0, governing * 0.90
                + min(vib_rms_mg / thresholds.vibration_mg, 1.0) * 0.10)

    return Assessment(
        score=score,
        band=band(score),
        damage_class=classify_damage(strain_mm_per_m if strain_valid else 0.0,
                                     tilt_mm_per_m),
        tilt_deg=tilt_deg,
        tilt_rate_deg_per_h=tilt_rate_deg_per_h,
        strain_mm_per_m=strain_mm_per_m if strain_valid else 0.0,
        strain_valid=strain_valid,
    )
