"""Connect saved observations to the fixed-prior correction core."""

import numpy as np
import pandas as pd
from .coenergy_forward_fit import CoenergySamples


def read_samples(path):
    frame = pd.read_csv(path, float_precision="round_trip", keep_default_na=False)
    required = ("observation_id", "id_A", "iq_A", "psi_d_Wb", "psi_q_Wb", "status", "reason",
                "psi_d_observed", "psi_q_observed", "weight_d", "weight_q")
    missing = set(required)-set(frame)
    if missing:
        raise ValueError(f"flux samples missing columns: {sorted(missing)}")
    return frame


def select_anchors(frame, prior, spec, support):
    result = frame.copy()
    for name in ("id_A", "iq_A", "psi_d_Wb", "psi_q_Wb", "weight_d", "weight_q"):
        result[name] = pd.to_numeric(result[name], errors="coerce")
    reflected = result.iq_A < 0
    result.loc[reflected, "psi_q_Wb"] *= -1
    result["iq_A"] = abs(result.iq_A)
    result["q_reflected"] = reflected
    for axis in ("d", "q"):
        observed = result[f"psi_{axis}_observed"].astype(str).str.lower().map({"true": True, "false": False})
        valid = (observed.eq(True) & np.isfinite(result[f"psi_{axis}_Wb"])
                 & np.isfinite(result[f"weight_{axis}"]) & (result[f"weight_{axis}"] > 0))
        result[f"component_{axis}_reason"] = np.where(observed.isna(), "INVALID_MASK",
            np.where(~observed.eq(True), "NOT_OBSERVED", np.where(valid, "", "INVALID_VALUE_OR_WEIGHT")))
        result[f"fit_mask_{axis}"] = valid
    finite = np.isfinite(result.id_A) & np.isfinite(result.iq_A)
    inside = (result.id_A.between(prior.i_base_A*prior.u_knots[prior.degree], prior.i_base_A*prior.u_knots[-prior.degree-1])
              & (result.iq_A <= prior.i_base_A*prior.v_knots[-prior.degree-1])
              & result.id_A.between(spec.i_base_A*spec.u_breakpoints[0], spec.i_base_A*spec.u_breakpoints[-1])
              & (result.iq_A <= spec.i_base_A*spec.v_breakpoints[-1]))
    core = result.id_A.between(*support.id_core_A) & result.iq_A.between(*support.iq_core_abs_A)
    result["fit_reason"] = np.select(
        [~result.status.eq("CALCULATED"), ~finite, ~inside, ~core,
         ~(result.fit_mask_d | result.fit_mask_q)],
        ["NOT_CALCULATED", "NONFINITE_COORDINATE", "OUTSIDE_MODEL_DOMAIN", "OUTSIDE_CORRECTION_CORE", "NO_ENABLED_COMPONENT"], default="")
    result["fit_used"] = result.fit_reason.eq("")
    train = result.loc[result.fit_used]
    if train.empty:
        return result, None
    mask = train[["fit_mask_d", "fit_mask_q"]].to_numpy(bool)
    targets = np.where(mask, train[["psi_d_Wb", "psi_q_Wb"]].to_numpy(float), 0)
    weights = np.where(mask, train[["weight_d", "weight_q"]].to_numpy(float), 0)/len(train)
    return result, CoenergySamples(train.id_A, train.iq_A, targets[:, 0], targets[:, 1], mask, weights)


def correction_residuals(frame, model):
    result = frame.copy()
    positions = np.flatnonzero(result.fit_used)
    for prefix, evaluator in (("prior", model.prior_model), ("final", model)):
        for axis in ("d", "q"):
            result[f"{prefix}_psi_{axis}_Wb"] = np.nan
        for start in range(0, len(positions), 2048):
            ix = positions[start:start+2048]
            value = evaluator.evaluate(result.id_A.iloc[ix], result.iq_A.iloc[ix])
            for axis in ("d", "q"):
                result.loc[result.index[ix], f"{prefix}_psi_{axis}_Wb"] = getattr(value, f"psi_{axis}_Wb")
        for axis in ("d", "q"):
            result[f"{prefix}_error_{axis}_Wb"] = (result[f"{prefix}_psi_{axis}_Wb"]-result[f"psi_{axis}_Wb"]).where(
                result.fit_used & result[f"fit_mask_{axis}"])
    return result
