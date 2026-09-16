"""Constrained co-energy forward fit used by the DEN E1 validation track.

This module is deliberately independent of the production forward-fit path.
It accepts only a normalized point-field contract and fully explicit basis,
quadrature, and solver settings.  In particular, it contains no master-data
adapter and no data-dependent defaults for knots, scales, regularization, or
solver tolerances.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any

import numpy as np
from scipy import linalg, sparse
from scipy.interpolate import BSpline
from scipy.sparse.linalg import lsmr


DEGREE = 3
SUPPORTED_SOLVERS = ("dense_gelsd", "sparse_lsmr")
COEFFICIENT_ORDER = "u-major/v-minor"


class CoenergyFitError(ValueError):
    """Raised when the explicit E1 fit contract cannot be satisfied."""

    def __init__(self, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class CoenergySamples:
    """Source-independent gradient observations for one co-energy fit.

    ``component_mask`` and legacy ``component_weight`` have shape ``(n, 2)``
    with component order ``(d, q)``.  A masked component is not read and its
    target may therefore be NaN; every enabled component must have a finite
    target and a strictly positive weight.

    The optional ``component_weight_matrix`` has shape ``(n, 2, 2)`` and acts
    on the normalized residual ``[e_d, e_q] / psi_base``.  It is mutually
    exclusive with ``component_weight`` and requires both components at every
    observation.  ``None`` preserves the legacy path bit-for-bit.
    """

    id_A: object
    iq_A: object
    psi_d_Wb: object
    psi_q_Wb: object
    component_mask: object
    component_weight: object
    component_weight_matrix: object | None = None


@dataclass(frozen=True)
class CoenergyFitSpec:
    """Fully explicit basis and solver settings for an E1 fit."""

    i_base_A: float
    psi_base_Wb: float
    u_breakpoints: object
    v_breakpoints: object
    solver: str
    roughness_weight: float
    solver_tolerance: float | None
    solver_max_iterations: int | None
    active_basis_tolerance: float
    rank_tolerance: float | None
    ridge_weight: float = 0.0


@dataclass(frozen=True)
class CoenergyQuadratures:
    """Fixed-domain quadrature contracts in dimensionless coordinates."""

    support_u: object
    support_v: object
    span_u: object
    span_v: object
    span_weight: object
    gauge_u: object
    gauge_v: object
    gauge_weight: object
    roughness_u: object
    roughness_v: object
    roughness_weight: object


@dataclass(frozen=True)
class CoenergyEvaluation:
    """Co-energy, flux, and analytic differential inductance evaluation."""

    coenergy_J: Any
    psi_d_Wb: Any
    psi_q_Wb: Any
    l_dd_H: Any
    l_dq_H: Any
    l_qd_H: Any
    l_qq_H: Any


@dataclass(frozen=True)
class CoenergyModel:
    """Fitted dimensionless co-energy model with exact q-axis extension."""

    i_base_A: float
    psi_base_Wb: float
    u_knots: np.ndarray
    v_knots: np.ndarray
    low_order_coefficients: np.ndarray
    sat_coefficients: np.ndarray
    sat_raw_transform: np.ndarray = field(repr=False)
    gauge_offset_bar: float
    degree: int = DEGREE

    def evaluate(self, id_A: object, iq_A: object) -> CoenergyEvaluation:
        """Evaluate W, its gradient, and Hessian with even/odd q extension."""

        (id_values, iq_values), shape = _broadcast(id_A, iq_A)
        u = id_values.reshape(-1) / self.i_base_A
        v_signed = iq_values.reshape(-1) / self.i_base_A
        v = np.abs(v_signed)
        _check_domain(u, self.u_knots, self.degree, "Id/I_base")
        _check_domain(v, self.v_knots, self.degree, "abs(Iq/I_base)")

        sign_q = np.sign(v_signed)
        raw_c = self.sat_raw_transform @ self.sat_coefficients
        a1, a2, a3 = self.low_order_coefficients

        b00 = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 0, 0
        )
        b10 = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 1, 0
        )
        b01 = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 0, 1
        )
        b20 = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 2, 0
        )
        b11 = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 1, 1
        )
        b02 = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 0, 2
        )

        bar_w = (
            a1 * u
            + 0.5 * a2 * u * u
            + 0.5 * a3 * v * v
            + b00 @ raw_c
            - self.gauge_offset_bar
        )
        bar_psi_d = a1 + a2 * u + b10 @ raw_c
        bar_psi_q = sign_q * (a3 * v + b01 @ raw_c)
        inductance_scale = self.psi_base_Wb / self.i_base_A
        l_dd = inductance_scale * (a2 + b20 @ raw_c)
        l_dq = inductance_scale * sign_q * (b11 @ raw_c)
        l_qd = np.array(l_dq, copy=True)
        l_qq = inductance_scale * (a3 + b02 @ raw_c)

        return CoenergyEvaluation(
            coenergy_J=_restore(
                self.i_base_A * self.psi_base_Wb * bar_w, shape
            ),
            psi_d_Wb=_restore(self.psi_base_Wb * bar_psi_d, shape),
            psi_q_Wb=_restore(self.psi_base_Wb * bar_psi_q, shape),
            l_dd_H=_restore(l_dd, shape),
            l_dq_H=_restore(l_dq, shape),
            l_qd_H=_restore(l_qd, shape),
            l_qq_H=_restore(l_qq, shape),
        )

    def raw_sat_coefficients(self) -> np.ndarray:
        """Return a read-only copy in documented u-major/v-minor order."""

        values = np.array(
            self.sat_raw_transform @ self.sat_coefficients,
            dtype=float,
            copy=True,
        )
        values.flags.writeable = False
        return values

    def parameter_vector(self) -> np.ndarray:
        """Return the fitted normalized parameter vector as a read-only copy.

        The first three entries are the low-order ``(a1, a2, a3)`` terms and
        the remainder are the saturation coefficients in the model's reduced
        basis.  This is the coefficient order used by
        :meth:`normalized_flux_parameter_design`.
        """

        values = np.concatenate(
            [self.low_order_coefficients, self.sat_coefficients]
        ).astype(float, copy=False)
        values = np.array(values, dtype=float, copy=True)
        values.flags.writeable = False
        return values

    def normalized_flux_parameter_design(
        self, id_A: object, iq_A: object
    ) -> np.ndarray:
        """Return the linear design mapping parameters to ``psi/Psi_base``.

        The returned shape is ``broadcast(Id, Iq).shape + (2, p)`` with
        component order ``(d, q)``.  It exposes the exact fitted basis needed
        for sparse-anchor rank, leverage, and prediction-uncertainty analysis;
        it does not evaluate or accept target flux values.
        """

        (id_values, iq_values), shape = _broadcast(id_A, iq_A)
        u = id_values.reshape(-1) / self.i_base_A
        v_signed = iq_values.reshape(-1) / self.i_base_A
        v = np.abs(v_signed)
        _check_domain(u, self.u_knots, self.degree, "Id/I_base")
        _check_domain(v, self.v_knots, self.degree, "abs(Iq/I_base)")

        sign_q = np.sign(v_signed)
        raw_du = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 1, 0
        )
        raw_dv = _tensor_basis(
            self.u_knots, self.v_knots, self.degree, u, v, 0, 1
        )
        sat_du = raw_du @ self.sat_raw_transform
        sat_dv = sign_q[:, np.newaxis] * (
            raw_dv @ self.sat_raw_transform
        )
        design_d = np.column_stack(
            [np.ones(len(u)), u, np.zeros(len(u)), sat_du]
        )
        design_q = np.column_stack(
            [np.zeros(len(u)), np.zeros(len(u)), v_signed, sat_dv]
        )
        design = np.stack([design_d, design_q], axis=1).reshape(
            shape + (2, design_d.shape[1])
        )
        design.flags.writeable = False
        return design


@dataclass(frozen=True)
class CoenergyFitResult:
    model: CoenergyModel
    prediction_psi_d_Wb: np.ndarray
    prediction_psi_q_Wb: np.ndarray
    residual_psi_d_Wb: np.ndarray
    residual_psi_q_Wb: np.ndarray
    metrics: dict[str, Any]
    numerical_diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoenergyFullBasisCensus:
    """Pre-pruning, unregularized rank census for CAP0."""

    total_basis_count: int
    symmetry_tied_basis_count: int
    exact_constraint_count: int
    zero_support_basis_count: int
    low_order_projection_rank: int
    low_order_projection_residual_norm: float
    low_order_projection_matrix_sha256: str
    data_design_rank: int
    data_nullity_before_regularization: int
    singular_values: np.ndarray
    smallest_nonzero_singular_value: float | None
    condition_number_nonzero_subspace: float | None
    data_design_matrix_sha256: str
    numerical_diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoenergySystemDiagnostics:
    """Opt-in §4.6 diagnostics kept outside legacy fit metrics."""

    effective_degrees_of_freedom: float
    active_support_graph_component_count: int
    active_basis_count: int
    zero_support_basis_count: int
    low_order_projection_residual_norm: float
    data_smallest_nonzero_singular_value: float | None
    data_condition_number_nonzero_subspace: float | None
    system_smallest_nonzero_singular_value: float | None
    system_condition_number_nonzero_subspace: float | None
    numerical_diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ValidatedSamples:
    id_A: np.ndarray
    iq_A: np.ndarray
    psi_d_Wb: np.ndarray
    psi_q_Wb: np.ndarray
    mask: np.ndarray
    weight: np.ndarray | None
    weight_matrix: np.ndarray | None


@dataclass(frozen=True)
class _ValidatedQuadratures:
    support_u: np.ndarray
    support_v: np.ndarray
    span_u: np.ndarray
    span_v: np.ndarray
    span_weight: np.ndarray
    gauge_u: np.ndarray
    gauge_v: np.ndarray
    gauge_weight: np.ndarray
    roughness_u: np.ndarray
    roughness_v: np.ndarray
    roughness_weight: np.ndarray


def _broadcast(*values: object) -> tuple[list[np.ndarray], tuple[int, ...]]:
    try:
        arrays = [np.asarray(value, dtype=float) for value in values]
        arrays = list(np.broadcast_arrays(*arrays))
    except (TypeError, ValueError) as error:
        raise CoenergyFitError(
            "co-energy query values must be numeric and broadcastable"
        ) from error
    if not all(np.isfinite(value).all() for value in arrays):
        raise CoenergyFitError("co-energy query values must be finite")
    return arrays, arrays[0].shape


def _restore(values: object, shape: tuple[int, ...]) -> Any:
    array = np.asarray(values, dtype=float).reshape(shape)
    return float(array) if shape == () else array


def _numeric_vector(value: object, name: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError) as error:
        raise CoenergyFitError(f"{name} must be numeric") from error
    return array


def _finite_vector(value: object, name: str, *, nonempty: bool = True) -> np.ndarray:
    array = _numeric_vector(value, name)
    if nonempty and not len(array):
        raise CoenergyFitError(f"{name} must not be empty")
    if not np.isfinite(array).all():
        raise CoenergyFitError(f"{name} must contain only finite values")
    return array


def _positive_scalar(value: object, name: str, *, allow_zero: bool = False) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise CoenergyFitError(f"{name} must be numeric") from error
    valid = converted >= 0.0 if allow_zero else converted > 0.0
    if not np.isfinite(converted) or not valid:
        qualifier = "nonnegative" if allow_zero else "positive"
        raise CoenergyFitError(f"{name} must be finite and {qualifier}")
    return converted


def _validated_breakpoints(value: object, name: str) -> np.ndarray:
    points = _finite_vector(value, name)
    if len(points) < 2 or not np.all(np.diff(points) > 0.0):
        raise CoenergyFitError(
            f"{name} must contain at least two strictly increasing values"
        )
    return points


def _open_clamped_knots(breakpoints: np.ndarray) -> np.ndarray:
    return np.concatenate(
        [
            np.repeat(breakpoints[0], DEGREE + 1),
            breakpoints[1:-1],
            np.repeat(breakpoints[-1], DEGREE + 1),
        ]
    )


def _basis_count(knots: np.ndarray, degree: int) -> int:
    return len(knots) - degree - 1


def _bspline_basis(
    knots: np.ndarray,
    degree: int,
    x: np.ndarray,
    derivative: int,
) -> np.ndarray:
    coefficients = np.eye(_basis_count(knots, degree), dtype=float)
    values = BSpline(
        knots,
        coefficients,
        degree,
        extrapolate=False,
        axis=0,
    )(x, nu=derivative)
    result = np.asarray(values, dtype=float).reshape(len(x), -1)
    if not np.isfinite(result).all():
        raise CoenergyFitError("B-spline evaluation produced nonfinite values")
    return result


def _tensor_basis(
    u_knots: np.ndarray,
    v_knots: np.ndarray,
    degree: int,
    u: np.ndarray,
    v: np.ndarray,
    derivative_u: int,
    derivative_v: int,
) -> np.ndarray:
    basis_u = _bspline_basis(u_knots, degree, u, derivative_u)
    basis_v = _bspline_basis(v_knots, degree, v, derivative_v)
    # C-order reshape makes the v index vary fastest: u-major/v-minor.
    return (
        basis_u[:, :, np.newaxis] * basis_v[:, np.newaxis, :]
    ).reshape(len(u), -1)


def _check_domain(
    values: np.ndarray,
    knots: np.ndarray,
    degree: int,
    name: str,
) -> None:
    lower = knots[degree]
    upper = knots[-degree - 1]
    tolerance = 32.0 * np.finfo(float).eps * max(1.0, abs(lower), abs(upper))
    invalid = (values < lower - tolerance) | (values > upper + tolerance)
    if invalid.any():
        positions = np.flatnonzero(invalid).tolist()
        raise CoenergyFitError(
            f"{name} is outside the explicit B-spline domain at position(s): "
            f"{positions}"
        )


def _validated_samples(samples: CoenergySamples) -> _ValidatedSamples:
    if not isinstance(samples, CoenergySamples):
        raise CoenergyFitError("samples must be a CoenergySamples instance")
    id_A = _finite_vector(samples.id_A, "samples.id_A")
    iq_A = _finite_vector(samples.iq_A, "samples.iq_A")
    if len(id_A) != len(iq_A):
        raise CoenergyFitError("samples Id and Iq lengths must match")
    negative_iq = np.flatnonzero(iq_A < 0.0)
    if len(negative_iq):
        raise CoenergyFitError(
            "fit samples must satisfy Iq >= 0; negative-Iq values are generated "
            "only by the model extension contract at position(s): "
            f"{negative_iq.tolist()}"
        )
    psi_d = _numeric_vector(samples.psi_d_Wb, "samples.psi_d_Wb")
    psi_q = _numeric_vector(samples.psi_q_Wb, "samples.psi_q_Wb")
    if len(psi_d) != len(id_A) or len(psi_q) != len(id_A):
        raise CoenergyFitError("sample target lengths must match current lengths")

    raw_mask = np.asarray(samples.component_mask)
    if raw_mask.shape != (len(id_A), 2):
        raise CoenergyFitError("component_mask must have shape (n_samples, 2)")
    if raw_mask.dtype.kind == "b":
        mask = raw_mask.astype(bool, copy=True)
    else:
        try:
            numeric_mask = np.asarray(raw_mask, dtype=float)
        except (TypeError, ValueError) as error:
            raise CoenergyFitError("component_mask must contain booleans or 0/1") from error
        if not np.isin(numeric_mask, (0.0, 1.0)).all():
            raise CoenergyFitError("component_mask must contain booleans or 0/1")
        mask = numeric_mask.astype(bool)
    if not mask.any():
        raise CoenergyFitError("at least one flux component must be enabled")

    targets = np.column_stack([psi_d, psi_q])
    if samples.component_weight_matrix is None:
        try:
            weight = np.asarray(samples.component_weight, dtype=float)
        except (TypeError, ValueError) as error:
            raise CoenergyFitError("component_weight must be numeric") from error
        if weight.shape != (len(id_A), 2):
            raise CoenergyFitError(
                "component_weight must have shape (n_samples, 2)"
            )
        if not np.isfinite(weight).all() or (weight < 0.0).any():
            raise CoenergyFitError(
                "component_weight must be finite and nonnegative"
            )
        if (weight[mask] <= 0.0).any():
            raise CoenergyFitError("enabled component weights must be positive")
        if not np.isfinite(targets[mask]).all():
            raise CoenergyFitError("enabled flux targets must be finite")
        return _ValidatedSamples(
            id_A, iq_A, psi_d, psi_q, mask, weight, None
        )

    if samples.component_weight is not None:
        raise CoenergyFitError(
            "component_weight and component_weight_matrix are mutually exclusive"
        )
    if not mask.all():
        raise CoenergyFitError(
            "component_weight_matrix requires both flux components enabled "
            "at every observation"
        )
    try:
        weight_matrix = np.asarray(
            samples.component_weight_matrix, dtype=float
        )
    except (TypeError, ValueError) as error:
        raise CoenergyFitError(
            "component_weight_matrix must be numeric"
        ) from error
    if weight_matrix.shape != (len(id_A), 2, 2):
        raise CoenergyFitError(
            "component_weight_matrix must have shape (n_samples, 2, 2)"
        )
    if not np.isfinite(weight_matrix).all():
        raise CoenergyFitError("component_weight_matrix must be finite")
    if not np.array_equal(weight_matrix, np.swapaxes(weight_matrix, 1, 2)):
        raise CoenergyFitError(
            "component_weight_matrix must be exactly symmetric"
        )
    eigenvalues = np.linalg.eigvalsh(weight_matrix)
    scale = np.maximum(
        1.0, np.max(np.abs(weight_matrix), axis=(1, 2))
    )
    psd_tolerance = 64.0 * np.finfo(float).eps * scale
    invalid_psd = np.flatnonzero(
        np.min(eigenvalues, axis=1) < -psd_tolerance
    )
    if len(invalid_psd):
        raise CoenergyFitError(
            "component_weight_matrix must be positive semidefinite at "
            f"observation position(s): {invalid_psd.tolist()}"
        )
    if not np.isfinite(targets).all():
        raise CoenergyFitError(
            "matrix-weighted flux targets must be finite"
        )
    return _ValidatedSamples(
        id_A,
        iq_A,
        psi_d,
        psi_q,
        mask,
        None,
        weight_matrix,
    )


def _validated_spec(
    spec: CoenergyFitSpec,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    if not isinstance(spec, CoenergyFitSpec):
        raise CoenergyFitError("spec must be a CoenergyFitSpec instance")
    i_base = _positive_scalar(spec.i_base_A, "spec.i_base_A")
    psi_base = _positive_scalar(spec.psi_base_Wb, "spec.psi_base_Wb")
    u_breakpoints = _validated_breakpoints(
        spec.u_breakpoints, "spec.u_breakpoints"
    )
    v_breakpoints = _validated_breakpoints(
        spec.v_breakpoints, "spec.v_breakpoints"
    )
    if v_breakpoints[0] != 0.0 or (v_breakpoints < 0.0).any():
        raise CoenergyFitError(
            "spec.v_breakpoints must start at exactly zero and be nonnegative"
        )
    if spec.solver not in SUPPORTED_SOLVERS:
        raise CoenergyFitError(
            "spec.solver must be one of: " + ", ".join(SUPPORTED_SOLVERS)
        )
    _positive_scalar(
        spec.roughness_weight, "spec.roughness_weight", allow_zero=True
    )
    _positive_scalar(spec.ridge_weight, "spec.ridge_weight", allow_zero=True)
    _positive_scalar(
        spec.active_basis_tolerance, "spec.active_basis_tolerance"
    )
    if spec.rank_tolerance is not None:
        _positive_scalar(spec.rank_tolerance, "spec.rank_tolerance")
    if spec.solver == "sparse_lsmr":
        if spec.solver_tolerance is None:
            raise CoenergyFitError(
                "sparse_lsmr requires an explicit solver_tolerance"
            )
        _positive_scalar(spec.solver_tolerance, "spec.solver_tolerance")
        if (
            isinstance(spec.solver_max_iterations, bool)
            or not isinstance(spec.solver_max_iterations, (int, np.integer))
            or int(spec.solver_max_iterations) <= 0
        ):
            raise CoenergyFitError(
                "sparse_lsmr requires positive integer solver_max_iterations"
            )
    elif spec.solver_tolerance is not None or spec.solver_max_iterations is not None:
        raise CoenergyFitError(
            "dense_gelsd does not accept sparse solver tolerance settings"
        )
    return i_base, psi_base, u_breakpoints, v_breakpoints


def _validated_quadrature_block(
    u_value: object,
    v_value: object,
    weight_value: object,
    name: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    u = _finite_vector(u_value, f"quadratures.{name}_u")
    v = _finite_vector(v_value, f"quadratures.{name}_v")
    weight = _finite_vector(weight_value, f"quadratures.{name}_weight")
    if len(v) != len(u) or len(weight) != len(u):
        raise CoenergyFitError(f"{name} quadrature vector lengths must match")
    if (v < 0.0).any():
        raise CoenergyFitError(f"{name} quadrature v must be nonnegative")
    if (weight <= 0.0).any():
        raise CoenergyFitError(f"{name} quadrature weights must be positive")
    return u, v, weight


def _validated_quadratures(
    quadratures: CoenergyQuadratures,
) -> _ValidatedQuadratures:
    if not isinstance(quadratures, CoenergyQuadratures):
        raise CoenergyFitError(
            "quadratures must be a CoenergyQuadratures instance"
        )
    support_u = _finite_vector(
        quadratures.support_u, "quadratures.support_u"
    )
    support_v = _finite_vector(
        quadratures.support_v, "quadratures.support_v"
    )
    if len(support_v) != len(support_u):
        raise CoenergyFitError("support probe vector lengths must match")
    if (support_v < 0.0).any():
        raise CoenergyFitError("support probe v must be nonnegative")
    span = _validated_quadrature_block(
        quadratures.span_u,
        quadratures.span_v,
        quadratures.span_weight,
        "span",
    )
    gauge = _validated_quadrature_block(
        quadratures.gauge_u,
        quadratures.gauge_v,
        quadratures.gauge_weight,
        "gauge",
    )
    roughness = _validated_quadrature_block(
        quadratures.roughness_u,
        quadratures.roughness_v,
        quadratures.roughness_weight,
        "roughness",
    )
    return _ValidatedQuadratures(
        support_u,
        support_v,
        *span,
        *gauge,
        *roughness,
    )


def _q_neumann_elimination(n_u: int, n_v: int) -> np.ndarray:
    """Map free coefficients to raw coefficients with c[u,0] == c[u,1]."""

    if n_v < 2:
        raise CoenergyFitError("q-axis Neumann elimination requires two v bases")
    transform = np.zeros((n_u * n_v, n_u * (n_v - 1)), dtype=float)
    for u_index in range(n_u):
        raw = u_index * n_v
        free = u_index * (n_v - 1)
        transform[raw, free] = 1.0
        transform[raw + 1, free] = 1.0
        for v_index in range(2, n_v):
            transform[raw + v_index, free + v_index - 1] = 1.0
    return transform


def _rank_from_singular_values(
    singular_values: np.ndarray,
    shape: tuple[int, int],
    relative_tolerance: float | None,
) -> tuple[int, float]:
    if not len(singular_values) or singular_values[0] == 0.0:
        return 0, 0.0
    relative = (
        np.finfo(float).eps * max(shape)
        if relative_tolerance is None
        else float(relative_tolerance)
    )
    cutoff = relative * singular_values[0]
    return int(np.count_nonzero(singular_values > cutoff)), float(cutoff)


def _matrix_rank(
    matrix: np.ndarray,
    relative_tolerance: float | None,
) -> tuple[int, np.ndarray, float]:
    singular_values = linalg.svdvals(matrix)
    rank, cutoff = _rank_from_singular_values(
        singular_values, matrix.shape, relative_tolerance
    )
    return rank, singular_values, cutoff


def _free_variable_nullspace(
    constraints: np.ndarray,
    relative_tolerance: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, float]:
    """Return A@N=0 using pivoted QR and identity free variables."""

    _, _, pivot_order = linalg.qr(
        constraints, mode="economic", pivoting=True, check_finite=True
    )
    rank, _, cutoff = _matrix_rank(constraints, relative_tolerance)
    if rank != constraints.shape[0]:
        raise CoenergyFitError(
            "active B-spline basis cannot enforce all four low-order span "
            f"constraints: rank={rank}, required={constraints.shape[0]}"
        )
    if constraints.shape[1] <= rank:
        raise CoenergyFitError(
            "low-order span removal leaves no saturation basis functions"
        )
    pivot = pivot_order[:rank]
    # QR chooses the dependent columns.  Free columns are deliberately restored
    # to original active-basis order so serialized coefficients are deterministic
    # rather than inheriting an implementation-specific QR tail order.
    free = np.sort(pivot_order[rank:])
    pivot_block = constraints[:, pivot]
    free_block = constraints[:, free]
    relation = -linalg.solve(pivot_block, free_block, assume_a="gen")
    transform = np.zeros((constraints.shape[1], len(free)), dtype=float)
    transform[pivot, :] = relation
    transform[free, :] = np.eye(len(free), dtype=float)
    return transform, pivot, free, rank, cutoff


def _matrix_sha256(matrix: np.ndarray) -> str:
    canonical = np.ascontiguousarray(matrix, dtype="<f8")
    descriptor = json.dumps(
        {"dtype": "float64-le", "shape": list(canonical.shape)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(descriptor + b"\n" + canonical.tobytes()).hexdigest()


def _condition_number(
    singular_values: np.ndarray,
    rank: int,
    column_count: int,
) -> float:
    if not len(singular_values) or rank < column_count:
        return float("inf")
    return float(singular_values[0] / singular_values[-1])


def _json_condition(value: float) -> tuple[float | None, bool]:
    return (float(value), False) if np.isfinite(value) else (None, True)


def _readonly(values: object) -> np.ndarray:
    array = np.array(values, dtype=float, copy=True)
    array.flags.writeable = False
    return array


def _matrix_weighted_rows(
    weight_matrix: np.ndarray,
    design_d: np.ndarray,
    design_q: np.ndarray,
    target_d: np.ndarray,
    target_q: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply principal PSD square roots in legacy d-major/q-major row order."""

    off_diagonal = weight_matrix[:, 0, 1]
    if np.count_nonzero(off_diagonal) == 0:
        diagonal_weight = np.concatenate(
            [weight_matrix[:, 0, 0], weight_matrix[:, 1, 1]]
        )
        sqrt_weight = np.sqrt(np.maximum(diagonal_weight, 0.0))
        data_design = np.vstack([design_d, design_q])
        data_target = np.concatenate([target_d, target_q])
        return (
            sqrt_weight[:, np.newaxis] * data_design,
            sqrt_weight * data_target,
        )

    eigenvalues, eigenvectors = np.linalg.eigh(weight_matrix)
    scale = np.maximum(
        1.0, np.max(np.abs(weight_matrix), axis=(1, 2))
    )
    psd_tolerance = 64.0 * np.finfo(float).eps * scale
    eigenvalues = np.where(
        eigenvalues < 0.0,
        np.where(eigenvalues >= -psd_tolerance[:, np.newaxis], 0.0, eigenvalues),
        eigenvalues,
    )
    roots = np.einsum(
        "nik,nk,njk->nij",
        eigenvectors,
        np.sqrt(eigenvalues),
        eigenvectors,
        optimize=False,
    )
    design_pair = np.stack([design_d, design_q], axis=1)
    target_pair = np.stack([target_d, target_q], axis=1)
    weighted_pair_design = np.einsum(
        "nij,njp->nip", roots, design_pair, optimize=False
    )
    weighted_pair_target = np.einsum(
        "nij,nj->ni", roots, target_pair, optimize=False
    )
    return (
        np.vstack(
            [weighted_pair_design[:, 0, :], weighted_pair_design[:, 1, :]]
        ),
        np.concatenate(
            [weighted_pair_target[:, 0], weighted_pair_target[:, 1]]
        ),
    )


