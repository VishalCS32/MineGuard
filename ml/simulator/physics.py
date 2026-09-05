"""Ground-subsidence physics over a longwall panel.

Implements the *influence-function* (Knothe) method, the standard analytical model
for surface movement above underground extraction. Everything the AI is trained on
comes out of here, which is why this module is pure, analytic and heavily tested:
if the physics is wrong the model learns a fiction.

Theory
------
Extraction of an element of the seam draws down an area of surface described by the
Knothe influence function, a Gaussian of radius ``r``:

    f(x) = (1/r) * exp(-pi * x^2 / r^2)          r = H / tan(beta)

with ``H`` the seam depth and ``beta`` the angle of draw. Integrating that over a
semi-infinite extraction gives a complementary-error-function profile, so for a
panel extracted over ``[x1, x2]``:

    S(x) / S_max = 0.5 * [ erfc(k*(x - x2)) - erfc(k*(x - x1)) ],   k = sqrt(pi)/r

For a rectangular panel the 2-D surface is the product of the two 1-D profiles.
Maximum possible subsidence is ``S_max = a * m`` for subsidence factor ``a`` and
extraction thickness ``m``.

Derived quantities (these are what the sensors actually see):
    tilt        T = dS/dx                    -> what LIS3DH measures
    curvature   K = d2S/dx2
    horiz disp  U = B * T                    -> what the ToF ranger measures
    strain      e = dU/dx = B * K            -> what the crack gauge measures

with ``B ~ 0.4 * H``. Sign convention follows the field: strain is compressive at
the trough centre and tensile at the rim, which is exactly why cracks open at the
panel edges and why an edge node is the earliest warning you get.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.special import erfc

__all__ = ["PanelGeometry", "SurfaceMovement", "SubsidenceModel", "DamageClass",
           "classify_damage"]


@dataclass(frozen=True, slots=True)
class PanelGeometry:
    """Extraction panel in local metric coordinates (metres, x east / y north).

    Defaults are representative of Indian longwall practice (moderate depth,
    ~3 m extraction height, Indian coalfield subsidence factors).
    """

    x_start: float = 0.0          # panel extent along the direction of face advance
    x_end: float = 600.0
    y_min: float = -150.0         # panel half-width across the face
    y_max: float = 150.0
    seam_depth_m: float = 150.0           # H
    extraction_thickness_m: float = 3.0   # m
    subsidence_factor: float = 0.65       # a
    angle_of_draw_deg: float = 35.0       # beta
    horizontal_disp_factor: float = 0.4   # B, as a multiple of H

    def __post_init__(self) -> None:
        if self.x_end <= self.x_start or self.y_max <= self.y_min:
            raise ValueError("panel must have positive extent in both axes")
        if not 0 < self.subsidence_factor <= 1:
            raise ValueError("subsidence factor must be in (0, 1]")
        if not 0 < self.angle_of_draw_deg < 90:
            raise ValueError("angle of draw must be in (0, 90) degrees")
        if self.seam_depth_m <= 0 or self.extraction_thickness_m <= 0:
            raise ValueError("depth and extraction thickness must be positive")

    @property
    def s_max_m(self) -> float:
        """Maximum possible subsidence for a fully critical panel, in metres."""
        return self.subsidence_factor * self.extraction_thickness_m

    @property
    def radius_of_influence_m(self) -> float:
        """r = H / tan(beta) -- how far beyond the panel edge movement reaches."""
        return self.seam_depth_m / math.tan(math.radians(self.angle_of_draw_deg))

    @property
    def critical_width_m(self) -> float:
        """Panel width below which full S_max never develops (subcritical)."""
        return 2.0 * self.radius_of_influence_m

    @property
    def b_coefficient_m(self) -> float:
        """B, relating tilt to horizontal displacement."""
        return self.horizontal_disp_factor * self.seam_depth_m

    @property
    def is_subcritical(self) -> bool:
        return (self.y_max - self.y_min) < self.critical_width_m


@dataclass(slots=True)
class SurfaceMovement:
    """Complete surface-movement state at a set of points. All arrays same shape.

    Units are the ones engineers and damage criteria actually use:
    subsidence in mm, tilt in mm/m, strain in mm/m, curvature in 1/km.
    """

    subsidence_mm: np.ndarray
    tilt_x_mm_per_m: np.ndarray
    tilt_y_mm_per_m: np.ndarray
    strain_x_mm_per_m: np.ndarray
    strain_y_mm_per_m: np.ndarray
    disp_x_mm: np.ndarray
    disp_y_mm: np.ndarray

    @property
    def tilt_mm_per_m(self) -> np.ndarray:
        """Resultant tilt magnitude -- the quantity damage criteria are stated in."""
        return np.hypot(self.tilt_x_mm_per_m, self.tilt_y_mm_per_m)

    @property
    def tilt_deg(self) -> np.ndarray:
        """Tilt as an angle, which is what an accelerometer reports."""
        return np.degrees(np.arctan(self.tilt_mm_per_m / 1000.0))

    @property
    def strain_mm_per_m(self) -> np.ndarray:
        """Signed governing strain: whichever axis has the largest magnitude.

        Sign is retained deliberately -- tensile (+) opens cracks, compressive (-)
        buckles them shut, and they are not interchangeable for damage assessment.
        """
        take_x = np.abs(self.strain_x_mm_per_m) >= np.abs(self.strain_y_mm_per_m)
        return np.where(take_x, self.strain_x_mm_per_m, self.strain_y_mm_per_m)


class SubsidenceModel:
    """Analytic subsidence surface above an advancing longwall face.

    The face position advances with time, so ``at_time()`` gives the evolving
    trough that the sensor field would actually experience.
    """

    def __init__(self, panel: PanelGeometry, time_coefficient_per_day: float = 0.35):
        """``time_coefficient_per_day`` is Knothe's c: surface movement lags the
        face, approaching its final value as ``1 - exp(-c*t)``. Lower c means a
        slower, more drawn-out settlement.
        """
        if time_coefficient_per_day <= 0:
            raise ValueError("time coefficient must be positive")
        self.panel = panel
        self.c = time_coefficient_per_day
        self._r = panel.radius_of_influence_m
        self._k = math.sqrt(math.pi) / self._r

    # ------------------------------------------------------------ 1-D profile
    def _profile(self, u: np.ndarray, a: float, b: float) -> np.ndarray:
        """Fraction of S_max from extraction spanning [a, b] along one axis."""
        return 0.5 * (erfc(self._k * (u - b)) - erfc(self._k * (u - a)))

    def _profile_d1(self, u: np.ndarray, a: float, b: float) -> np.ndarray:
        """d/du of ``_profile`` -- the difference of two influence functions."""
        inv_r = 1.0 / self._r
        return inv_r * (np.exp(-math.pi * (u - a) ** 2 / self._r**2)
                        - np.exp(-math.pi * (u - b) ** 2 / self._r**2))

    def _profile_d2(self, u: np.ndarray, a: float, b: float) -> np.ndarray:
        """d2/du2 of ``_profile``."""
        coef = 2.0 * math.pi / self._r**3
        return coef * ((u - b) * np.exp(-math.pi * (u - b) ** 2 / self._r**2)
                       - (u - a) * np.exp(-math.pi * (u - a) ** 2 / self._r**2))

    # -------------------------------------------------------------- evaluate
    def face_position(self, days: float) -> float:
        """Where the working face has reached after ``days`` of advance."""
        raise NotImplementedError  # face advance is supplied by the caller

    def evaluate(self, x: np.ndarray, y: np.ndarray, face_x: float,
                 completion: float = 1.0) -> SurfaceMovement:
        """Surface movement at points (x, y) for a face that has reached ``face_x``.

        ``completion`` in [0, 1] scales the whole field to model the time lag
        between extraction and the surface finishing its settlement.
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if x.shape != y.shape:
            raise ValueError(f"x and y must share a shape, got {x.shape} and {y.shape}")
        if not 0.0 <= completion <= 1.0:
            raise ValueError("completion must be in [0, 1]")

        p = self.panel
        x2 = float(np.clip(face_x, p.x_start, p.x_end))
        s_max_mm = p.s_max_m * 1000.0 * completion

        if x2 <= p.x_start:  # nothing extracted yet -- undisturbed ground
            zeros = np.zeros_like(x)
            return SurfaceMovement(zeros, zeros.copy(), zeros.copy(), zeros.copy(),
                                   zeros.copy(), zeros.copy(), zeros.copy())

        fx = self._profile(x, p.x_start, x2)
        fy = self._profile(y, p.y_min, p.y_max)
        dfx = self._profile_d1(x, p.x_start, x2)
        dfy = self._profile_d1(y, p.y_min, p.y_max)
        d2fx = self._profile_d2(x, p.x_start, x2)
        d2fy = self._profile_d2(y, p.y_min, p.y_max)

        subsidence_mm = s_max_mm * fx * fy
        # Tilt in mm/m: dS/dx with S in mm and x in m.
        tilt_x = s_max_mm * dfx * fy
        tilt_y = s_max_mm * fx * dfy
        # Horizontal displacement U = B * tilt; strain is its gradient.
        b = p.b_coefficient_m
        disp_x = b * tilt_x
        disp_y = b * tilt_y
        strain_x = b * s_max_mm * d2fx * fy
        strain_y = b * s_max_mm * fx * d2fy

        return SurfaceMovement(subsidence_mm, tilt_x, tilt_y,
                               strain_x, strain_y, disp_x, disp_y)


