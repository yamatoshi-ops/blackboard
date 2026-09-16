"""CLI pipelines; identification artifacts survive a later fit failure."""

import argparse
from dataclasses import asdict
import platform
import sys
import numpy as np
import pandas as pd
import scipy

from .artifacts import prepare_output, save_json, save_model
from .config import load_config
from .identification import read_vi, identify_flux
from .fitting import quadratures, select_samples, residual_table
from .coenergy_forward_fit import fit_coenergy_model


def run(config_path, *, fit):
    config = load_config(config_path, fit=fit)
    output = prepare_output(config.output_dir)
    summary = {"schema_version": 1, "stage": "fit_jmag" if fit else "identify_flux", "status": "RUNNING"}
    try:
        save_json(output / "run_settings.json", {"config": config.raw, "input_csv": str(config.input_csv),
                  "environment": {"python": platform.python_version(), "numpy": np.__version__,
                                  "scipy": scipy.__version__, "pandas": pd.__version__}})
        rows = read_vi(config)
        samples, diagnostics = identify_flux(rows, config)
        diagnostics.to_csv(output / "input_diagnostics.csv", index=False, float_format="%.17g")
        name = "jmag_flux_samples.csv" if fit else "flux_samples.csv"
        summary.update(input_rows=len(rows), observations=len(samples),
                       calculated=int(samples.status.eq("CALCULATED").sum()),
                       not_calculated=int(samples.status.ne("CALCULATED").sum()))
        samples.to_csv(output / name, index=False, float_format="%.17g")
        if fit:
            samples, training = select_samples(samples, config.fit_spec)
            samples.to_csv(output / name, index=False, float_format="%.17g")
            summary.update(fit_observations=int(samples.fit_used.sum()),
                           outside_model_domain=int(samples.fit_reason.eq("OUTSIDE_MODEL_DOMAIN").sum()))
            if training is None:
                raise ValueError("no calculable observations inside model domain")
            result = fit_coenergy_model(training, config.fit_spec, quadratures(config.fit_spec, config.quadrature_order))
            save_model(output / "prior_model.npz", result.model)
            spec = config.fit_spec
            used = samples.loc[samples.fit_used]
            save_json(output / "prior_settings.json", {
                "schema_version": 1, "model_file": "prior_model.npz", "motor": config.raw["motor"],
                "fit_spec": asdict(spec), "selection": "explicit", "quadrature_order": config.quadrature_order,
                "quadrature_domain": "configured knot spans; Gauss-Legendre tensor product",
                "loss": "sum of enabled component squared normalized errors / fitted observation count",
                "model_domain_A": {"id": [spec.i_base_A*spec.u_breakpoints[0], spec.i_base_A*spec.u_breakpoints[-1]],
                                   "iq": [-spec.i_base_A*spec.v_breakpoints[-1], spec.i_base_A*spec.v_breakpoints[-1]]},
                "observed_coordinate_bounds_A": {axis: [used[axis].min(), used[axis].max()] for axis in ("id_A", "iq_A")},
                "observations_file": name,
                "support_note": "bounds are not a validated continuous region; retain fit_used coordinates and component masks",
                "q_symmetry": "W and psi_d even, psi_q odd", "correction_region": None, "inverse_valid_region": None,
            })
            residuals = residual_table(samples, result.model)
            residuals.to_csv(output / "fit_residuals.csv", index=False, float_format="%.17g")
            summary.update(metrics=result.metrics, numerical_diagnostics=result.numerical_diagnostics)
            summary["residuals_Wb"] = {}
            for axis in ("d", "q"):
                errors = residuals[f"error_{axis}_Wb"].dropna().to_numpy(float)
                summary["residuals_Wb"][axis] = {"count": len(errors), "rmse": float(np.sqrt(np.mean(errors**2))) if len(errors) else None,
                                                "max_abs": float(np.max(abs(errors))) if len(errors) else None}
        summary["status"] = "COMPLETE" if summary["calculated"] else "NO_CALCULABLE_OBSERVATIONS"
        if fit and not all(result.numerical_diagnostics.get(k, False) for k in ("optimality_pass", "span_pass")):
            summary["status"] = "COMPLETE_WITH_NUMERICAL_WARNING"
        save_json(output / "summary.json", summary)
        return summary, output
    except Exception as error:
        summary.update(status="FAILED", reason=str(error), numerical_diagnostics=getattr(error, "diagnostics", None))
        save_json(output / "summary.json", summary)
        raise


def main(*, fit):
    parser = argparse.ArgumentParser(description="JMAG VI → Co-energy prior" if fit else "VI → flux samples")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        summary, output = run(args.config, fit=fit)
    except (ValueError, OSError, KeyError, TypeError, np.linalg.LinAlgError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"{summary['status']}: {output} ({summary['calculated']}/{summary['observations']} observations calculated)")
    return 0 if summary["status"] == "COMPLETE" else 2
