from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from coenergy_maps.artifacts import load_model
from coenergy_maps.config import load_config
from coenergy_maps.identification import read_vi, identify_flux
from coenergy_maps.pipeline import run
from coenergy_maps.fitting import select_samples, quadratures
from coenergy_maps.coenergy_forward_fit import fit_coenergy_model

ROOT = Path(__file__).resolve().parents[1]


def analytic(id_A, iq_A, ib, pb):
    u, v = np.asarray(id_A)/ib, np.asarray(iq_A)/ib
    return pb*(.7+.3*u+.05*v*v+.04*u*v*v), pb*(.65*v+.1*u*v+.04*u*u*v)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coenergy test ")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        shutil.copytree(ROOT/"examples", self.folder/"examples")

    def config(self, name="motor_a", fit=True):
        return load_config(self.folder/"examples"/f"{name}.toml", fit=fit)

    def test_two_motor_vi_fit_reload_and_off_grid_hessian(self):
        for name in ("motor_a", "motor_b"):
            with self.subTest(name=name):
                cfg = self.config(name)
                summary, output = run(cfg.path, fit=True)
                self.assertEqual(summary["status"], "COMPLETE")
                self.assertEqual((summary["input_rows"], summary["calculated"]), (221, 117))
                model = load_model(output/"prior_model.npz")
                ib, pb = cfg.fit_spec.i_base_A, cfg.fit_spec.psi_base_Wb
                u = np.array([-.93, -.47, .13, .83, 0])
                v = np.array([.03, -.29, .58, -.99, 0])
                value = model.evaluate(ib*u, ib*v)
                expected = analytic(ib*u, ib*v, ib, pb)
                np.testing.assert_allclose(value.psi_d_Wb, expected[0], rtol=0, atol=2e-12)
                np.testing.assert_allclose(value.psi_q_Wb, expected[1], rtol=0, atol=2e-12)
                np.testing.assert_allclose(value.l_dd_H, pb/ib*(.3+.04*v*v), rtol=0, atol=2e-12)
                np.testing.assert_allclose(value.l_dq_H, pb/ib*(.1*v+.08*u*v), rtol=0, atol=2e-12)
                np.testing.assert_allclose(value.l_qq_H, pb/ib*(.65+.1*u+.04*u*u), rtol=0, atol=2e-12)
                np.testing.assert_array_equal(value.l_dq_H, value.l_qd_H)
                residual = pd.read_csv(output/"fit_residuals.csv")
                self.assertTrue(residual.loc[~residual.psi_q_observed, "error_q_Wb"].isna().all())
                settings = json.loads((output/"prior_settings.json").read_text())
                self.assertIsNone(settings["inverse_valid_region"])

    def test_source_reference_fixture(self):
        cfg = self.config()
        points, _ = identify_flux(read_vi(cfg), cfg)
        _, training = select_samples(points, cfg.fit_spec)
        result = fit_coenergy_model(training, cfg.fit_spec, quadratures(cfg.fit_spec, cfg.quadrature_order))
        with np.load(ROOT/"tests/fixtures/source_reference.npz", allow_pickle=False) as reference:
            np.testing.assert_allclose(points[["id_A", "iq_A", "psi_d_Wb", "psi_q_Wb"]], reference["points"], rtol=0, atol=2e-14)
            evaluation = result.model.evaluate(reference["id_A"], reference["iq_A"])
            for field in evaluation.__dataclass_fields__:
                np.testing.assert_allclose(getattr(evaluation, field), reference[field], rtol=2e-11, atol=2e-12)

    def test_malformed_rows_preserve_good_pairs_and_identity(self):
        cfg = self.config()
        rows = read_vi(cfg)
        rows.loc[1, "vq_V"] = np.nan
        rows.loc[3, "rpm"] = 0
        rows = rows.drop(index=6).reset_index(drop=True)
        points, diagnostics = identify_flux(rows, cfg)
        self.assertEqual(len(diagnostics), 220)
        self.assertEqual(points.status.eq("CALCULATED").sum(), 114)
        self.assertEqual(set(points.loc[points.status.ne("CALCULATED"), "reason"]),
                         {"REQUIRED_VALUE_NONFINITE", "ZERO_SPEED_PRESENT", "PAIR_INCOMPLETE_OR_AMBIGUOUS"})
        self.assertEqual(diagnostics.observation_id.eq("").sum(), 0)
        self.assertEqual(points.iloc[1].source_row_indices, "1;2")

    def test_ambiguous_repeated_acquisition_requires_explicit_pair_id(self):
        cfg = self.config()
        rows = read_vi(cfg).iloc[[1, 2]].copy()
        repeated = pd.concat([rows, rows], ignore_index=True)
        points, _ = identify_flux(repeated, cfg)
        self.assertEqual(points.iloc[0].reason, "PAIR_INCOMPLETE_OR_AMBIGUOUS")
        repeated["pair_id"] = ["first", "first", "second", "second"]
        points, _ = identify_flux(repeated, cfg)
        self.assertTrue(points.status.eq("CALCULATED").all())
        self.assertEqual(len(points), 2)

    def test_achieved_coordinates_and_speed_deviations_are_diagnostics(self):
        cfg = self.config()
        rows = read_vi(cfg).iloc[[1, 2]].copy()
        rows.loc[1, "id_A"] += 2.0
        rows.loc[2, "iq_A"] -= 1.0
        rows.loc[2, "rpm"] += 20.0
        points, _ = identify_flux(rows, cfg)
        p = points.iloc[0]
        self.assertEqual(p.status, "CALCULATED")
        self.assertEqual((p.id_A, p.iq_A), (-99, 13))
        self.assertEqual(p.rpm_difference, 20)
        self.assertEqual(p.mirror_id_difference_A, 2)
        self.assertEqual(p.mirror_iq_sum_A, -1)

    def test_single_resistance_and_unobserved_q(self):
        cfg = self.config()
        rows = read_vi(cfg).iloc[[0]].copy()
        rows.loc[0, "iq_A"] = -.25
        rows.loc[0, "vq_V"] -= cfg.resistance*.25
        rows.loc[0, "vd_V"] = np.nan  # not used in the d-only equation
        points, _ = identify_flux(rows, cfg)
        p = points.iloc[0]
        self.assertEqual(p.status, "CALCULATED")
        self.assertAlmostEqual(p.psi_d_Wb, .048)
        self.assertEqual(p.iq_A, .25)
        self.assertFalse(p.psi_q_observed)
        self.assertFalse(p.psi_q_structural)
        self.assertEqual(p.weight_q, 0)
        points, _ = identify_flux(rows, replace(cfg, resistance=None))
        self.assertEqual(points.iloc[0].reason, "SINGLE_REQUIRES_STATOR_RESISTANCE")

    def test_mirror_needs_no_resistance(self):
        cfg = self.config()
        points, _ = identify_flux(read_vi(cfg), replace(cfg, resistance=None))
        self.assertEqual(points.status.eq("CALCULATED").sum(), 104)

    def test_outside_domain_rows_are_saved_and_excluded(self):
        cfg = self.config()
        points, _ = identify_flux(read_vi(cfg), cfg)
        points.loc[0, "id_A"] = -101
        selected, sample = select_samples(points, cfg.fit_spec)
        self.assertEqual(selected.iloc[0].fit_reason, "OUTSIDE_MODEL_DOMAIN")
        self.assertEqual(len(sample.id_A), 116)

    def test_fit_failure_retains_identification_and_reason(self):
        cfg = self.config()
        rows = pd.read_csv(cfg.input_csv).iloc[[0]]
        rows.to_csv(cfg.input_csv, index=False)
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            run(cfg.path, fit=True)
        self.assertTrue((cfg.output_dir/"jmag_flux_samples.csv").exists())
        self.assertTrue((cfg.output_dir/"input_diagnostics.csv").exists())
        self.assertEqual(json.loads((cfg.output_dir/"summary.json").read_text())["status"], "FAILED")

    def test_output_is_never_overwritten(self):
        cfg = self.config("identify_flux", fit=False)
        cfg.output_dir.mkdir(parents=True)
        sentinel = cfg.output_dir/"original.txt"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(ValueError, "empty directory"):
            run(cfg.path, fit=False)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(len(list(cfg.output_dir.iterdir())), 1)

    def test_identify_only_has_no_fit_dependency(self):
        summary, output = run(self.config("identify_flux", fit=False).path, fit=False)
        self.assertEqual(summary["status"], "COMPLETE")
        self.assertTrue((output/"flux_samples.csv").exists())
        self.assertFalse((output/"prior_model.npz").exists())

    def test_bad_schema_and_settings_report_errors(self):
        cfg = self.config()
        path = cfg.path
        original = path.read_text()
        for before, after, reason in (("pole_pairs = 3", "pole_pairs = 0", "pole_pairs"),
                                     ("quadrature_order = 4", "quadrature_order = 2", "quadrature_order"),
                                     ("roughness_weight", "roughnes_weight", "unknown fit")):
            path.write_text(original.replace(before, after))
            with self.assertRaisesRegex(ValueError, reason):
                load_config(path, fit=True)
        path.write_text(original)
        pd.DataFrame({"something": [1]}).to_csv(cfg.input_csv, index=False)
        with self.assertRaisesRegex(ValueError, "missing columns"):
            read_vi(cfg)

    def test_cli_outside_project_and_copy_has_no_parent_imports(self):
        copied = self.folder/"standalone"
        shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns(".venv", "output", "__pycache__"))
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        for script, cfg in (("run_fit_jmag.py", "motor_a.toml"), ("run_identify_flux.py", "identify_flux.toml")):
            result = subprocess.run([sys.executable, "-E", str(copied/script), "--config", str(copied/"examples"/cfg)],
                                    cwd=self.folder, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        probe = "import sys,coenergy_maps; print(coenergy_maps.__file__); assert not any('code_flux' in str(m) for m in sys.modules)"
        result = subprocess.run([sys.executable, "-E", "-c", probe], cwd=copied, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(copied), result.stdout)


if __name__ == "__main__":
    unittest.main()
