"""Sparse Co-energy correction around a fixed JMAG prior.

The functions in this module implement the mathematical core of method B from
the DEN third-report plan.  A fixed prior is evaluated at measured anchors,
only the residual flux is fitted with the existing scalar Co-energy solver,
and the two scalar potentials are combined analytically.

The correction support is explicit.  Anchors must lie in its unit-weight core;
a C2 quintic taper returns the correction to exactly zero outside the support.
The taper multiplies a gauge-fixed Co-energy difference, so its gradient and
Hessian remain reciprocal and do not depend on the arbitrary fitted gauge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .coenergy_forward_fit import (
    CoenergyEvaluation,
    CoenergyFitError,
    CoenergyFitResult,
    CoenergyFitSpec,
    CoenergyModel,
    CoenergyQuadratures,
    CoenergySamples,
    _broadcast,
    _readonly,
    _restore,
    _validated_samples,
    fit_coenergy_model,
)


@dataclass(frozen=True)
class CorrectionSupportSpec:
    """Explicit C2 rectangular support in physical current coordinates.

    ``*_outer_A`` is the closed nonzero-support extent and ``*_core_A`` is
    the unit-weight extent.  The q intervals apply to ``abs(Iq)``.  The lower
    q bounds may both be zero; all other core boundaries must have a nonzero
    taper width.  ``reference_*`` fixes the otherwise arbitrary additive
    constant of the correction potential before tapering.
    """

    id_outer_A: tuple[float, float]
    id_core_A: tuple[float, float]
    iq_outer_abs_A: tuple[float, float]
    iq_core_abs_A: tuple[float, float]
    reference_id_A: float
    reference_iq_A: float

    def __post_init__(self) -> None:
        bounds = _validated_support(self)
        object.__setattr__(self, "id_outer_A", bounds.id_outer)
        object.__setattr__(self, "id_core_A", bounds.id_core)
        object.__setattr__(self, "iq_outer_abs_A", bounds.iq_outer)
        object.__setattr__(self, "iq_core_abs_A", bounds.iq_core)
        object.__setattr__(self, "reference_id_A", bounds.reference_id_A)
        object.__setattr__(self, "reference_iq_A", bounds.reference_iq_A)


@dataclass(frozen=True)
class CorrectionSupportEvaluation:
    """Support weight and its first/second current derivatives."""

    weight: Any
    d_id_per_A: Any
    d_iq_per_A: Any
    d2_id2_per_A2: Any
    d2_id_iq_per_A2: Any
    d2_iq2_per_A2: Any


@dataclass(frozen=True)
class PriorCorrectedCoenergyModel:
    """Fixed prior plus a localized, gauge-fixed correction potential."""

    prior_model: CoenergyModel
    correction_model: CoenergyModel
    support: CorrectionSupportSpec
    correction_reference_coenergy_J: float = field(init=False)

    def __post_init__(self) -> None:
        bounds = _validate_support_domains(
            self.prior_model, self.correction_model, self.support
        )
        reference = self.correction_model.evaluate(
            bounds.reference_id_A, bounds.reference_iq_A
        )
        object.__setattr__(
            self,
            "correction_reference_coenergy_J",
            float(reference.coenergy_J),
        )

    def evaluate_correction(
        self, id_A: object, iq_A: object
    ) -> CoenergyEvaluation:
        """Evaluate only the localized correction and its derivatives."""

        (id_values, iq_values), shape = _broadcast(id_A, iq_A)
        id_flat = id_values.reshape(-1)
        iq_flat = iq_values.reshape(-1)
        support = _support_arrays(self.support, id_flat, iq_flat)

        correction_w = np.zeros(len(id_flat), dtype=float)
        correction_d = np.zeros(len(id_flat), dtype=float)
        correction_q = np.zeros(len(id_flat), dtype=float)
        correction_dd = np.zeros(len(id_flat), dtype=float)
        correction_dq = np.zeros(len(id_flat), dtype=float)
        correction_qd = np.zeros(len(id_flat), dtype=float)
        correction_qq = np.zeros(len(id_flat), dtype=float)

        active = (
            (support[0] != 0.0)
            | (support[1] != 0.0)
            | (support[2] != 0.0)
            | (support[3] != 0.0)
            | (support[4] != 0.0)
            | (support[5] != 0.0)
        )
        if active.any():
            delta = self.correction_model.evaluate(
                id_flat[active], iq_flat[active]
            )
            weight, d_id, d_iq, d2_id2, d2_id_iq, d2_iq2 = (
                values[active] for values in support
            )
            shifted_w = (
                np.asarray(delta.coenergy_J, dtype=float)
                - float(self.correction_reference_coenergy_J)
            )
            psi_d = np.asarray(delta.psi_d_Wb, dtype=float)
            psi_q = np.asarray(delta.psi_q_Wb, dtype=float)
            l_dd = np.asarray(delta.l_dd_H, dtype=float)
            l_dq = np.asarray(delta.l_dq_H, dtype=float)
            l_qd = np.asarray(delta.l_qd_H, dtype=float)
            l_qq = np.asarray(delta.l_qq_H, dtype=float)

            correction_w[active] = weight * shifted_w
            correction_d[active] = weight * psi_d + shifted_w * d_id
            correction_q[active] = weight * psi_q + shifted_w * d_iq
            correction_dd[active] = (
                weight * l_dd + 2.0 * d_id * psi_d + shifted_w * d2_id2
            )
            correction_dq[active] = (
                weight * l_dq
                + d_id * psi_q
                + d_iq * psi_d
                + shifted_w * d2_id_iq
            )
            correction_qd[active] = (
                weight * l_qd
                + d_iq * psi_d
                + d_id * psi_q
                + shifted_w * d2_id_iq
            )
            correction_qq[active] = (
                weight * l_qq + 2.0 * d_iq * psi_q + shifted_w * d2_iq2
            )

        return CoenergyEvaluation(
            coenergy_J=_restore(correction_w, shape),
            psi_d_Wb=_restore(correction_d, shape),
            psi_q_Wb=_restore(correction_q, shape),
            l_dd_H=_restore(correction_dd, shape),
            l_dq_H=_restore(correction_dq, shape),
            l_qd_H=_restore(correction_qd, shape),
            l_qq_H=_restore(correction_qq, shape),
        )

    def evaluate(self, id_A: object, iq_A: object) -> CoenergyEvaluation:
        """Evaluate prior plus localized correction."""

        prior = self.prior_model.evaluate(id_A, iq_A)
        correction = self.evaluate_correction(id_A, iq_A)
        return CoenergyEvaluation(
            coenergy_J=prior.coenergy_J + correction.coenergy_J,
            psi_d_Wb=prior.psi_d_Wb + correction.psi_d_Wb,
            psi_q_Wb=prior.psi_q_Wb + correction.psi_q_Wb,
            l_dd_H=prior.l_dd_H + correction.l_dd_H,
            l_dq_H=prior.l_dq_H + correction.l_dq_H,
            l_qd_H=prior.l_qd_H + correction.l_qd_H,
            l_qq_H=prior.l_qq_H + correction.l_qq_H,
        )


@dataclass(frozen=True)
class PriorCorrectionFitResult:
    """Sparse residual fit plus anchor-level numerical results."""

    model: PriorCorrectedCoenergyModel
    delta_fit: CoenergyFitResult
    anchor_samples: CoenergySamples
    residual_samples: CoenergySamples
    prior_prediction_psi_d_Wb: np.ndarray
    prior_prediction_psi_q_Wb: np.ndarray
    correction_prediction_psi_d_Wb: np.ndarray
    correction_prediction_psi_q_Wb: np.ndarray
    total_prediction_psi_d_Wb: np.ndarray
    total_prediction_psi_q_Wb: np.ndarray
    total_residual_psi_d_Wb: np.ndarray
    total_residual_psi_q_Wb: np.ndarray
    metrics: dict[str, Any]


@dataclass(frozen=True)
class _SupportBounds:
    id_outer: tuple[float, float]
    id_core: tuple[float, float]
    iq_outer: tuple[float, float]
    iq_core: tuple[float, float]
    reference_id_A: float
    reference_iq_A: float


def _finite_pair(value: object, name: str) -> tuple[float, float]:
    try:
        array = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError) as error:
        raise CoenergyFitError(
            f"{name} must be a numeric length-2 interval"
        ) from error
    if len(array) != 2 or not np.isfinite(array).all():
        raise CoenergyFitError(f"{name} must be a finite length-2 interval")
    if not array[0] < array[1]:
        raise CoenergyFitError(f"{name} must be strictly increasing")
    return float(array[0]), float(array[1])


def _validated_support(spec: CorrectionSupportSpec) -> _SupportBounds:
    if not isinstance(spec, CorrectionSupportSpec):
        raise CoenergyFitError("support must be a CorrectionSupportSpec instance")
    id_outer = _finite_pair(spec.id_outer_A, "support.id_outer_A")
    id_core = _finite_pair(spec.id_core_A, "support.id_core_A")
    iq_outer = _finite_pair(spec.iq_outer_abs_A, "support.iq_outer_abs_A")
    iq_core = _finite_pair(spec.iq_core_abs_A, "support.iq_core_abs_A")
    if not (id_outer[0] < id_core[0] < id_core[1] < id_outer[1]):
        raise CoenergyFitError(
            "support Id core must be strictly inside its outer interval"
        )
    if iq_outer[0] < 0.0 or iq_core[0] < 0.0:
        raise CoenergyFitError("support abs(Iq) intervals must be nonnegative")
    q_lower_valid = (
        iq_outer[0] < iq_core[0]
        or (iq_outer[0] == 0.0 and iq_core[0] == 0.0)
    )
    if not (
        q_lower_valid
        and iq_core[0] < iq_core[1] < iq_outer[1]
    ):
        raise CoenergyFitError(
            "support abs(Iq) core must be inside its outer interval; only the "
            "shared zero lower boundary may have zero taper width"
        )
    try:
        reference_id = float(spec.reference_id_A)
        reference_iq = float(spec.reference_iq_A)
    except (TypeError, ValueError) as error:
        raise CoenergyFitError("support reference current must be numeric") from error
    if not np.isfinite(reference_id) or not np.isfinite(reference_iq):
        raise CoenergyFitError("support reference current must be finite")
    if not id_core[0] <= reference_id <= id_core[1]:
        raise CoenergyFitError("support reference Id must lie in the core")
    if not iq_core[0] <= abs(reference_iq) <= iq_core[1]:
        raise CoenergyFitError("support reference abs(Iq) must lie in the core")
    return _SupportBounds(
        id_outer=id_outer,
        id_core=id_core,
        iq_outer=iq_outer,
        iq_core=iq_core,
        reference_id_A=reference_id,
        reference_iq_A=reference_iq,
    )


def _smoothstep5(value: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    value2 = value * value
    value3 = value2 * value
    smooth = value3 * (10.0 + value * (-15.0 + 6.0 * value))
    first = 30.0 * value2 * (value - 1.0) ** 2
    second = 60.0 * value * (2.0 * value2 - 3.0 * value + 1.0)
    return smooth, first, second


def _interval_taper(
    values: np.ndarray,
    outer: tuple[float, float],
    core: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    weight = np.zeros(len(values), dtype=float)
    first = np.zeros(len(values), dtype=float)
    second = np.zeros(len(values), dtype=float)

    core_mask = (values >= core[0]) & (values <= core[1])
    weight[core_mask] = 1.0

    if core[0] > outer[0]:
        left = (values >= outer[0]) & (values < core[0])
        coordinate = (values[left] - outer[0]) / (core[0] - outer[0])
        smooth, derivative, curvature = _smoothstep5(coordinate)
        width = core[0] - outer[0]
        weight[left] = smooth
        first[left] = derivative / width
        second[left] = curvature / (width * width)

    right = (values > core[1]) & (values <= outer[1])
    coordinate = (values[right] - core[1]) / (outer[1] - core[1])
    smooth, derivative, curvature = _smoothstep5(coordinate)
    width = outer[1] - core[1]
    weight[right] = 1.0 - smooth
    first[right] = -derivative / width
    second[right] = -curvature / (width * width)
    return weight, first, second


def _support_arrays(
    spec: CorrectionSupportSpec,
    id_A: np.ndarray,
    iq_A: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    bounds = _validated_support(spec)
    id_weight, id_first, id_second = _interval_taper(
        id_A, bounds.id_outer, bounds.id_core
    )
    iq_abs = np.abs(iq_A)
    q_weight, q_first_abs, q_second_abs = _interval_taper(
        iq_abs, bounds.iq_outer, bounds.iq_core
    )
    q_first = np.sign(iq_A) * q_first_abs
    return (
        id_weight * q_weight,
        id_first * q_weight,
        id_weight * q_first,
        id_second * q_weight,
        id_first * q_first,
        id_weight * q_second_abs,
    )


def evaluate_correction_support(
    spec: CorrectionSupportSpec, id_A: object, iq_A: object
) -> CorrectionSupportEvaluation:
    """Evaluate the explicit C2 support and its physical derivatives."""

    (id_values, iq_values), shape = _broadcast(id_A, iq_A)
    arrays = _support_arrays(
        spec, id_values.reshape(-1), iq_values.reshape(-1)
    )
    return CorrectionSupportEvaluation(
        weight=_restore(arrays[0], shape),
        d_id_per_A=_restore(arrays[1], shape),
        d_iq_per_A=_restore(arrays[2], shape),
        d2_id2_per_A2=_restore(arrays[3], shape),
        d2_id_iq_per_A2=_restore(arrays[4], shape),
        d2_iq2_per_A2=_restore(arrays[5], shape),
    )


def _validate_support_domains(
    prior_model: CoenergyModel,
    correction_model: CoenergyModel,
    support: CorrectionSupportSpec,
) -> _SupportBounds:
    if not isinstance(prior_model, CoenergyModel):
        raise CoenergyFitError("prior_model must be a CoenergyModel instance")
    bounds = _validated_support(support)
    correction_id_domain = (
        correction_model.i_base_A
        * correction_model.u_knots[correction_model.degree],
        correction_model.i_base_A
        * correction_model.u_knots[-correction_model.degree - 1],
    )
    correction_iq_max = (
        correction_model.i_base_A
        * correction_model.v_knots[-correction_model.degree - 1]
    )
    tolerance = 64.0 * np.finfo(float).eps * max(
        1.0,
        abs(correction_id_domain[0]),
        abs(correction_id_domain[1]),
        abs(correction_iq_max),
    )
    if (
        bounds.id_outer[0] < correction_id_domain[0] - tolerance
        or bounds.id_outer[1] > correction_id_domain[1] + tolerance
        or bounds.iq_outer[1] > correction_iq_max + tolerance
    ):
        raise CoenergyFitError(
            "correction support outer interval must lie inside the delta-model domain"
        )

    # The fixed prior must cover every corner of the correction support.  This
    # is a physical model-domain check, not provenance or process metadata.
    prior_model.evaluate(
        np.array(
            [
                bounds.id_outer[0],
                bounds.id_outer[0],
                bounds.id_outer[1],
                bounds.id_outer[1],
            ]
        ),
        np.array(
            [bounds.iq_outer[0], bounds.iq_outer[1], bounds.iq_outer[0], bounds.iq_outer[1]]
        ),
    )
    return bounds


def _readonly_samples(source: Any, psi_d: np.ndarray, psi_q: np.ndarray) -> CoenergySamples:
    mask = np.array(source.mask, dtype=bool, copy=True)
    mask.flags.writeable = False
    if source.weight is None:
        component_weight = None
    else:
        component_weight = _readonly(source.weight)
    if source.weight_matrix is None:
        component_weight_matrix = None
    else:
        component_weight_matrix = _readonly(source.weight_matrix)
    return CoenergySamples(
        id_A=_readonly(source.id_A),
        iq_A=_readonly(source.iq_A),
        psi_d_Wb=_readonly(psi_d),
        psi_q_Wb=_readonly(psi_q),
        component_mask=mask,
        component_weight=component_weight,
        component_weight_matrix=component_weight_matrix,
    )


def _masked_rms(values: np.ndarray, mask: np.ndarray) -> float | None:
    return float(np.sqrt(np.mean(values[mask] ** 2))) if mask.any() else None


def fit_prior_correction(
    prior_model: CoenergyModel,
    anchor_samples: CoenergySamples,
    delta_spec: CoenergyFitSpec,
    quadratures: CoenergyQuadratures,
    support: CorrectionSupportSpec,
) -> PriorCorrectionFitResult:
    """Fit ``target - prior`` at anchors and return the reciprocal composite.

    Only values in ``anchor_samples`` are passed to the solve.  Anchors must be
    in the unit-weight support core so the fitted residual is the correction
    gradient without taper terms.  No validation or candidate target values
    are accepted by this API.
    """

    source = _validated_samples(anchor_samples)
    support_at_anchor = _support_arrays(support, source.id_A, source.iq_A)
    enabled_rows = source.mask.any(axis=1)
    in_flat_core = (
        (support_at_anchor[0] == 1.0)
        & (support_at_anchor[1] == 0.0)
        & (support_at_anchor[2] == 0.0)
        & (support_at_anchor[3] == 0.0)
        & (support_at_anchor[4] == 0.0)
        & (support_at_anchor[5] == 0.0)
    )
    invalid_anchor = np.flatnonzero(enabled_rows & ~in_flat_core)
    if len(invalid_anchor):
        raise CoenergyFitError(
            "enabled correction anchors must lie in the unit-weight support "
            f"core at position(s): {invalid_anchor.tolist()}"
        )

    prior = prior_model.evaluate(source.id_A, source.iq_A)
    prior_d = np.asarray(prior.psi_d_Wb, dtype=float).reshape(-1)
    prior_q = np.asarray(prior.psi_q_Wb, dtype=float).reshape(-1)
    residual_target_d = np.array(source.psi_d_Wb, dtype=float, copy=True)
    residual_target_q = np.array(source.psi_q_Wb, dtype=float, copy=True)
    residual_target_d[source.mask[:, 0]] -= prior_d[source.mask[:, 0]]
    residual_target_q[source.mask[:, 1]] -= prior_q[source.mask[:, 1]]
    residual_samples = _readonly_samples(
        source, residual_target_d, residual_target_q
    )

    delta_fit = fit_coenergy_model(residual_samples, delta_spec, quadratures)
    bounds = _validated_support(support)
    model = PriorCorrectedCoenergyModel(
        prior_model=prior_model,
        correction_model=delta_fit.model,
        support=support,
    )
    correction = model.evaluate_correction(source.id_A, source.iq_A)
    total = model.evaluate(source.id_A, source.iq_A)
    correction_d = np.asarray(correction.psi_d_Wb, dtype=float).reshape(-1)
    correction_q = np.asarray(correction.psi_q_Wb, dtype=float).reshape(-1)
    total_d = np.asarray(total.psi_d_Wb, dtype=float).reshape(-1)
    total_q = np.asarray(total.psi_q_Wb, dtype=float).reshape(-1)
    total_residual_d = np.full(len(source.id_A), np.nan, dtype=float)
    total_residual_q = np.full(len(source.id_A), np.nan, dtype=float)
    total_residual_d[source.mask[:, 0]] = (
        total_d[source.mask[:, 0]] - source.psi_d_Wb[source.mask[:, 0]]
    )
    total_residual_q[source.mask[:, 1]] = (
        total_q[source.mask[:, 1]] - source.psi_q_Wb[source.mask[:, 1]]
    )
    anchor_copy = _readonly_samples(source, source.psi_d_Wb, source.psi_q_Wb)
    metrics = {
        "anchor_count": int(enabled_rows.sum()),
        "enabled_component_count": int(source.mask.sum()),
        "support": {
            "id_outer_A": list(bounds.id_outer),
            "id_core_A": list(bounds.id_core),
            "iq_outer_abs_A": list(bounds.iq_outer),
            "iq_core_abs_A": list(bounds.iq_core),
            "reference_id_A": bounds.reference_id_A,
            "reference_iq_A": bounds.reference_iq_A,
            "rule": "C2_quintic_rectangular_coenergy_taper",
        },
        "training_residual": {
            "psi_d_rms_Wb": _masked_rms(
                total_residual_d, source.mask[:, 0]
            ),
            "psi_q_rms_Wb": _masked_rms(
                total_residual_q, source.mask[:, 1]
            ),
        },
    }
    return PriorCorrectionFitResult(
        model=model,
        delta_fit=delta_fit,
        anchor_samples=anchor_copy,
        residual_samples=residual_samples,
        prior_prediction_psi_d_Wb=_readonly(prior_d),
        prior_prediction_psi_q_Wb=_readonly(prior_q),
        correction_prediction_psi_d_Wb=_readonly(correction_d),
        correction_prediction_psi_q_Wb=_readonly(correction_q),
        total_prediction_psi_d_Wb=_readonly(total_d),
        total_prediction_psi_q_Wb=_readonly(total_q),
        total_residual_psi_d_Wb=_readonly(total_residual_d),
        total_residual_psi_q_Wb=_readonly(total_residual_q),
        metrics=metrics,
    )