def _analysis_problem(
    samples: CoenergySamples,
    spec: CoenergyFitSpec,
    quadratures: CoenergyQuadratures,
    *,
    prune_inactive: bool,
) -> dict[str, Any]:
    """Shared assembly for fitting, census and target-independent design norms."""

    source = _validated_samples(samples)
    i_base, psi_base, u_breakpoints, v_breakpoints = _validated_spec(spec)
    quad = _validated_quadratures(quadratures)
    u_knots = _open_clamped_knots(u_breakpoints)
    v_knots = _open_clamped_knots(v_breakpoints)
    u = source.id_A / i_base
    v_signed = source.iq_A / i_base
    v = np.abs(v_signed)
    sign_q = np.sign(v_signed)
    for values, knots, name in (
        (u, u_knots, "samples.Id/I_base"),
        (v, v_knots, "samples.abs(Iq/I_base)"),
        (quad.support_u, u_knots, "quadratures.support_u"),
        (quad.support_v, v_knots, "quadratures.support_v"),
        (quad.span_u, u_knots, "quadratures.span_u"),
        (quad.span_v, v_knots, "quadratures.span_v"),
        (quad.gauge_u, u_knots, "quadratures.gauge_u"),
        (quad.gauge_v, v_knots, "quadratures.gauge_v"),
        (quad.roughness_u, u_knots, "quadratures.roughness_u"),
        (quad.roughness_v, v_knots, "quadratures.roughness_v"),
    ):
        _check_domain(values, knots, DEGREE, name)

    n_u = _basis_count(u_knots, DEGREE)
    n_v = _basis_count(v_knots, DEGREE)
    q_transform = _q_neumann_elimination(n_u, n_v)
    raw_du = _tensor_basis(u_knots, v_knots, DEGREE, u, v, 1, 0)
    raw_dv = _tensor_basis(u_knots, v_knots, DEGREE, u, v, 0, 1)
    neumann_du = raw_du @ q_transform
    neumann_dv = sign_q[:, np.newaxis] * (raw_dv @ q_transform)
    observation_basis = np.vstack(
        [neumann_du[source.mask[:, 0]], neumann_dv[source.mask[:, 1]]]
    )
    support_raw = _tensor_basis(
        u_knots,
        v_knots,
        DEGREE,
        quad.support_u,
        quad.support_v,
        0,
        0,
    )
    support = np.maximum(
        np.max(np.abs(observation_basis), axis=0),
        np.max(np.abs(support_raw @ q_transform), axis=0),
    )
    supported_indices = np.flatnonzero(
        support > float(spec.active_basis_tolerance)
    )
    zero_support_indices = np.flatnonzero(
        support <= float(spec.active_basis_tolerance)
    )
    if prune_inactive:
        active_indices = supported_indices
        if not len(active_indices):
            raise CoenergyFitError(
                "no B-spline basis has active gradient support at enabled samples"
            )
    else:
        active_indices = np.arange(q_transform.shape[1], dtype=int)
    inactive_indices = np.setdiff1d(
        np.arange(q_transform.shape[1], dtype=int),
        active_indices,
        assume_unique=True,
    )
    active_transform = q_transform[:, active_indices]

    span_raw = _tensor_basis(
        u_knots, v_knots, DEGREE, quad.span_u, quad.span_v, 0, 0
    )
    span_active = span_raw @ active_transform
    polynomial = np.column_stack(
        [
            np.ones(len(quad.span_u)),
            quad.span_u,
            quad.span_u**2,
            quad.span_v**2,
        ]
    )
    low_order_constraints = polynomial.T @ (
        quad.span_weight[:, np.newaxis] * span_active
    )
    (
        low_order_transform,
        pivot_indices,
        free_indices,
        constraint_rank,
        constraint_cutoff,
    ) = _free_variable_nullspace(
        low_order_constraints, spec.rank_tolerance
    )
    projection_residual = low_order_constraints @ low_order_transform
    sat_raw_transform = active_transform @ low_order_transform
    sat_basis_count = sat_raw_transform.shape[1]
    sat_du = raw_du @ sat_raw_transform
    sat_dv = sign_q[:, np.newaxis] * (raw_dv @ sat_raw_transform)
    trend_d = np.column_stack([np.ones(len(u)), u, np.zeros(len(u))])
    trend_q = np.column_stack(
        [np.zeros(len(u)), np.zeros(len(u)), v_signed]
    )
    design_d = np.column_stack([trend_d, sat_du])
    design_q = np.column_stack([trend_q, sat_dv])
    data_design = np.vstack(
        [design_d[source.mask[:, 0]], design_q[source.mask[:, 1]]]
    )
    data_target = np.concatenate(
        [
            source.psi_d_Wb[source.mask[:, 0]] / psi_base,
            source.psi_q_Wb[source.mask[:, 1]] / psi_base,
        ]
    )
    if source.weight_matrix is None:
        data_weight = np.concatenate(
            [
                source.weight[source.mask[:, 0], 0],
                source.weight[source.mask[:, 1], 1],
            ]
        )
        sqrt_data_weight = np.sqrt(data_weight)
        weighted_data_design = sqrt_data_weight[:, np.newaxis] * data_design
        weighted_data_target = sqrt_data_weight * data_target
    else:
        weighted_data_design, weighted_data_target = _matrix_weighted_rows(
            source.weight_matrix,
            design_d,
            design_q,
            source.psi_d_Wb / psi_base,
            source.psi_q_Wb / psi_base,
        )

    roughness_designs: list[np.ndarray] = []
    penalty_sat_blocks: list[np.ndarray] = []
    system_blocks = [weighted_data_design]
    roughness_value = float(spec.roughness_weight)
    if roughness_value > 0.0:
        for derivative_u, derivative_v, multiplicity in (
            (3, 0, 1.0),
            (2, 1, 3.0),
            (1, 2, 3.0),
            (0, 3, 1.0),
        ):
            raw_derivative = _tensor_basis(
                u_knots,
                v_knots,
                DEGREE,
                quad.roughness_u,
                quad.roughness_v,
                derivative_u,
                derivative_v,
            )
            sat_derivative = raw_derivative @ sat_raw_transform
            roughness_designs.append(sat_derivative)
            scale = np.sqrt(
                roughness_value * multiplicity * quad.roughness_weight
            )
            penalty_sat = scale[:, np.newaxis] * sat_derivative
            penalty_sat_blocks.append(penalty_sat)
            system_blocks.append(
                np.column_stack(
                    [np.zeros((len(scale), 3)), penalty_sat]
                )
            )
    ridge_value = float(spec.ridge_weight)
    if ridge_value > 0.0:
        penalty_sat = np.sqrt(ridge_value) * np.eye(sat_basis_count)
        penalty_sat_blocks.append(penalty_sat)
        system_blocks.append(
            np.column_stack(
                [np.zeros((sat_basis_count, 3)), penalty_sat]
            )
        )
    system_design = np.vstack(system_blocks)
    return {
        "u_breakpoints": u_breakpoints,
        "v_breakpoints": v_breakpoints,
        "u": u,
        "active_transform": active_transform,
        "support": support,
        "polynomial": polynomial,
        "low_order_transform": low_order_transform,
        "pivot_indices": pivot_indices,
        "free_indices": free_indices,
        "constraint_cutoff": constraint_cutoff,
        "roughness_designs": roughness_designs,
        "source": source,
        "i_base": i_base,
        "psi_base": psi_base,
        "quad": quad,
        "u_knots": u_knots,
        "v_knots": v_knots,
        "n_u": n_u,
        "n_v": n_v,
        "q_transform": q_transform,
        "active_indices": active_indices,
        "inactive_indices": inactive_indices,
        "zero_support_indices": zero_support_indices,
        "low_order_constraints": low_order_constraints,
        "constraint_rank": constraint_rank,
        "projection_residual": projection_residual,
        "sat_raw_transform": sat_raw_transform,
        "data_design": data_design,
        "data_target": data_target,
        "weighted_data_design": weighted_data_design,
        "weighted_data_target": weighted_data_target,
        "penalty_sat": (
            np.vstack(penalty_sat_blocks)
            if penalty_sat_blocks
            else np.empty((0, sat_basis_count), dtype=float)
        ),
        "system_design": system_design,
    }


