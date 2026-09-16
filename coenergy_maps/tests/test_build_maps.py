import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from coenergy_maps.artifacts import load_model, save_model
from coenergy_maps.pipeline import run as run_vi
from coenergy_maps.build_pipeline import run
from coenergy_maps.map_config import load_map_config, correction_config
from coenergy_maps.correction import read_samples, select_anchors
from coenergy_maps.maps import DirectInverse, PublicLut

ROOT = Path(__file__).resolve().parents[1]


class BuildMapsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="stage3 tests ")
        cls.root = Path(cls.temp.name)
        shutil.copytree(ROOT/"examples", cls.root/"examples")
        cls.results = {}
        for motor in ("a", "b"):
            run_vi(cls.root/"examples"/f"motor_{motor}.toml", fit=True)
            run_vi(cls.root/"examples"/f"identify_correction_{motor}.toml", fit=False)
            cls.results[motor] = run(cls.root/"examples"/f"build_maps_{motor}.toml")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_two_motors_nonzero_delta_roundtrip_and_independent_reload(self):
        for name, ib, pb in (("a", 100, .12), ("b", 40, .035)):
            with self.subTest(motor=name):
                summary, output = self.results[name]
                self.assertEqual(summary["status"], "COMPLETE")
                self.assertEqual(summary["fit_observations"], 88)
                self.assertEqual(summary["forward"]["grid_shape"], [17, 25])
                self.assertEqual(summary["inverse"]["grid_shape"], [31, 31])
                self.assertGreater(summary["roundtrip"]["valid_count"], 0)
                self.assertGreater(summary["inverse"]["extrapolated_nodes"], 0)
                model = load_model(output/"final_model.npz")
                saved_prior = json.loads((output/"prior_settings.json").read_text())
                self.assertTrue((output/saved_prior["model_file"]).exists())
                self.assertTrue((output/saved_prior["observations_file"]).exists())
                self.assertEqual((output/"prior_model.npz").read_bytes(),
                    (self.root/f"output/motor_{name}/prior_model.npz").read_bytes())
                u, v = np.array([-.51, .13, .42]), np.array([.23, -.31, .57])
                prior = model.prior_model.evaluate(ib*u, ib*v)
                value = model.evaluate(ib*u, ib*v)
                np.testing.assert_allclose(value.psi_d_Wb-prior.psi_d_Wb, pb*(.002+.003*u+.0008*u*v*v), rtol=0, atol=2e-12)
                np.testing.assert_allclose(value.psi_q_Wb-prior.psi_q_Wb, pb*(-.002*v+.0008*u*u*v), rtol=0, atol=2e-12)
                original = load_model(self.root/f"output/motor_{name}/prior_model.npz")
                for field in original.__dataclass_fields__:
                    np.testing.assert_array_equal(getattr(original, field), getattr(model.prior_model, field))
                # The final NPZ is self-contained, including the taper support.
                with tempfile.TemporaryDirectory() as folder:
                    saved = Path(folder)/"standalone.npz"
                    save_model(saved, model)
                    restored = load_model(saved)
                    x, y = ib*np.array([-.97, -.83, .28, .82]), ib*np.array([0, -.82, .31, .94])
                    a, b = model.evaluate(x, y), restored.evaluate(x, y)
                    for field in a.__dataclass_fields__:
                        np.testing.assert_array_equal(getattr(a, field), getattr(b, field))
                residual = pd.read_csv(output/"correction_residuals.csv")
                self.assertTrue(residual.loc[~residual.fit_mask_q, "final_error_q_Wb"].isna().all())
                self.assertLess(summary["residuals_Wb"]["final_d"]["max_abs"], 2e-12)
                self.assertGreater(summary["residuals_Wb"]["prior_d"]["max_abs"], pb*.001)

    def test_public_rounding_orientation_and_inverse_source(self):
        _, output = self.results["a"]
        samples = pd.read_csv(output/"inverse_fit_samples.csv", float_precision="round_trip")
        for name in ("psi_d", "psi_q"):
            table = pd.read_csv(output/f"forward_flux_map_{name}.csv", index_col=0, float_precision="round_trip")
            self.assertEqual(table.shape, (17, 25))
            np.testing.assert_array_equal(table.to_numpy().ravel(), samples[name+"_Wb"])
            np.testing.assert_array_equal(table.to_numpy(), np.round(table.to_numpy(), 8))
        for name in ("id", "iq"):
            table = pd.read_csv(output/f"inverse_flux_map_{name}.csv", index_col=0, float_precision="round_trip")
            self.assertEqual(table.index.name, r"pq\pd")
            self.assertEqual(table.shape, (31, 31))
            np.testing.assert_array_equal(table.to_numpy(), np.round(table.to_numpy(), 6))
            np.testing.assert_array_equal(table.columns.astype(float), np.round(table.columns.astype(float), 6))
            if name == "iq":
                np.testing.assert_array_equal(table.loc[0.].to_numpy(), 0)
        validity = pd.read_csv(output/"inverse_validity.csv", index_col=0)
        self.assertTrue(np.isin(validity, [0, 1]).all())
        self.assertTrue((validity == 0).any().any())

    def test_masks_nonfinite_outside_core_and_negative_q_are_local(self):
        cfg = load_map_config(self.root/"examples/build_maps_a.toml")
        prior = load_model(cfg.inputs["prior_model"])
        spec, _, support = correction_config(cfg.raw)
        frame = read_samples(cfg.inputs["flux_samples"])
        frame["psi_q_Wb"] = frame.psi_q_Wb.astype(object)
        frame.loc[0, "psi_q_Wb"] = "garbage"  # d-only row remains usable
        frame.loc[1, "psi_d_Wb"] = np.nan  # q component remains usable
        frame.loc[2, "weight_d"] = -1
        frame.loc[2, "weight_q"] = 0
        frame.loc[3, "id_A"] = 80
        frame.loc[4, "id_A"] = 101
        frame.loc[5, "id_A"] = np.nan
        frame.loc[6, "iq_A"] *= -1
        frame.loc[6, "psi_q_Wb"] *= -1
        selected, samples = select_anchors(frame, prior, spec, support)
        self.assertTrue(selected.loc[0, "fit_used"])
        self.assertFalse(selected.loc[0, "fit_mask_q"])
        self.assertTrue(selected.loc[1, "fit_mask_q"])
        self.assertFalse(selected.loc[1, "fit_mask_d"])
        self.assertEqual(selected.loc[2, "fit_reason"], "NO_ENABLED_COMPONENT")
        self.assertEqual(selected.loc[3, "fit_reason"], "OUTSIDE_CORRECTION_CORE")
        self.assertEqual(selected.loc[4, "fit_reason"], "OUTSIDE_MODEL_DOMAIN")
        self.assertEqual(selected.loc[5, "fit_reason"], "NONFINITE_COORDINATE")
        self.assertTrue(selected.loc[6, "q_reflected"])
        self.assertTrue(np.isfinite(samples.psi_d_Wb).all())
        self.assertTrue(np.isfinite(samples.psi_q_Wb).all())

    def config_with_output(self, name, transform=lambda text: text):
        original = self.root/"examples/build_maps_a.toml"
        path = original.with_name(name+".toml")
        path.write_text(transform(original.read_text().replace("../output/maps_a", f"../output/{name}")))
        return path, self.root/"output"/name

    def test_inverse_failure_preserves_model_forward_and_diagnostics(self):
        path, output = self.config_with_output("inverse_failure", lambda s: s.replace("smoothing_d = 0.0", "smoothing_d = -1.0"))
        result = subprocess.run([sys.executable, str(ROOT/"run_build_maps.py"), "--config", str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        summary = json.loads((output/"summary.json").read_text())
        self.assertEqual(summary["failed_step"], "inverse_fit")
        self.assertIn("smoothing", summary["reason"])
        self.assertTrue((output/"final_model.npz").exists())
        self.assertTrue((output/"forward_flux_map_psi_q.csv").exists())
        self.assertTrue((output/"correction_residuals.csv").exists())
        self.assertFalse((output/"inverse_flux_map_id.csv").exists())

    def test_correction_rank_failure_preserves_input_diagnostics(self):
        path, output = self.config_with_output("rank_failure")
        cfg = load_map_config(path)
        bad = self.root/"one_sample.csv"
        pd.read_csv(cfg.inputs["flux_samples"]).iloc[:1].to_csv(bad, index=False)
        path.write_text(path.read_text().replace("../output/correction_a/flux_samples.csv", "../one_sample.csv"))
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            run(path)
        self.assertTrue((output/"correction_samples.csv").exists())
        self.assertEqual(json.loads((output/"summary.json").read_text())["failed_step"], "correction_fit")

    def test_inverse_rounding_collisions_are_detected_after_forward_save(self):
        path, output = self.config_with_output("axis_collision")
        cfg = load_map_config(path)
        cfg.raw["inverse"]["psi_d_axis_Wb"] = [.04, .04000001]
        with patch("coenergy_maps.build_pipeline.load_map_config", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "after 6-decimal"):
                run(path)
        self.assertTrue((output/"forward_flux_map_psi_d.csv").exists())

    def test_inverse_flux_collision_and_wrong_q_branch(self):
        samples = pd.DataFrame({"id_A": [0, 1, 0, 1], "iq_A": [0, 0, 1, 1],
            "psi_d_Wb": [0, 1, 0, 1], "psi_q_Wb": [0, 0, 1, 1]})
        duplicate = samples.copy()
        duplicate.loc[3, ["psi_d_Wb", "psi_q_Wb"]] = [0, 1]
        with self.assertRaisesRegex(ValueError, "collision"):
            DirectInverse(duplicate, [0, 0])
        samples.loc[3, "psi_q_Wb"] = -1
        with self.assertRaisesRegex(ValueError, "positive-half"):
            DirectInverse(samples, [0, 0])

    def test_public_lut_validity_uses_vertices_and_flags_fallback(self):
        lut = PublicLut([0, 1], [0, 1], [[0, 1], [0, 1]], [[0, 0], [1, 1]], [[False, False], [False, False]])
        d, q, valid, fallback = lut.evaluate(np.array([.3, .3, 2]), np.array([.4, -.4, .4]))
        np.testing.assert_allclose(d[:2], [.3, .3])
        np.testing.assert_allclose(q[:2], [.4, -.4])
        self.assertFalse(valid.any())
        np.testing.assert_array_equal(fallback, [False, False, True])

    def test_nonempty_output_is_untouched(self):
        path = self.root/"examples/build_maps_a.toml"
        output = self.results["a"][1]
        before = (output/"final_model.npz").read_bytes()
        with self.assertRaisesRegex(ValueError, "empty directory"):
            run(path)
        self.assertEqual(before, (output/"final_model.npz").read_bytes())

    def test_source_correction_and_inverse_fixture(self):
        model = load_model(self.results["a"][1]/"final_model.npz")
        with np.load(ROOT/"tests/fixtures/stage3_source_reference.npz", allow_pickle=False) as ref:
            value = model.evaluate(ref["id_A"], ref["iq_A"])
            for name in value.__dataclass_fields__:
                np.testing.assert_allclose(getattr(value, name), ref[name], rtol=2e-11, atol=2e-12)
            samples = pd.read_csv(self.results["a"][1]/"inverse_fit_samples.csv", float_precision="round_trip")
            inverse = DirectInverse(samples, [0, 0])
            d, q = inverse.evaluate(ref["query_d"], ref["query_q"])
            np.testing.assert_allclose(d, ref["inverse_d"], rtol=2e-11, atol=2e-12)
            np.testing.assert_allclose(q, ref["inverse_q"], rtol=2e-11, atol=2e-12)
            np.testing.assert_allclose(samples[["psi_d_Wb", "psi_q_Wb"]], ref["forward_flux"], rtol=0, atol=1e-8)
            for name in ("id", "iq"):
                table = pd.read_csv(self.results["a"][1]/f"inverse_flux_map_{name}.csv", index_col=0, float_precision="round_trip")
                np.testing.assert_array_equal(table.to_numpy(), ref[f"inverse_lut_{name}"])

    def test_copied_cli_all_three_stages_with_external_cwd(self):
        with tempfile.TemporaryDirectory(prefix="independent stage3 ") as folder:
            copied = Path(folder)/"coenergy maps"
            shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns(".venv", "output", "__pycache__"))
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            for script, config in (("run_fit_jmag.py", "motor_a.toml"),
                                   ("run_identify_flux.py", "identify_correction_a.toml"),
                                   ("run_build_maps.py", "build_maps_a.toml")):
                process = subprocess.run([sys.executable, "-E", str(copied/script), "--config", str(copied/"examples"/config)],
                    cwd=folder, env=env, capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
            self.assertTrue((copied/"output/maps_a/inverse_flux_map_id.csv").exists())


if __name__ == "__main__":
    unittest.main()
