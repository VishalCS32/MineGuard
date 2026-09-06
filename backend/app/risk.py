"""Risk scoring and damage classification.

Deliberately server-side. The web dashboard and the Android app must never be
able to disagree about whether a node is in trouble, so the judgement is made
once, here, and both clients render the same answer. It also means thresholds
can be retuned without shipping new apps.

Damage bands follow the NCB-style structural criteria keyed on horizontal
strain, which is the vocabulary mine planners and regulators already use.
"""

from __future__ import annotations

from dataclasses import dataclass

# Ordered least to most severe; index doubles as the numeric severity.
RISK_BANDS = ("low", "medium", "high", "critical")

DAMAGE_ORDER = ("negligible", "slight", "appreciable", "severe", "very_severe")
_DAMAGE_THRESHOLDS = ((0.5, "negligible"), (1.5, "slight"), (3.0, "appreciable"), (6.0, "severe"))

# Crack width in mm is read off tensile strain over the gauge's bonded length.
_CRACK_MM_PER_STRAIN = 0.35
_CRACK_STRAIN_ONSET = 1.0


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


@dataclass(frozen=True, slots=True)
class Thresholds:
    tilt_deg: float
    crack_mm: float
    vibration_mg: float


@dataclass(frozen=True, slots=True)
class Assessment:
    score: float
    band: str
    damage_class: str
    tilt_deg: float
    crack_mm: float
    strain_mm_per_m: float


def assess(*, pitch_mdeg: int, roll_mdeg: int, vib_rms_mg: int, crack_ohm: int,
           thresholds: Thresholds,
           baseline_pitch_mdeg: int = 0, baseline_roll_mdeg: int = 0) -> Assessment:
    """Score one telemetry frame.

    Tilt is taken *relative to the commissioning baseline*: nodes are hand-planted
    on uneven ground, so absolute tilt says more about how the post was hammered
    in than about ground movement. Subtracting the baseline is what turns a raw
    reading into a deformation measurement.
    """
    d_pitch = (pitch_mdeg - baseline_pitch_mdeg) / 1000.0
    d_roll = (roll_mdeg - baseline_roll_mdeg) / 1000.0
    tilt_deg = (d_pitch ** 2 + d_roll ** 2) ** 0.5
    tilt_mm_per_m = tilt_deg * 1000.0 * 3.14159265 / 180.0

    # Crack gauge: resistance above its nominal 1 kOhm indicates tensile opening.
    ohms = crack_ohm * 10.0
    strain = max(0.0, (ohms - 1000.0) / 900.0) ** (1 / 1.6) + _CRACK_STRAIN_ONSET \
        if ohms > 1000.0 else 0.0
    crack_mm = max(0.0, (strain - _CRACK_STRAIN_ONSET)) * _CRACK_MM_PER_STRAIN

    score = min(
        1.0,
        max(tilt_deg / thresholds.tilt_deg, crack_mm / thresholds.crack_mm) * 0.92
        + min(vib_rms_mg / thresholds.vibration_mg, 1.0) * 0.08,
    )
    return Assessment(
        score=score,
        band=band(score),
        damage_class=classify_damage(strain, tilt_mm_per_m),
        tilt_deg=tilt_deg,
        crack_mm=crack_mm,
        strain_mm_per_m=strain,
    )