def _relative_residual(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return 0.0 if numerator == 0.0 else float("inf")
    return numerator / denominator


def _numerical_diagnostics(problem, spec, *, data_singular=None, system_singular=None):
    """SVD evidence on the very same assembled matrices, including failed fits.

    Span removal uses ||CZ||_F / (||C||_F ||Z||_F); no refit or change of
    eliminated coordinates is made for the rank-sensitivity calculation.
    """
    result = {
        "raw_basis_count": int(problem["n_u"] * problem["n_v"]),
        "active_indices": problem["active_indices"].tolist(),
        "inactive_indices": problem["inactive_indices"].tolist(),
        "parameter_count": int(problem["system_design"].shape[1]),
        "low_order_span_rank": int(problem["constraint_rank"]),
        "low_order_span_cutoff": float(problem["constraint_cutoff"]),
        "span_relative_residual_definition": "||CZ||_F/(||C||_F*||Z||_F)",
        "span_relative_residual": _relative_residual(
            float(np.linalg.norm(problem["projection_residual"])),
            float(np.linalg.norm(problem["low_order_constraints"]))
            * float(np.linalg.norm(problem["low_order_transform"])),
        ),
    }
    result["span_pass"] = result["span_relative_residual"] <= 1e-12
    for name, matrix, singular in (
        ("data", problem["weighted_data_design"], data_singular),
        ("system", problem["system_design"], system_singular),
    ):
        if singular is None:
            singular = linalg.svdvals(matrix)
        rank, cutoff = _rank_from_singular_values(singular, matrix.shape, spec.rank_tolerance)
        result[name] = {
            "rank": rank, "nullity": matrix.shape[1] - rank,
            "cutoff": cutoff, "singular_values": singular.tolist(),
            "condition_is_infinite": rank < matrix.shape[1],
            "condition_nonzero_subspace": float(singular[0] / singular[rank-1]) if rank else None,
            "rank_sensitivity": {
                str(tol): _rank_from_singular_values(singular, matrix.shape, tol)[0]
                for tol in (1e-13, 1e-11)
            },
        }
    return result


def coenergy_design_norms(
    id_A, iq_A, component_mask, component_weight,
    spec: CoenergyFitSpec, quadratures: CoenergyQuadratures,
) -> dict[str, float | int]:
    """Return ||A||_F² and ||R||_F² using coordinates/weights, never flux targets.

    R contains unit third-derivative roughness and zero trend columns, no ridge.
    Its free-coordinate convention is exactly the one used by the fit solver.
    """
    zeros = np.zeros_like(np.asarray(id_A, dtype=float))
    samples = CoenergySamples(id_A, iq_A, zeros, zeros, component_mask, component_weight)
    problem = _analysis_problem(
        samples, replace(spec, roughness_weight=1.0, ridge_weight=0.0),
        quadratures, prune_inactive=True,
    )
    return {
        "data_frobenius_squared": float(np.sum(problem["weighted_data_design"] ** 2)),
        "unit_roughness_frobenius_squared": float(np.sum(problem["penalty_sat"] ** 2)),
        "parameter_count": int(problem["system_design"].shape[1]),
    }


def _active_support_graph_component_count(
    active_indices: np.ndarray,
    u_knots: np.ndarray,
    v_knots: np.ndarray,
    n_v: int,
) -> int:
    if not len(active_indices):
        return 0
    free_v_count = n_v - 1
    spans: list[tuple[float, float, float, float]] = []
    for index in active_indices:
        u_index = int(index) // free_v_count
        free_v_index = int(index) % free_v_count
        raw_v_indices = (
            (0, 1) if free_v_index == 0 else (free_v_index + 1,)
        )
        spans.append(
            (
                float(u_knots[u_index]),
                float(u_knots[u_index + DEGREE + 1]),
                min(float(v_knots[value]) for value in raw_v_indices),
                max(
                    float(v_knots[value + DEGREE + 1])
                    for value in raw_v_indices
                ),
            )
        )
    unseen = set(range(len(spans)))
    components = 0
    while unseen:
        components += 1
        stack = [min(unseen)]
        unseen.remove(stack[0])
        while stack:
            current = stack.pop()
            u0, u1, v0, v1 = spans[current]
            neighbours = [
                candidate
                for candidate in sorted(unseen)
                if max(u0, spans[candidate][0])
                < min(u1, spans[candidate][1])
                and max(v0, spans[candidate][2])
                < min(v1, spans[candidate][3])
            ]
            for candidate in neighbours:
                unseen.remove(candidate)
                stack.append(candidate)
    return components


def analyze_coenergy_full_basis(
    samples: CoenergySamples,
    spec: CoenergyFitSpec,
    quadratures: CoenergyQuadratures,
) -> CoenergyFullBasisCensus:
    """Return the CAP0 census before active pruning or regularization."""

    census_spec = replace(spec, roughness_weight=0.0, ridge_weight=0.0)
    problem = _analysis_problem(
        samples, census_spec, quadratures, prune_inactive=False
    )
    design = problem["weighted_data_design"]
    rank, singular_values, _ = _matrix_rank(design, spec.rank_tolerance)
    parameter_count = int(design.shape[1])
    smallest = (
        float(singular_values[rank - 1]) if rank > 0 else None
    )
    condition = (
        float(singular_values[0] / singular_values[rank - 1])
        if rank > 0
        else None
    )
    q_transform = problem["q_transform"]
    total_basis_count = int(problem["n_u"] * problem["n_v"])
    return CoenergyFullBasisCensus(
        total_basis_count=total_basis_count,
        symmetry_tied_basis_count=int(q_transform.shape[1]),
        exact_constraint_count=(
            total_basis_count
            - int(q_transform.shape[1])
            + int(problem["constraint_rank"])
        ),
        zero_support_basis_count=int(len(problem["zero_support_indices"])),
        low_order_projection_rank=int(problem["constraint_rank"]),
        low_order_projection_residual_norm=float(
            np.linalg.norm(problem["projection_residual"])
        ),
        low_order_projection_matrix_sha256=_matrix_sha256(
            problem["low_order_constraints"]
        ),
        data_design_rank=rank,
        data_nullity_before_regularization=parameter_count - rank,
        singular_values=_readonly(singular_values),
        smallest_nonzero_singular_value=smallest,
        condition_number_nonzero_subspace=condition,
        data_design_matrix_sha256=_matrix_sha256(design),
        numerical_diagnostics=_numerical_diagnostics(
            problem, census_spec, data_singular=singular_values,
            system_singular=singular_values,
        ),
    )


def analyze_coenergy_fit_system(
    samples: CoenergySamples,
    spec: CoenergyFitSpec,
    quadratures: CoenergyQuadratures,
) -> CoenergySystemDiagnostics:
    """Return opt-in E3 diagnostics without changing legacy fit metrics."""

    problem = _analysis_problem(
        samples, spec, quadratures, prune_inactive=True
    )
    design = problem["weighted_data_design"]
    data_rank, singular_values, _ = _matrix_rank(
        design, spec.rank_tolerance
    )
    if float(spec.roughness_weight) == 0.0 and float(spec.ridge_weight) == 0.0:
        effective_dof = float(data_rank)
    else:
        trend = design[:, :3]
        sat = design[:, 3:]
        trend_rank, _, _ = _matrix_rank(trend, spec.rank_tolerance)
        trend_u, _, _ = linalg.svd(
            trend,
            full_matrices=False,
            lapack_driver="gesvd",
            check_finite=True,
        )
        trend_basis = trend_u[:, :trend_rank]
        residualized = sat - trend_basis @ (trend_basis.T @ sat)
        penalty = problem["penalty_sat"]
        augmented = np.vstack([residualized, penalty])
        augmented_rank, _, _ = _matrix_rank(
            augmented, spec.rank_tolerance
        )
        augmented_u, _, _ = linalg.svd(
            augmented,
            full_matrices=False,
            lapack_driver="gesvd",
            check_finite=True,
        )
        effective_dof = float(
            trend_rank
            + np.sum(
                augmented_u[: len(residualized), :augmented_rank] ** 2
            )
        )
    smallest = (
        float(singular_values[data_rank - 1]) if data_rank > 0 else None
    )
    data_condition = (
        float(singular_values[0] / singular_values[data_rank - 1])
        if data_rank > 0
        else None
    )
    system_rank, system_singular_values, _ = _matrix_rank(
        problem["system_design"], spec.rank_tolerance
    )
    system_smallest = (
        float(system_singular_values[system_rank - 1])
        if system_rank > 0
        else None
    )
    system_condition = (
        float(system_singular_values[0] / system_singular_values[system_rank - 1])
        if system_rank > 0
        else None
    )
    return CoenergySystemDiagnostics(
        effective_degrees_of_freedom=effective_dof,
        active_support_graph_component_count=(
            _active_support_graph_component_count(
                problem["active_indices"],
                problem["u_knots"],
                problem["v_knots"],
                int(problem["n_v"]),
            )
        ),
        active_basis_count=int(len(problem["active_indices"])),
        zero_support_basis_count=int(len(problem["inactive_indices"])),
        low_order_projection_residual_norm=float(
            np.linalg.norm(problem["projection_residual"])
        ),
        data_smallest_nonzero_singular_value=smallest,
        data_condition_number_nonzero_subspace=data_condition,
        system_smallest_nonzero_singular_value=system_smallest,
        system_condition_number_nonzero_subspace=system_condition,
        numerical_diagnostics=_numerical_diagnostics(
            problem, spec, data_singular=singular_values,
            system_singular=system_singular_values,
        ),
    )


def fit_coenergy_model(
    samples: CoenergySamples,
    spec: CoenergyFitSpec,
    quadratures: CoenergyQuadratures,
) -> CoenergyFitResult:
    """Fit one constrained E1 model without touching production fit defaults."""

    problem = _analysis_problem(samples, spec, quadratures, prune_inactive=True)
    source = problem["source"]
    i_base = problem["i_base"]
    psi_base = problem["psi_base"]
    u_breakpoints = problem["u_breakpoints"]
    v_breakpoints = problem["v_breakpoints"]
    quad = problem["quad"]
    u_knots = problem["u_knots"]
    v_knots = problem["v_knots"]
    u = problem["u"]
    n_u = problem["n_u"]
    n_v = problem["n_v"]
    q_transform = problem["q_transform"]
    active_indices = problem["active_indices"]
    inactive_indices = problem["inactive_indices"]
    active_transform = problem["active_transform"]
    support = problem["support"]
    polynomial = problem["polynomial"]
    low_order_constraints = problem["low_order_constraints"]
    low_order_transform = problem["low_order_transform"]
    pivot_indices = problem["pivot_indices"]
    free_indices = problem["free_indices"]
    constraint_rank = problem["constraint_rank"]
    constraint_cutoff = problem["constraint_cutoff"]
    sat_raw_transform = problem["sat_raw_transform"]
    projection_residual = problem["projection_residual"]
    data_design = problem["data_design"]
    data_target = problem["data_target"]
    weighted_data_design = problem["weighted_data_design"]
    weighted_data_target = problem["weighted_data_target"]
    roughness_designs = problem["roughness_designs"]
    system_design = problem["system_design"]
    raw_basis_count = n_u * n_v
    active = support > float(spec.active_basis_tolerance)
    sat_basis_count = sat_raw_transform.shape[1]
    roughness_value = float(spec.roughness_weight)
    ridge_value = float(spec.ridge_weight)
    system_target = np.concatenate([
        weighted_data_target,
        np.zeros(system_design.shape[0] - len(weighted_data_target)),
    ])
    parameter_count = system_design.shape[1]
    data_rank, data_singular, data_cutoff = _matrix_rank(
        weighted_data_design, spec.rank_tolerance
    )
    system_rank, system_singular, system_cutoff = _matrix_rank(
        system_design, spec.rank_tolerance
    )
    diagnostics = _numerical_diagnostics(
        problem, spec, data_singular=data_singular, system_singular=system_singular
    )
    if system_rank != parameter_count:
        raise CoenergyFitError(
            "co-energy fit system is rank deficient after active-basis and "
            "low-order-span elimination: "
            f"rank={system_rank}, parameters={parameter_count}",
            diagnostics=diagnostics
        )

    try:
        solver_metrics: dict[str, Any]
        if spec.solver == "dense_gelsd":
            coefficients, _, solve_rank, solve_singular = linalg.lstsq(
                system_design,
                system_target,
                cond=spec.rank_tolerance,
                lapack_driver="gelsd",
                check_finite=True,
            )
            if int(solve_rank) != parameter_count:
                raise CoenergyFitError(
                    f"dense_gelsd returned rank={solve_rank}, expected={parameter_count}"
                )
            solver_metrics = {
                "lapack_driver": "gelsd",
                "reported_rank": int(solve_rank),
                "reported_min_singular_value": float(solve_singular[-1]),
            }
        else:
            column_norm = np.linalg.norm(system_design, axis=0)
            if (column_norm == 0.0).any() or not np.isfinite(column_norm).all():
                raise CoenergyFitError(
                    "sparse_lsmr column equilibration found a zero/nonfinite column"
                )
            equilibrated = sparse.csr_matrix(system_design / column_norm)
            solve = lsmr(
                equilibrated,
                system_target,
                atol=float(spec.solver_tolerance),
                btol=float(spec.solver_tolerance),
                maxiter=int(spec.solver_max_iterations),
            )
            if solve[1] not in (1, 2):
                raise CoenergyFitError(
                    f"sparse_lsmr did not converge to a residual criterion: istop={solve[1]}"
                )
            coefficients = np.asarray(solve[0], dtype=float) / column_norm
            estimated_condition, estimated_condition_infinite = _json_condition(
                float(solve[6])
            )
            solver_metrics = {
                "column_equilibration": "l2_norm",
                "istop": int(solve[1]),
                "iterations": int(solve[2]),
                "norm_residual": float(solve[3]),
                "norm_normal_residual": float(solve[4]),
                "estimated_condition": estimated_condition,
                "estimated_condition_is_infinite": estimated_condition_infinite,
                "solver_tolerance": float(spec.solver_tolerance),
                "solver_max_iterations": int(spec.solver_max_iterations),
            }
        if not np.isfinite(coefficients).all():
            raise CoenergyFitError("co-energy solver returned nonfinite coefficients")

    except (CoenergyFitError, linalg.LinAlgError, ValueError) as error:
        raise CoenergyFitError(str(error), diagnostics=diagnostics) from error

    fitted_target = system_design @ coefficients
    normal_residual = system_design.T @ (fitted_target - system_target)
    diagnostics["optimality_relative_residual"] = _relative_residual(
        float(np.linalg.norm(normal_residual)),
        float(system_singular[0])
        * (float(np.linalg.norm(fitted_target)) + float(np.linalg.norm(system_target))),
    )
    diagnostics["optimality_pass"] = diagnostics["optimality_relative_residual"] <= 1e-10

    low_order_coefficients = coefficients[:3]
    sat_coefficients = coefficients[3:]
    gauge_raw = _tensor_basis(
        u_knots, v_knots, DEGREE, quad.gauge_u, quad.gauge_v, 0, 0
    )
    gauge_sat = gauge_raw @ sat_raw_transform
    gauge_bar_ungauged = (
        low_order_coefficients[0] * quad.gauge_u
        + 0.5 * low_order_coefficients[1] * quad.gauge_u**2
        + 0.5 * low_order_coefficients[2] * quad.gauge_v**2
        + gauge_sat @ sat_coefficients
    )
    gauge_offset = float(
        np.dot(quad.gauge_weight, gauge_bar_ungauged)
        / np.sum(quad.gauge_weight)
    )
    model = CoenergyModel(
        i_base_A=i_base,
        psi_base_Wb=psi_base,
        u_knots=_readonly(u_knots),
        v_knots=_readonly(v_knots),
        low_order_coefficients=_readonly(low_order_coefficients),
        sat_coefficients=_readonly(sat_coefficients),
        sat_raw_transform=_readonly(sat_raw_transform),
        gauge_offset_bar=gauge_offset,
    )
    evaluation = model.evaluate(source.id_A, source.iq_A)
    prediction_d = np.asarray(evaluation.psi_d_Wb, dtype=float)
    prediction_q = np.asarray(evaluation.psi_q_Wb, dtype=float)
    residual_d = np.full(len(u), np.nan, dtype=float)
    residual_q = np.full(len(u), np.nan, dtype=float)
    residual_d[source.mask[:, 0]] = (
        prediction_d[source.mask[:, 0]] - source.psi_d_Wb[source.mask[:, 0]]
    )
    residual_q[source.mask[:, 1]] = (
        prediction_q[source.mask[:, 1]] - source.psi_q_Wb[source.mask[:, 1]]
    )

    q_axis_u = quad.gauge_u
    q_axis_v = np.zeros(len(q_axis_u), dtype=float)
    q_neumann_derivative = _tensor_basis(
        u_knots, v_knots, DEGREE, q_axis_u, q_axis_v, 0, 1
    ) @ sat_raw_transform
    post_gauge_mean = float(
        np.dot(quad.gauge_weight, gauge_bar_ungauged - gauge_offset)
        / np.sum(quad.gauge_weight)
    )

    if roughness_designs:
        multiplicities = (1.0, 3.0, 3.0, 1.0)
        roughness_integral = float(
            sum(
                multiplier
                * np.dot(
                    quad.roughness_weight,
                    (design @ sat_coefficients) ** 2,
                )
                for multiplier, design in zip(
                    multiplicities, roughness_designs, strict=True
                )
            )
        )
    else:
        roughness_integral = 0.0

    data_condition, data_condition_infinite = _json_condition(
        _condition_number(data_singular, data_rank, parameter_count)
    )
    system_condition, system_condition_infinite = _json_condition(
        _condition_number(system_singular, system_rank, parameter_count)
    )
    math_contract_hashes = {
        "u_knots_sha256": _matrix_sha256(u_knots.reshape(1, -1)),
        "v_knots_sha256": _matrix_sha256(v_knots.reshape(1, -1)),
        "q_neumann_transform_sha256": _matrix_sha256(q_transform),
        "active_transform_sha256": _matrix_sha256(active_transform),
        "support_probes_sha256": _matrix_sha256(
            np.column_stack([quad.support_u, quad.support_v])
        ),
        "active_support_vector_sha256": _matrix_sha256(
            support.reshape(1, -1)
        ),
        "span_quadrature_sha256": _matrix_sha256(
            np.column_stack([quad.span_u, quad.span_v, quad.span_weight])
        ),
        "low_order_polynomial_matrix_sha256": _matrix_sha256(polynomial),
        "low_order_constraint_matrix_sha256": _matrix_sha256(
            low_order_constraints
        ),
        "low_order_transform_sha256": _matrix_sha256(low_order_transform),
        "sat_raw_transform_sha256": _matrix_sha256(sat_raw_transform),
        "gauge_quadrature_sha256": _matrix_sha256(
            np.column_stack([quad.gauge_u, quad.gauge_v, quad.gauge_weight])
        ),
        "roughness_quadrature_sha256": _matrix_sha256(
            np.column_stack(
                [quad.roughness_u, quad.roughness_v, quad.roughness_weight]
            )
        ),
    }
    math_contract_hashes["aggregate_sha256"] = hashlib.sha256(
        json.dumps(
            math_contract_hashes,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()

    metrics: dict[str, Any] = {
        "contract": {
            "coordinate_system": "u=Id/I_base,v=Iq/I_base",
            "coenergy_scale": "W=I_base*Psi_base*bar_W",
            "coefficient_order": COEFFICIENT_ORDER,
            "negative_iq_extension": {
                "coenergy": "even",
                "psi_d": "even",
                "psi_q": "odd",
            },
            "degree": DEGREE,
            "ridge_default_is_zero": True,
        },
        "fit_spec": {
            "i_base_A": i_base,
            "psi_base_Wb": psi_base,
            "u_breakpoints": u_breakpoints.tolist(),
            "v_breakpoints": v_breakpoints.tolist(),
            "solver": spec.solver,
            "roughness_weight": roughness_value,
            "ridge_weight": ridge_value,
            "solver_tolerance": spec.solver_tolerance,
            "solver_max_iterations": spec.solver_max_iterations,
            "active_basis_tolerance": float(spec.active_basis_tolerance),
            "rank_tolerance": spec.rank_tolerance,
        },
        "basis": {
            "raw_basis_count": raw_basis_count,
            "q_neumann_free_basis_count": int(q_transform.shape[1]),
            "active_basis_count": int(len(active_indices)),
            "inactive_basis_count": int(len(inactive_indices)),
            "active_basis_indices": active_indices.tolist(),
            "inactive_basis_indices": inactive_indices.tolist(),
            "active_support_min": float(np.min(support[active])),
            "inactive_support_max": float(np.max(support[~active]))
            if (~active).any()
            else None,
            "active_basis_tolerance": float(spec.active_basis_tolerance),
            "low_order_span": ["1", "u", "u^2", "v^2"],
            "low_order_constraint_rank": constraint_rank,
            "low_order_constraint_cutoff": constraint_cutoff,
            "low_order_pivot_indices": pivot_indices.tolist(),
            "low_order_free_indices": free_indices.tolist(),
            "sat_basis_count": sat_basis_count,
            "low_order_projection_max_abs": float(
                np.max(np.abs(projection_residual), initial=0.0)
            ),
            "q_axis_neumann_basis_max_abs": float(
                np.max(np.abs(q_neumann_derivative), initial=0.0)
            ),
            "support_probe_count": int(len(quad.support_u)),
            "span_quadrature_count": int(len(quad.span_u)),
            "active_support_rule": (
                "observation_gradient_or_explicit_valid_domain_value_probe"
            ),
            "low_order_span_quadrature": "Q_span_distinct_from_Q_gauge",
        },
        "linear_system": {
            "enabled_observation_count": int(len(data_target)),
            "parameter_count": parameter_count,
            "data_rank": data_rank,
            "data_nullity": parameter_count - data_rank,
            "data_rank_cutoff": data_cutoff,
            "data_condition_number": data_condition,
            "data_condition_is_infinite": data_condition_infinite,
            "system_row_count": int(system_design.shape[0]),
            "system_rank": system_rank,
            "system_nullity": parameter_count - system_rank,
            "system_rank_cutoff": system_cutoff,
            "system_condition_number": system_condition,
            "system_condition_is_infinite": system_condition_infinite,
            "matrix_sha256": _matrix_sha256(system_design),
        },
        "math_contract_hashes": math_contract_hashes,
        "solver": {"name": spec.solver, **solver_metrics},
        "regularization": {
            "roughness_weight": roughness_value,
            "roughness_definition": "W_uuu^2+3W_uuv^2+3W_uvv^2+W_vvv^2",
            "roughness_integral": roughness_integral,
            "ridge_weight": ridge_value,
            "regularized_components": "sat_only",
        },
        "gauge": {
            "method": "fixed_domain_post_fit_weighted_mean",
            "gauge_quadrature_count": int(len(quad.gauge_u)),
            "offset_bar_W": gauge_offset,
            "weighted_mean_bar_W_after": post_gauge_mean,
        },
        "training_residual": {
            "psi_d_enabled_count": int(source.mask[:, 0].sum()),
            "psi_q_enabled_count": int(source.mask[:, 1].sum()),
            "psi_d_rms_Wb": float(
                np.sqrt(np.mean(residual_d[source.mask[:, 0]] ** 2))
            )
            if source.mask[:, 0].any()
            else None,
            "psi_q_rms_Wb": float(
                np.sqrt(np.mean(residual_q[source.mask[:, 1]] ** 2))
            )
            if source.mask[:, 1].any()
            else None,
        },
    }
    return CoenergyFitResult(
        model=model,
        prediction_psi_d_Wb=_readonly(prediction_d),
        prediction_psi_q_Wb=_readonly(prediction_q),
        residual_psi_d_Wb=_readonly(residual_d),
        residual_psi_q_Wb=_readonly(residual_q),
        metrics=metrics,
        numerical_diagnostics=diagnostics,
    )