# ------------------------------------------------------------ damage classes
class DamageClass:
    """NCB-style structural damage bands, keyed on tensile strain in mm/m.

    These are the thresholds a mine planner and a regulator already work in, so
    the system's output lands in familiar units instead of an opaque score.
    """

    NEGLIGIBLE = "negligible"
    SLIGHT = "slight"
    APPRECIABLE = "appreciable"
    SEVERE = "severe"
    VERY_SEVERE = "very_severe"

    ORDER = [NEGLIGIBLE, SLIGHT, APPRECIABLE, SEVERE, VERY_SEVERE]
    # (upper bound of tensile strain in mm/m, class)
    THRESHOLDS = [(0.5, NEGLIGIBLE), (1.5, SLIGHT), (3.0, APPRECIABLE), (6.0, SEVERE)]
    SEVERITY = {NEGLIGIBLE: 0, SLIGHT: 1, APPRECIABLE: 2, SEVERE: 3, VERY_SEVERE: 3}


def classify_damage(strain_mm_per_m: float, tilt_mm_per_m: float = 0.0) -> str:
    """Damage band from strain, with tilt able to escalate but never de-escalate.

    Compressive strain damages structures too, so magnitude is what is banded;
    tilt above 10 mm/m is independently disruptive (services, drainage, rail) and
    lifts the classification by one band.
    """
    magnitude = abs(strain_mm_per_m)
    damage = DamageClass.VERY_SEVERE
    for limit, label in DamageClass.THRESHOLDS:
        if magnitude < limit:
            damage = label
            break

    if tilt_mm_per_m > 10.0:
        idx = DamageClass.ORDER.index(damage)
        damage = DamageClass.ORDER[min(idx + 1, len(DamageClass.ORDER) - 1)]
    return damage
