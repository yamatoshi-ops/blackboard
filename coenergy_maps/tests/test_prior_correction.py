from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np

from coenergy_maps.coenergy_forward_fit import (
    CoenergyFitError,
    CoenergyFitSpec,
    CoenergyQuadratures,
    CoenergySamples,
    fit_coenergy_model,
)
from coenergy_maps.coenergy_prior_correction import (
    CorrectionSupportSpec,
    PriorCorrectedCoenergyModel,
    evaluate_correction_support,
    fit_prior_correction,
)


class CoenergyPriorCorrectionTest(unittest.TestCase):
    i_base_A = 1000.0
    psi_base_Wb = 0.2
    prior_coefficients = (0.42, 0.24, 0.31, 0.025)
    delta_coefficients = (0.018, 0.009, -0.006, 0.004)

    @classmethod
    def mesh(cls, u_values, v_values):
        u_grid, v_grid = np.meshgrid(u_values, v_values, indexing="ij")
        return u_grid.reshape(-1), v_grid.reshape(-1)

    @classmethod
    def normalized_flux(cls, u, v, coefficients):
        a1, a2, a3, cross = coefficients
        return (
            a1 + a2 * u + 2.0 * cross * u * v * v,
            a3 * v + 2.0 * cross * u * u * v,
        )

    @classmethod
    def normalized_coenergy(cls, u, v, coefficients):
        a1, a2, a3, cross = coefficients
        return (
            a1 * u
            + 0.5 * a2 * u * u
            + 0.5 * a3 * v * v
            + cross * u * u * v * v
        )

    @classmethod
    def samples_from_flux(cls, u, v, psi_d, psi_q):
        return CoenergySamples(
            id_A=cls.i_base_A * np.asarray(u),
            iq_A=cls.i_base_A * np.asarray(v),
            psi_d_Wb=np.asarray(psi_d),
            psi_q_Wb=np.asarray(psi_q),
            component_mask=np.ones((len(np.asarray(u)), 2), dtype=bool),
            component_weight=np.ones((len(np.asarray(u)), 2), dtype=float),
        )

    @classmethod
    def quadratures(cls):
        support_u, support_v = cls.mesh(
            np.linspace(-1.0, 1.0, 9), np.linspace(0.0, 1.0, 7)
        )
        span_u, span_v = cls.mesh(
            np.linspace(-1.0, 1.0, 11), np.linspace(0.0, 1.0, 8)
        )
        gauge_u, gauge_v = cls.mesh(
            np.linspace(-1.0, 1.0, 7), np.linspace(0.0, 1.0, 6)
        )
        roughness_u, roughness_v = cls.mesh(
            np.linspace(-1.0, 1.0, 10), np.linspace(0.0, 1.0, 7)
        )
        return CoenergyQuadratures(
            support_u=support_u,
            support_v=support_v,
            span_u=span_u,
            span_v=span_v,
            span_weight=np.ones(len(span_u)),
            gauge_u=gauge_u,
            gauge_v=gauge_v,
            gauge_weight=np.ones(len(gauge_u)),
            roughness_u=roughness_u,
            roughness_v=roughness_v,
            roughness_weight=np.ones(len(roughness_u)),
        )

    @classmethod
    def spec(cls, *, sparse=False, ridge=0.0):
        return CoenergyFitSpec(
            i_base_A=cls.i_base_A,
            psi_base_Wb=cls.psi_base_Wb,
            u_breakpoints=(-1.0, 0.0, 1.0)
            if sparse
            else (-1.0, -0.5, 0.0, 0.5, 1.0),
            v_breakpoints=(0.0, 0.5, 1.0)
            if sparse
            else (0.0, 0.25, 0.5, 0.75, 1.0),
            solver="dense_gelsd",
            roughness_weight=0.0,
            solver_tolerance=None,
            solver_max_iterations=None,
            active_basis_tolerance=1.0e-14,
            rank_tolerance=None,
            ridge_weight=ridge,
        )

    @classmethod
    def support(cls):
        return CorrectionSupportSpec(
            id_outer_A=(-900.0, 900.0),
            id_core_A=(-700.0, 700.0),
            iq_outer_abs_A=(0.0, 900.0),
            iq_core_abs_A=(0.0, 700.0),
            reference_id_A=0.0,
            reference_iq_A=0.0,
        )

    @classmethod
    def setUpClass(cls):
        full_u, full_v = cls.mesh(
            np.linspace(-1.0, 1.0, 13), np.linspace(0.0, 1.0, 9)
        )
        prior_d, prior_q = cls.normalized_flux(
            full_u, full_v, cls.prior_coefficients
        )
        prior_samples = cls.samples_from_flux(
            full_u,
            full_v,
            cls.psi_base_Wb * prior_d,
            cls.psi_base_Wb * prior_q,
        )
        cls.prior_model = fit_coenergy_model(
            prior_samples, cls.spec(), cls.quadratures()
        ).model

        anchor_u, anchor_v = cls.mesh(
            np.linspace(-0.65, 0.65, 11), np.linspace(0.0, 0.65, 8)
        )
        prior = cls.prior_model.evaluate(
            cls.i_base_A * anchor_u, cls.i_base_A * anchor_v
        )
        delta_d, delta_q = cls.normalized_flux(
            anchor_u, anchor_v, cls.delta_coefficients
        )
        cls.anchor_samples = cls.samples_from_flux(
            anchor_u,
            anchor_v,
            np.asarray(prior.psi_d_Wb) + cls.psi_base_Wb * delta_d,
            np.asarray(prior.psi_q_Wb) + cls.psi_base_Wb * delta_q,
        )
        cls.result = fit_prior_correction(
            cls.prior_model,
            cls.anchor_samples,
            cls.spec(sparse=True),
            cls.quadratures(),
            cls.support(),
        )

    def test_parameter_design_reproduces_fitted_flux(self):
        id_A = np.array([-750.0, -120.0, 430.0])
        iq_A = np.array([180.0, -390.0, 610.0])
        model = self.result.model.correction_model
        design = model.normalized_flux_parameter_design(id_A, iq_A)
        normalized = np.einsum(
            "ncp,p->nc", design, model.parameter_vector()
        )
        evaluation = model.evaluate(id_A, iq_A)
        np.testing.assert_allclose(
            self.psi_base_Wb * normalized[:, 0],
            evaluation.psi_d_Wb,
            rtol=0.0,
            atol=2.0e-15,
        )
        np.testing.assert_allclose(
            self.psi_base_Wb * normalized[:, 1],
            evaluation.psi_q_Wb,
            rtol=0.0,
            atol=2.0e-15,
        )
        with self.assertRaises(ValueError):
            design[0, 0, 0] = 0.0

    def test_sparse_residual_fit_recovers_known_delta_in_core(self):
        self.assertIs(self.result.model.prior_model, self.prior_model)
        u, v = self.mesh(
            np.linspace(-0.6, 0.6, 9), np.linspace(0.0, 0.6, 7)
        )
        id_A = self.i_base_A * u
        iq_A = self.i_base_A * v
        prior = self.prior_model.evaluate(id_A, iq_A)
        actual = self.result.model.evaluate(id_A, iq_A)
        delta_d, delta_q = self.normalized_flux(
            u, v, self.delta_coefficients
        )
        np.testing.assert_allclose(
            actual.psi_d_Wb,
            np.asarray(prior.psi_d_Wb) + self.psi_base_Wb * delta_d,
            rtol=0.0,
            atol=3.0e-15,
        )
        np.testing.assert_allclose(
            actual.psi_q_Wb,
            np.asarray(prior.psi_q_Wb) + self.psi_base_Wb * delta_q,
            rtol=0.0,
            atol=3.0e-15,
        )
        self.assertLess(
            self.result.metrics["training_residual"]["psi_d_rms_Wb"],
            3.0e-15,
        )
        self.assertLess(
            self.result.metrics["training_residual"]["psi_q_rms_Wb"],
            3.0e-15,
        )

    def test_zero_target_difference_produces_zero_correction(self):
        id_A = np.asarray(self.anchor_samples.id_A)
        iq_A = np.asarray(self.anchor_samples.iq_A)
        prior = self.prior_model.evaluate(id_A, iq_A)
        zero_samples = replace(
            self.anchor_samples,
            psi_d_Wb=np.asarray(prior.psi_d_Wb),
            psi_q_Wb=np.asarray(prior.psi_q_Wb),
        )
        zero = fit_prior_correction(
            self.prior_model,
            zero_samples,
            self.spec(sparse=True),
            self.quadratures(),
            self.support(),
        )
        u, v = self.mesh(
            np.linspace(-0.9, 0.9, 15), np.linspace(0.0, 0.9, 11)
        )
        correction = zero.model.evaluate_correction(
            self.i_base_A * u, self.i_base_A * v
        )
        self.assertLess(np.max(np.abs(correction.psi_d_Wb)), 1.0e-15)
        self.assertLess(np.max(np.abs(correction.psi_q_Wb)), 1.0e-15)
        self.assertLess(np.max(np.abs(correction.coenergy_J)), 1.0e-12)

    def test_support_returns_exactly_to_prior_and_is_even_in_iq(self):
        id_A = np.array([-950.0, 950.0, 0.0, 900.0])
        iq_A = np.array([300.0, 300.0, 950.0, 300.0])
        prior = self.prior_model.evaluate(id_A, iq_A)
        total = self.result.model.evaluate(id_A, iq_A)
        for field in (
            "coenergy_J",
            "psi_d_Wb",
            "psi_q_Wb",
            "l_dd_H",
            "l_dq_H",
            "l_qd_H",
            "l_qq_H",
        ):
            np.testing.assert_array_equal(
                np.asarray(getattr(total, field)),
                np.asarray(getattr(prior, field)),
            )

        plus = self.result.model.evaluate_correction(350.0, 820.0)
        minus = self.result.model.evaluate_correction(350.0, -820.0)
        self.assertEqual(plus.coenergy_J, minus.coenergy_J)
        self.assertEqual(plus.psi_d_Wb, minus.psi_d_Wb)
        self.assertEqual(plus.psi_q_Wb, -minus.psi_q_Wb)
        self.assertEqual(plus.l_dd_H, minus.l_dd_H)
        self.assertEqual(plus.l_dq_H, -minus.l_dq_H)
        self.assertEqual(plus.l_qd_H, -minus.l_qd_H)
        self.assertEqual(plus.l_qq_H, minus.l_qq_H)

    def test_taper_gradient_hessian_and_reciprocity_are_analytic(self):
        id_A = 810.0
        iq_A = 790.0
        step_A = 0.01
        correction = self.result.model.evaluate_correction(id_A, iq_A)
        d_plus = self.result.model.evaluate_correction(id_A + step_A, iq_A)
        d_minus = self.result.model.evaluate_correction(id_A - step_A, iq_A)
        q_plus = self.result.model.evaluate_correction(id_A, iq_A + step_A)
        q_minus = self.result.model.evaluate_correction(id_A, iq_A - step_A)

        numerical_psi_d = (d_plus.coenergy_J - d_minus.coenergy_J) / (
            2.0 * step_A
        )
        numerical_psi_q = (q_plus.coenergy_J - q_minus.coenergy_J) / (
            2.0 * step_A
        )
        numerical_l_dd = (d_plus.psi_d_Wb - d_minus.psi_d_Wb) / (
            2.0 * step_A
        )
        numerical_l_dq = (q_plus.psi_d_Wb - q_minus.psi_d_Wb) / (
            2.0 * step_A
        )
        numerical_l_qq = (q_plus.psi_q_Wb - q_minus.psi_q_Wb) / (
            2.0 * step_A
        )
        self.assertAlmostEqual(correction.psi_d_Wb, numerical_psi_d, places=9)
        self.assertAlmostEqual(correction.psi_q_Wb, numerical_psi_q, places=9)
        self.assertAlmostEqual(correction.l_dd_H, numerical_l_dd, places=11)
        self.assertAlmostEqual(correction.l_dq_H, numerical_l_dq, places=11)
        self.assertAlmostEqual(correction.l_qq_H, numerical_l_qq, places=11)
        self.assertEqual(correction.l_dq_H, correction.l_qd_H)

    def test_reference_difference_removes_fitted_gauge_from_taper(self):
        shifted_delta = replace(
            self.result.model.correction_model,
            gauge_offset_bar=(
                self.result.model.correction_model.gauge_offset_bar + 3.25
            ),
        )
        shifted = PriorCorrectedCoenergyModel(
            prior_model=self.prior_model,
            correction_model=shifted_delta,
            support=self.support(),
        )
        id_A = np.array([-830.0, 780.0, 250.0])
        iq_A = np.array([420.0, 810.0, 760.0])
        baseline = self.result.model.evaluate_correction(id_A, iq_A)
        alternate = shifted.evaluate_correction(id_A, iq_A)
        for field in (
            "coenergy_J",
            "psi_d_Wb",
            "psi_q_Wb",
            "l_dd_H",
            "l_dq_H",
            "l_qd_H",
            "l_qq_H",
        ):
            np.testing.assert_allclose(
                getattr(alternate, field),
                getattr(baseline, field),
                rtol=0.0,
                atol=1.0e-13,
            )

    def test_masked_target_is_not_read_and_anchor_outside_core_is_rejected(self):
        mask = np.array(self.anchor_samples.component_mask, copy=True)
        psi_d = np.array(self.anchor_samples.psi_d_Wb, copy=True)
        psi_q = np.array(self.anchor_samples.psi_q_Wb, copy=True)
        mask[3, 0] = False
        mask[7, 1] = False
        psi_d[3] = np.nan
        psi_q[7] = np.nan
        masked = replace(
            self.anchor_samples,
            component_mask=mask,
            psi_d_Wb=psi_d,
            psi_q_Wb=psi_q,
        )
        result = fit_prior_correction(
            self.prior_model,
            masked,
            self.spec(sparse=True),
            self.quadratures(),
            self.support(),
        )
        self.assertTrue(np.isnan(result.total_residual_psi_d_Wb[3]))
        self.assertTrue(np.isnan(result.total_residual_psi_q_Wb[7]))

        outside = replace(
            self.anchor_samples,
            id_A=np.where(
                np.arange(len(np.asarray(self.anchor_samples.id_A))) == 0,
                800.0,
                np.asarray(self.anchor_samples.id_A),
            ),
        )
        with self.assertRaisesRegex(CoenergyFitError, "unit-weight support core"):
            fit_prior_correction(
                self.prior_model,
                outside,
                self.spec(sparse=True),
                self.quadratures(),
                self.support(),
            )

    def test_support_derivatives_are_zero_at_core_and_outer_boundaries(self):
        support = self.support()
        self.assertIsInstance(support.id_outer_A, tuple)
        evaluated = evaluate_correction_support(
            support,
            np.array([-900.0, -700.0, 0.0, 700.0, 900.0]),
            np.zeros(5),
        )
        np.testing.assert_array_equal(
            evaluated.weight, np.array([0.0, 1.0, 1.0, 1.0, 0.0])
        )
        for derivative in (
            evaluated.d_id_per_A,
            evaluated.d_iq_per_A,
            evaluated.d2_id2_per_A2,
            evaluated.d2_id_iq_per_A2,
            evaluated.d2_iq2_per_A2,
        ):
            np.testing.assert_array_equal(derivative, np.zeros(5))
        with self.assertRaisesRegex(CoenergyFitError, "strictly inside"):
            replace(support, id_core_A=(-900.0, 700.0))
