"""Configured knot-span quadrature and masked mean-loss fit."""

import numpy as np
from .coenergy_forward_fit import CoenergyQuadratures, CoenergySamples


def quadratures(spec, order):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    def axis(breaks):
        breaks = np.asarray(breaks)
        half = np.diff(breaks)/2
        return ((breaks[:-1]+half)[:, None]+half[:, None]*nodes).ravel(), (half[:, None]*weights).ravel()
    ua, uw = axis(spec.u_breakpoints)
    va, vw = axis(spec.v_breakpoints)
    u, v = np.meshgrid(ua, va, indexing="ij")
    u, v, weight = u.ravel(), v.ravel(), np.outer(uw, vw).ravel()
    return CoenergyQuadratures(u, v, u, v, weight, u, v, weight, u, v, weight)


def select_samples(frame, spec):
    frame = frame.copy()
    u = frame.id_A/spec.i_base_A
    v = frame.iq_A/spec.i_base_A
    inside = u.between(spec.u_breakpoints[0], spec.u_breakpoints[-1]) & v.between(0, spec.v_breakpoints[-1])
    used = frame.status.eq("CALCULATED") & inside
    frame["fit_used"] = used
    frame["fit_reason"] = np.where(used, "", np.where(frame.status.ne("CALCULATED"), frame.reason, "OUTSIDE_MODEL_DOMAIN"))
    train = frame.loc[used]
    if train.empty:
        return frame, None
    mask = train[["psi_d_observed", "psi_q_observed"]].to_numpy(bool)
    weights = train[["weight_d", "weight_q"]].to_numpy(float)/len(train)
    return frame, CoenergySamples(train.id_A, train.iq_A, train.psi_d_Wb, train.psi_q_Wb, mask, weights)


def residual_table(frame, model):
    result = frame.copy()
    for column in ("coenergy_J", "psi_fit_d_Wb", "psi_fit_q_Wb", "error_d_Wb", "error_q_Wb"):
        result[column] = np.nan
    positions = np.flatnonzero(frame.fit_used)
    for start in range(0, len(positions), 2048):
        ix = positions[start:start+2048]
        value = model.evaluate(frame.id_A.iloc[ix], frame.iq_A.iloc[ix])
        result.loc[result.index[ix], ["coenergy_J", "psi_fit_d_Wb", "psi_fit_q_Wb"]] = np.column_stack(
            [value.coenergy_J, value.psi_d_Wb, value.psi_q_Wb])
    for axis in ("d", "q"):
        result[f"error_{axis}_Wb"] = (result[f"psi_fit_{axis}_Wb"]-result[f"psi_{axis}_Wb"]).where(
            result.fit_used & result[f"psi_{axis}_observed"])
    return result
