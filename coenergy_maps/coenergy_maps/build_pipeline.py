"""Stage three: saved prior + observed flux -> localized correction -> public maps."""

import argparse
from dataclasses import asdict
import json
import platform
import shutil
import sys
import numpy as np
import pandas as pd
import scipy

from .artifacts import load_model, prepare_output, save_json, save_model
from .coenergy_forward_fit import CoenergyModel
from .coenergy_prior_correction import fit_prior_correction
from .correction import read_samples, select_anchors, correction_residuals
from .fitting import quadratures
from .map_config import load_map_config, correction_config, map_axes, inverse_smoothing
from .maps import forward_maps, inverse_maps, forward_lut, lut_jacobian, roundtrip, statistics


def run(config_path):
    config = load_map_config(config_path)
    output = prepare_output(config.output_dir)
    summary = {"schema_version": 1, "stage": "build_maps", "status": "RUNNING", "completed_steps": []}
    step = "load_inputs"
    try:
        save_json(output/"run_settings.json", {"config": config.raw, "inputs": {k: str(v) for k, v in config.inputs.items()},
            "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "pandas": pd.__version__}})
        prior = load_model(config.inputs["prior_model"])
        if not isinstance(prior, CoenergyModel):
            raise ValueError("stage three requires the original stage-one prior, not an already corrected model")
        settings = json.loads(config.inputs["prior_settings"].read_text(encoding="utf-8"))
        if settings["schema_version"] != 1:
            raise ValueError("unsupported prior settings schema")
        # These define the actual numerical meaning, not optional provenance.
        for name in ("i_base_A", "psi_base_Wb"):
            if settings["fit_spec"][name] != getattr(prior, name):
                raise ValueError(f"prior settings/model mismatch: {name}")
        prior_samples = read_samples(config.inputs["prior_samples"])
        observations = read_samples(config.inputs["flux_samples"])
        prior_samples.to_csv(output/"jmag_flux_samples.csv", index=False, float_format="%.17g")
        shutil.copyfile(config.inputs["prior_model"], output/"prior_model.npz")
        saved_prior_settings = dict(settings, model_file="prior_model.npz", observations_file="jmag_flux_samples.csv")
        save_json(output/"prior_settings.json", saved_prior_settings)
        observations.to_csv(output/"correction_samples.csv", index=False, float_format="%.17g")
        step = "correction_fit"
        spec, order, support = correction_config(config.raw)
        selected, training = select_anchors(observations, prior, spec, support)
        selected.to_csv(output/"correction_samples.csv", index=False, float_format="%.17g")
        summary.update(observations=len(selected), fit_observations=int(selected.fit_used.sum()),
                       excluded_reasons=selected.loc[~selected.fit_used, "fit_reason"].value_counts().to_dict())
        if training is None:
            raise ValueError("no usable observed components in correction core")
        result = fit_prior_correction(prior, training, spec, quadratures(spec, order), support)
        save_model(output/"final_model.npz", result.model)
        residuals = correction_residuals(selected, result.model)
        residuals.to_csv(output/"correction_residuals.csv", index=False, float_format="%.17g")
        summary.update(correction_metrics=result.metrics, numerical_diagnostics=result.delta_fit.numerical_diagnostics,
            residuals_Wb={f"{prefix}_{axis}": statistics(residuals[f"{prefix}_error_{axis}_Wb"])
                for prefix in ("prior", "final") for axis in ("d", "q")})
        final_settings = {"schema_version": 1, "model_file": "final_model.npz", "motor": settings["motor"],
            "model_domain_A": {"id": [prior.i_base_A*prior.u_knots[prior.degree], prior.i_base_A*prior.u_knots[-prior.degree-1]],
                               "iq": [-prior.i_base_A*prior.v_knots[-prior.degree-1], prior.i_base_A*prior.v_knots[-prior.degree-1]]},
            "prior_observed_coordinate_bounds_A": settings["observed_coordinate_bounds_A"],
            "prior_observations_file": "jmag_flux_samples.csv", "correction_observations_file": "correction_samples.csv",
            "correction_fit_spec": asdict(spec), "correction_quadrature_order": order,
            "correction_support": asdict(support), "q_symmetry": settings["q_symmetry"],
            "inverse_training_source": "published_forward_lut_nodes", "forward_decimals": 8, "inverse_decimals": 6,
            "interpolation": "Delaunay linear triangles; outside hull nearest fallback, flagged invalid",
            "inverse_valid_region": None,
            "scope_note": "coordinate bounds and hull support do not certify measurement accuracy or inverse uniqueness"}
        save_json(output/"final_settings.json", final_settings)
        summary["completed_steps"].append(step)
        step = "forward_lut"
        axes = map_axes(config.raw)
        samples, summary["forward"] = forward_maps(result.model, axes, output)
        summary["completed_steps"].append(step)
        final_settings["forward_axes_A"] = {"id": axes[0], "iq": axes[1]}
        save_json(output/"final_settings.json", final_settings)
        step = "inverse_fit"
        forward = forward_lut(samples, axes)
        summary["forward"]["lut_jacobian"] = lut_jacobian(forward)
        inverse_axes = map_axes(config.raw, inverse=True)
        direct, inverse, summary["inverse"] = inverse_maps(samples, axes, inverse_axes, inverse_smoothing(config.raw), output)
        summary["completed_steps"].append(step)
        final_settings["inverse_axes_Wb"] = {"psi_d": inverse_axes[0], "psi_q": inverse_axes[1]}
        final_settings["inverse_valid_region"] = {"node_mask": "inverse_validity.csv", "node_diagnostics": "inverse_domain.csv",
            "rule": "inside training flux convex hull and recovered current inside forward grid; interpolation requires all triangle vertices valid"}
        save_json(output/"final_settings.json", final_settings)
        step = "roundtrip"
        summary["roundtrip"] = roundtrip(result.model, forward, inverse, direct, axes, output)
        summary["completed_steps"].append(step)
        warnings = []
        if not all(result.delta_fit.numerical_diagnostics.get(k, False) for k in ("optimality_pass", "span_pass")):
            warnings.append("CORRECTION_NUMERICAL_DIAGNOSTICS")
        if summary["forward"]["nonpositive_hessian_nodes"] or summary["forward"]["lut_jacobian"]["nonpositive_triangles"]:
            warnings.append("NONPOSITIVE_FORWARD_JACOBIAN_IN_SAMPLED_DOMAIN")
        if not summary["roundtrip"]["valid_count"]:
            warnings.append("NO_VALID_PUBLIC_LUT_ROUNDTRIP_POINTS")
        summary.update(status="COMPLETE_WITH_NUMERICAL_WARNING" if warnings else "COMPLETE", warnings=warnings)
        save_json(output/"summary.json", summary)
        return summary, output
    except Exception as error:
        summary.update(status="FAILED", failed_step=step, reason=str(error), failure_diagnostics=getattr(error, "diagnostics", None))
        save_json(output/"summary.json", summary)
        raise


def main():
    parser = argparse.ArgumentParser(description="Fixed Co-energy prior + flux observations -> corrected forward/inverse maps")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        summary, output = run(args.config)
    except (ValueError, OSError, KeyError, TypeError, np.linalg.LinAlgError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"{summary['status']}: {output} ({summary['fit_observations']}/{summary['observations']} correction observations)")
    return 0 if summary["status"] == "COMPLETE" else 2
