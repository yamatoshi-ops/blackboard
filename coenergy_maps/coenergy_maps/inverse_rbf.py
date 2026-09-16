"""RBF primitives extracted from code_flux/inverse_fit.py; no runtime parent import."""
from dataclasses import dataclass, field
import numpy as np
from scipy.interpolate import RBFInterpolator

def _target_normalization(
    values: np.ndarray,
    ddof: int,
) -> tuple[float, float]:
    mean = float(np.mean(values))
    scale = float(np.std(values, ddof=ddof))
    if not np.isfinite([mean, scale]).all() or scale <= 0.0:
        raise ValueError("inverse-fit target cannot be normalized")
    return mean, scale


def _fit_rbf(
    points_normalized: np.ndarray,
    targets_normalized: np.ndarray,
    smoothing: float,
) -> RBFInterpolator:
    return RBFInterpolator(
        points_normalized,
        targets_normalized,
        kernel="thin_plate_spline",
        smoothing=float(smoothing),
        degree=1,
    )


@dataclass(frozen=True)
class InverseComponentFit:
    """Normalized direct inverse RBF for one current component."""

    component: str
    input_mean_Wb: np.ndarray
    input_scale_Wb: np.ndarray
    target_mean_A: float
    target_scale_A: float
    smoothing: float
    rbf: RBFInterpolator = field(repr=False, compare=False)
    enforce_zero_q_boundary: bool = False

    def __call__(self, psi_d_Wb: object, psi_q_Wb: object) -> np.ndarray:
        try:
            psi_d, psi_q = np.broadcast_arrays(
                np.asarray(psi_d_Wb, dtype=float),
                np.asarray(psi_q_Wb, dtype=float),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "direct inverse query must be numeric and broadcastable"
            ) from error
        if not np.isfinite(psi_d).all() or not np.isfinite(psi_q).all():
            raise ValueError("direct inverse query must be finite")
        query = np.column_stack([psi_d.ravel(), psi_q.ravel()])
        normalized = (query - self.input_mean_Wb) / self.input_scale_Wb
        values = (
            np.asarray(self.rbf(normalized), dtype=float).reshape(-1)
            * self.target_scale_A
            + self.target_mean_A
        ).reshape(psi_d.shape)
        if self.enforce_zero_q_boundary:
            values = np.where(psi_q == 0.0, 0.0, values)
        if not np.isfinite(values).all():
            raise ValueError(
                f"direct inverse {self.component} evaluation produced nonfinite values"
            )
        return values
