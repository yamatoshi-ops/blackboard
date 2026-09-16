from dataclasses import FrozenInstanceError, is_dataclass, replace
import unittest

import numpy as np


from coenergy_maps.coenergy_forward_fit import (
    COEFFICIENT_ORDER,
    CoenergyEvaluation,
    CoenergyFitError,
    CoenergyFitResult,
    CoenergyFitSpec,
    CoenergyFullBasisCensus,
    CoenergyModel,
    CoenergyQuadratures,
    CoenergySamples,
    CoenergySystemDiagnostics,
    _analysis_problem,
    _matrix_sha256,
    analyze_coenergy_fit_system,
    analyze_coenergy_full_basis,
    fit_coenergy_model,
)


class CoenergyForwardFitTest(unittest.TestCase):
    i_base_A = 1000.0
    psi_base_Wb = 0.2
    coefficients = {
        "a1": 0.7,
        "a2": 0.3,
        "a3": 0.65,
        "g": 0.05,
        "h": 0.02,
    }

    @staticmethod
    def mesh(u_axis, v_axis):
        u, v = np.meshgrid(u_axis, v_axis, indexing="ij")
        return u.reshape(-1), v.reshape(-1)

    def flux(self, u, v_signed, *, coefficients=None):
        values = self.coefficients if coefficients is None else coefficients
        v = np.abs(v_signed)
        psi_d_bar = (
            values["a1"]
            + values["a2"] * u
            + values["g"] * v**2
            + 2.0 * values["h"] * u * v**2
        )
        psi_q_bar = np.sign(v_signed) * (
            values["a3"] * v
            + 2.0 * values["g"] * u * v
            + 2.0 * values["h"] * u**2 * v
        )
        return self.psi_base_Wb * psi_d_bar, self.psi_base_Wb * psi_q_bar

    def hessian(self, u, v_signed, *, coefficients=None):
        values = self.coefficients if coefficients is None else coefficients
        v = np.abs(v_signed)
        sign = np.sign(v_signed)
        scale = self.psi_base_Wb / self.i_base_A
        l_dd = scale * (values["a2"] + 2.0 * values["h"] * v**2)
        l_dq = scale * sign * (
            2.0 * values["g"] * v + 4.0 * values["h"] * u * v
        )
        l_qq = scale * (
            values["a3"]
            + 2.0 * values["g"] * u
            + 2.0 * values["h"] * u**2
        )
        return l_dd, l_dq, l_qq

    def samples(self, *, coefficients=None):
        u, v = self.mesh(np.linspace(-1.0, 1.0, 13), np.linspace(0.0, 1.0, 9))
        psi_d, psi_q = self.flux(u, v, coefficients=coefficients)
        return CoenergySamples(
            id_A=self.i_base_A * u,
            iq_A=self.i_base_A * v,
            psi_d_Wb=psi_d,
            psi_q_Wb=psi_q,
            component_mask=np.ones((len(u), 2), dtype=bool),
            component_weight=np.ones((len(u), 2), dtype=float),
        )

    def quadratures(self):
        support_u, support_v = self.mesh(
            np.linspace(-1.0, 1.0, 9), np.linspace(0.0, 1.0, 7)
        )
        span_u, span_v = self.mesh(
            np.linspace(-1.0, 1.0, 11), np.linspace(0.0, 1.0, 8)
        )
        gauge_u, gauge_v = self.mesh(
            np.linspace(-1.0, 1.0, 7), np.linspace(0.0, 1.0, 6)
        )
        roughness_u, roughness_v = self.mesh(
            np.linspace(-1.0, 1.0, 10), np.linspace(0.0, 1.0, 7)
        )
        return CoenergyQuadratures(
            support_u=support_u,
            support_v=support_v,
            span_u=span_u,
            span_v=span_v,
            span_weight=1.0 + 0.1 * (span_u + 1.0) + 0.05 * span_v,
            gauge_u=gauge_u,
            gauge_v=gauge_v,
            gauge_weight=1.0 + 0.2 * gauge_v,
            roughness_u=roughness_u,
            roughness_v=roughness_v,
            roughness_weight=np.ones(len(roughness_u)),
        )

    def spec(self, *, solver="dense_gelsd", roughness=0.0):
        sparse_solver = solver == "sparse_lsmr"
        return CoenergyFitSpec(
            i_base_A=self.i_base_A,
            psi_base_Wb=self.psi_base_Wb,
            u_breakpoints=(-1.0, -0.5, 0.0, 0.5, 1.0),
            v_breakpoints=(0.0, 0.25, 0.5, 0.75, 1.0),
            solver=solver,
            roughness_weight=roughness,
            solver_tolerance=1.0e-13 if sparse_solver else None,
            solver_max_iterations=10000 if sparse_solver else None,
            active_basis_tolerance=1.0e-14,
            rank_tolerance=None,
        )

    def test_public_types_are_frozen_dataclasses(self):
        for value_type in (
            CoenergySamples,
            CoenergyFitSpec,
            CoenergyQuadratures,
            CoenergyEvaluation,
            CoenergyModel,
            CoenergyFitResult,
        ):
            self.assertTrue(is_dataclass(value_type))
            self.assertTrue(value_type.__dataclass_params__.frozen)
        spec = self.spec()
        with self.assertRaises(FrozenInstanceError):
            spec.i_base_A = 1.0
        self.assertEqual(0.0, spec.ridge_weight)
        self.assertEqual("u-major/v-minor", COEFFICIENT_ORDER)

    def test_exact_cross_saturation_recovery_and_analytic_hessian(self):
        result = fit_coenergy_model(
            self.samples(), self.spec(), self.quadratures()
        )
        u, v_positive = self.mesh(
            np.linspace(-0.9, 0.9, 8), np.linspace(0.0, 0.9, 7)
        )
        v = np.concatenate([v_positive, -v_positive])
        u = np.concatenate([u, u])
        expected_d, expected_q = self.flux(u, v)
        expected_dd, expected_dq, expected_qq = self.hessian(u, v)
        evaluation = result.model.evaluate(
            self.i_base_A * u, self.i_base_A * v
        )
        np.testing.assert_allclose(
            evaluation.psi_d_Wb, expected_d, rtol=0.0, atol=2.0e-14
        )
        np.testing.assert_allclose(
            evaluation.psi_q_Wb, expected_q, rtol=0.0, atol=2.0e-14
        )
        np.testing.assert_allclose(
            evaluation.l_dd_H, expected_dd, rtol=0.0, atol=2.0e-16
        )
        np.testing.assert_allclose(
            evaluation.l_dq_H, expected_dq, rtol=0.0, atol=2.0e-16
        )
        np.testing.assert_allclose(
            evaluation.l_qd_H, expected_dq, rtol=0.0, atol=2.0e-16
        )
        np.testing.assert_allclose(
            evaluation.l_qq_H, expected_qq, rtol=0.0, atol=2.0e-16
        )
        self.assertLess(
            result.metrics["training_residual"]["psi_d_rms_Wb"], 1.0e-14
        )
        self.assertLess(
            result.metrics["training_residual"]["psi_q_rms_Wb"], 1.0e-14
        )
        self.assertEqual(0, result.metrics["basis"]["inactive_basis_count"])
        self.assertIsNone(result.metrics["basis"]["inactive_support_max"])
        self.assertGreater(
            result.metrics["basis"]["active_support_min"],
            result.metrics["basis"]["active_basis_tolerance"],
        )
        with self.assertRaises(ValueError):
            result.model.raw_sat_coefficients()[0] = 0.0

    def test_negative_iq_extension_and_q_axis_neumann_are_exact(self):
        result = fit_coenergy_model(
            self.samples(), self.spec(), self.quadratures()
        )
        id_A = np.array([-750.0, 0.0, 640.0])
        iq_A = np.array([180.0, 390.0, 710.0])
        plus = result.model.evaluate(id_A, iq_A)
        minus = result.model.evaluate(id_A, -iq_A)
        np.testing.assert_array_equal(plus.coenergy_J, minus.coenergy_J)
        np.testing.assert_array_equal(plus.psi_d_Wb, minus.psi_d_Wb)
        np.testing.assert_array_equal(plus.psi_q_Wb, -np.asarray(minus.psi_q_Wb))
        axis = result.model.evaluate(id_A, np.zeros_like(id_A))
        np.testing.assert_array_equal(axis.psi_q_Wb, np.zeros_like(id_A))
        np.testing.assert_array_equal(axis.l_dq_H, np.zeros_like(id_A))
        self.assertLess(
            result.metrics["basis"]["q_axis_neumann_basis_max_abs"],
            2.0e-14,
        )

    def test_span_support_and_gauge_contracts_are_separate_and_hashed(self):
        quadratures = self.quadratures()
        result = fit_coenergy_model(self.samples(), self.spec(), quadratures)
        basis = result.metrics["basis"]
        hashes = result.metrics["math_contract_hashes"]
        self.assertEqual(len(quadratures.support_u), basis["support_probe_count"])
        self.assertEqual(len(quadratures.span_u), basis["span_quadrature_count"])
        self.assertEqual(
            "Q_span_distinct_from_Q_gauge",
            basis["low_order_span_quadrature"],
        )
        self.assertLess(basis["low_order_projection_max_abs"], 2.0e-14)
        self.assertNotEqual(
            hashes["span_quadrature_sha256"],
            hashes["gauge_quadrature_sha256"],
        )
        self.assertEqual(64, len(hashes["aggregate_sha256"]))
        for required in (
            "q_neumann_transform_sha256",
            "active_transform_sha256",
            "low_order_polynomial_matrix_sha256",
            "low_order_constraint_matrix_sha256",
            "low_order_transform_sha256",
            "roughness_quadrature_sha256",
        ):
            self.assertEqual(64, len(hashes[required]))
        gauge = result.model.evaluate(
            self.i_base_A * np.asarray(quadratures.gauge_u),
            self.i_base_A * np.asarray(quadratures.gauge_v),
        )
        normalized_mean = np.average(
            np.asarray(gauge.coenergy_J)
            / (self.i_base_A * self.psi_base_Wb),
            weights=np.asarray(quadratures.gauge_weight),
        )
        self.assertAlmostEqual(0.0, float(normalized_mean), places=14)

    def test_dense_and_equilibrated_lsmr_predictions_match(self):
        samples = self.samples()
        quadratures = self.quadratures()
        dense = fit_coenergy_model(samples, self.spec(), quadratures)
        iterative = fit_coenergy_model(
            samples, self.spec(solver="sparse_lsmr"), quadratures
        )
        np.testing.assert_allclose(
            iterative.prediction_psi_d_Wb,
            dense.prediction_psi_d_Wb,
            rtol=0.0,
            atol=4.0e-13,
        )
        np.testing.assert_allclose(
            iterative.prediction_psi_q_Wb,
            dense.prediction_psi_q_Wb,
            rtol=0.0,
            atol=4.0e-13,
        )
        self.assertEqual(
            dense.metrics["linear_system"]["matrix_sha256"],
            iterative.metrics["linear_system"]["matrix_sha256"],
        )
        self.assertEqual(
            dense.metrics["math_contract_hashes"],
            iterative.metrics["math_contract_hashes"],
        )
        self.assertIn(iterative.metrics["solver"]["istop"], (1, 2))

    def test_masked_target_is_not_read(self):
        samples = self.samples()
        mask = np.array(samples.component_mask, copy=True)
        mask[4, 0] = False
        mask[8, 1] = False
        psi_d = np.array(samples.psi_d_Wb, copy=True)
        psi_q = np.array(samples.psi_q_Wb, copy=True)
        psi_d[4] = np.nan
        psi_q[8] = np.nan
        result = fit_coenergy_model(
            replace(
                samples,
                psi_d_Wb=psi_d,
                psi_q_Wb=psi_q,
                component_mask=mask,
            ),
            self.spec(),
            self.quadratures(),
        )
        self.assertTrue(np.isnan(result.residual_psi_d_Wb[4]))
        self.assertTrue(np.isnan(result.residual_psi_q_Wb[8]))

    def test_nonreciprocal_field_cannot_be_fit_exactly(self):
        samples = self.samples()
        u = np.asarray(samples.id_A) / self.i_base_A
        v = np.asarray(samples.iq_A) / self.i_base_A
        # This perturbation remains odd in Iq and is exactly zero on Iq=0;
        # its nonzero curl, not a q-axis boundary violation, prevents exact fit.
        nonreciprocal_q = np.asarray(samples.psi_q_Wb) + 0.02 * u * v
        result = fit_coenergy_model(
            replace(samples, psi_q_Wb=nonreciprocal_q),
            self.spec(),
            self.quadratures(),
        )
        combined_rms = np.hypot(
            result.metrics["training_residual"]["psi_d_rms_Wb"],
            result.metrics["training_residual"]["psi_q_rms_Wb"],
        )
        self.assertGreater(combined_rms, 1.0e-4)

    def test_non_psd_manufactured_surface_is_exposed_by_hessian(self):
        coefficients = dict(self.coefficients, a2=-0.2, g=0.0, h=0.0)
        result = fit_coenergy_model(
            self.samples(coefficients=coefficients),
            self.spec(),
            self.quadratures(),
        )
        evaluation = result.model.evaluate(0.0, 400.0)
        self.assertLess(evaluation.l_dd_H, 0.0)
        self.assertGreater(evaluation.l_qq_H, 0.0)

    def test_third_derivative_roughness_is_analytic_and_sat_only(self):
        cross_result = fit_coenergy_model(
            self.samples(),
            self.spec(roughness=1.0e-10),
            self.quadratures(),
        )
        self.assertGreater(
            cross_result.metrics["regularization"]["roughness_integral"], 0.0
        )
        pure = {"a1": 0.7, "a2": 0.3, "a3": 0.65, "g": 0.0, "h": 0.0}
        pure_result = fit_coenergy_model(
            self.samples(coefficients=pure),
            self.spec(roughness=1.0e3),
            self.quadratures(),
        )
        self.assertLess(
            pure_result.metrics["training_residual"]["psi_d_rms_Wb"], 1.0e-13
        )
        self.assertLess(
            pure_result.metrics["training_residual"]["psi_q_rms_Wb"], 1.0e-13
        )
        self.assertEqual(
            "sat_only",
            pure_result.metrics["regularization"]["regularized_components"],
        )

    def test_valid_domain_support_probe_does_not_hide_rank_deficiency(self):
        u, v = self.mesh(np.array([-1.0, 1.0]), np.array([0.0, 1.0]))
        psi_d, psi_q = self.flux(u, v)
        sparse_samples = CoenergySamples(
            self.i_base_A * u,
            self.i_base_A * v,
            psi_d,
            psi_q,
            np.ones((len(u), 2), dtype=bool),
            np.ones((len(u), 2), dtype=float),
        )
        with self.assertRaisesRegex(CoenergyFitError, "rank deficient"):
            fit_coenergy_model(
                sparse_samples, self.spec(), self.quadratures()
            )

    def test_zero_support_basis_is_excluded_from_active_transform(self):
        u, v = self.mesh(
            np.linspace(-0.4, 0.4, 13), np.linspace(0.0, 0.45, 9)
        )
        psi_d, psi_q = self.flux(u, v)
        samples = CoenergySamples(
            self.i_base_A * u,
            self.i_base_A * v,
            psi_d,
            psi_q,
            np.ones((len(u), 2), dtype=bool),
            np.ones((len(u), 2), dtype=float),
        )
        domain_u, domain_v = self.mesh(
            np.linspace(-0.45, 0.45, 9), np.linspace(0.0, 0.5, 7)
        )
        quadratures = CoenergyQuadratures(
            support_u=domain_u,
            support_v=domain_v,
            span_u=domain_u,
            span_v=domain_v,
            span_weight=np.ones(len(domain_u)),
            gauge_u=domain_u,
            gauge_v=domain_v,
            gauge_weight=np.ones(len(domain_u)),
            roughness_u=domain_u,
            roughness_v=domain_v,
            roughness_weight=np.ones(len(domain_u)),
        )
        result = fit_coenergy_model(samples, self.spec(), quadratures)
        basis = result.metrics["basis"]
        active = set(basis["active_basis_indices"])
        inactive = set(basis["inactive_basis_indices"])
        self.assertGreater(len(inactive), 0)
        self.assertTrue(active.isdisjoint(inactive))
        self.assertEqual(
            set(range(basis["q_neumann_free_basis_count"])), active | inactive
        )
        self.assertEqual(len(active), basis["active_basis_count"])
        self.assertGreater(
            basis["active_support_min"], basis["active_basis_tolerance"]
        )
        self.assertLessEqual(
            basis["inactive_support_max"], basis["active_basis_tolerance"]
        )
        self.assertEqual(
            64,
            len(
                result.metrics["math_contract_hashes"][
                    "active_support_vector_sha256"
                ]
            ),
        )

    def test_invalid_domain_and_solver_contracts_are_rejected(self):
        with self.assertRaisesRegex(CoenergyFitError, "start at exactly zero"):
            fit_coenergy_model(
                self.samples(),
                replace(self.spec(), v_breakpoints=(0.1, 0.5, 1.0)),
                self.quadratures(),
            )
        with self.assertRaisesRegex(CoenergyFitError, "requires an explicit"):
            fit_coenergy_model(
                self.samples(),
                replace(self.spec(), solver="sparse_lsmr"),
                self.quadratures(),
            )
        with self.assertRaisesRegex(CoenergyFitError, "outside"):
            fit_coenergy_model(
                replace(
                    self.samples(),
                    id_A=np.append(np.asarray(self.samples().id_A)[:-1], 1001.0),
                ),
                self.spec(),
                self.quadratures(),
            )

    def test_negative_iq_fit_sample_is_rejected_but_evaluation_is_extended(self):
        samples = self.samples()
        iq_A = np.array(samples.iq_A, copy=True)
        iq_A[3] = -abs(iq_A[3]) if iq_A[3] != 0.0 else -1.0
        with self.assertRaisesRegex(
            CoenergyFitError,
            "Iq >= 0; negative-Iq values are generated only by the model extension",
        ):
            fit_coenergy_model(
                replace(samples, iq_A=iq_A), self.spec(), self.quadratures()
            )

        result = fit_coenergy_model(samples, self.spec(), self.quadratures())
        plus = result.model.evaluate(120.0, 340.0)
        minus = result.model.evaluate(120.0, -340.0)
        self.assertEqual(plus.psi_d_Wb, minus.psi_d_Wb)
        self.assertEqual(plus.psi_q_Wb, -minus.psi_q_Wb)

    def test_diagonal_matrix_weight_is_bit_identical_to_legacy_weight(self):
        samples = self.samples()
        count = len(samples.id_A)
        legacy_weight = np.column_stack(
            [
                np.linspace(0.5, 1.5, count),
                np.linspace(1.75, 0.75, count),
            ]
        )
        samples = replace(samples, component_weight=legacy_weight)
        legacy = fit_coenergy_model(
            samples, self.spec(), self.quadratures()
        )
        diagonal = np.zeros((len(samples.id_A), 2, 2), dtype=float)
        diagonal[:, 0, 0] = np.asarray(samples.component_weight)[:, 0]
        diagonal[:, 1, 1] = np.asarray(samples.component_weight)[:, 1]
        matrix = fit_coenergy_model(
            replace(
                samples,
                component_weight=None,
                component_weight_matrix=diagonal,
            ),
            self.spec(),
            self.quadratures(),
        )
        np.testing.assert_array_equal(
            matrix.model.low_order_coefficients,
            legacy.model.low_order_coefficients,
        )
        np.testing.assert_array_equal(
            matrix.model.sat_coefficients, legacy.model.sat_coefficients
        )
        np.testing.assert_array_equal(
            matrix.prediction_psi_d_Wb, legacy.prediction_psi_d_Wb
        )
        np.testing.assert_array_equal(
            matrix.prediction_psi_q_Wb, legacy.prediction_psi_q_Wb
        )
        self.assertEqual(matrix.metrics, legacy.metrics)

    def test_matrix_weight_validation_is_strict(self):
        samples = self.samples()
        count = len(samples.id_A)
        identity = np.tile(np.eye(2), (count, 1, 1))
        with self.assertRaisesRegex(CoenergyFitError, "mutually exclusive"):
            fit_coenergy_model(
                replace(samples, component_weight_matrix=identity),
                self.spec(),
                self.quadratures(),
            )
        mask = np.array(samples.component_mask, copy=True)
        mask[0, 1] = False
        with self.assertRaisesRegex(CoenergyFitError, "both flux components"):
            fit_coenergy_model(
                replace(
                    samples,
                    component_weight=None,
                    component_weight_matrix=identity,
                    component_mask=mask,
                ),
                self.spec(),
                self.quadratures(),
            )
        asymmetric = np.array(identity, copy=True)
        asymmetric[0, 0, 1] = 0.25
        with self.assertRaisesRegex(CoenergyFitError, "exactly symmetric"):
            fit_coenergy_model(
                replace(
                    samples,
                    component_weight=None,
                    component_weight_matrix=asymmetric,
                ),
                self.spec(),
                self.quadratures(),
            )
        indefinite = np.array(identity, copy=True)
        indefinite[0] = np.array([[1.0, 2.0], [2.0, 1.0]])
        with self.assertRaisesRegex(CoenergyFitError, "semidefinite"):
            fit_coenergy_model(
                replace(
                    samples,
                    component_weight=None,
                    component_weight_matrix=indefinite,
                ),
                self.spec(),
                self.quadratures(),
            )

    def test_full_basis_census_returns_rank_deficiency_without_fitting(self):
        census = analyze_coenergy_full_basis(
            self.samples(), self.spec(), self.quadratures()
        )
        self.assertIsInstance(census, CoenergyFullBasisCensus)
        self.assertEqual(0, census.data_nullity_before_regularization)
        self.assertEqual(
            census.total_basis_count - census.symmetry_tied_basis_count + 4,
            census.exact_constraint_count,
        )
        self.assertEqual(4, census.low_order_projection_rank)
        self.assertEqual(64, len(census.data_design_matrix_sha256))
        self.assertEqual(64, len(census.low_order_projection_matrix_sha256))
        with self.assertRaises(ValueError):
            census.singular_values[0] = 0.0

        u, v = self.mesh(np.array([-1.0, 1.0]), np.array([0.0, 1.0]))
        psi_d, psi_q = self.flux(u, v)
        sparse_samples = CoenergySamples(
            self.i_base_A * u,
            self.i_base_A * v,
            psi_d,
            psi_q,
            np.ones((len(u), 2), dtype=bool),
            np.ones((len(u), 2), dtype=float),
        )
        deficient = analyze_coenergy_full_basis(
            sparse_samples, self.spec(), self.quadratures()
        )
        self.assertGreater(deficient.data_nullity_before_regularization, 0)

    def test_effective_dof_matches_direct_hat_trace_and_graph_is_connected(self):
        samples = self.samples()
        quadratures = self.quadratures()
        spec = self.spec(roughness=1.0e-4)
        diagnostics = analyze_coenergy_fit_system(
            samples, spec, quadratures
        )
        self.assertIsInstance(diagnostics, CoenergySystemDiagnostics)
        self.assertEqual(1, diagnostics.active_support_graph_component_count)
        problem = _analysis_problem(
            samples, spec, quadratures, prune_inactive=True
        )
        data = problem["weighted_data_design"]
        system = problem["system_design"]
        fitted = fit_coenergy_model(samples, spec, quadratures)
        self.assertEqual(
            fitted.metrics["linear_system"]["matrix_sha256"],
            _matrix_sha256(system),
        )
        direct_hat = data @ np.linalg.solve(system.T @ system, data.T)
        self.assertAlmostEqual(
            float(np.trace(direct_hat)),
            diagnostics.effective_degrees_of_freedom,
            places=10,
        )
        unregularized = analyze_coenergy_fit_system(
            samples, self.spec(), quadratures
        )
        expected_rank = np.linalg.matrix_rank(
            _analysis_problem(
                samples,
                self.spec(),
                quadratures,
                prune_inactive=True,
            )["weighted_data_design"]
        )
        self.assertEqual(
            float(expected_rank),
            unregularized.effective_degrees_of_freedom,
        )

        count = len(samples.id_A)
        coupled = np.tile(
            np.array([[1.2, -0.25], [-0.25, 0.8]]),
            (count, 1, 1),
        )
        matrix_samples = replace(
            samples,
            component_weight=None,
            component_weight_matrix=coupled,
        )
        matrix_problem = _analysis_problem(
            matrix_samples, spec, quadratures, prune_inactive=True
        )
        matrix_fit = fit_coenergy_model(matrix_samples, spec, quadratures)
        self.assertEqual(
            matrix_fit.metrics["linear_system"]["matrix_sha256"],
            _matrix_sha256(matrix_problem["system_design"]),
        )


if __name__ == "__main__":
    unittest.main()
