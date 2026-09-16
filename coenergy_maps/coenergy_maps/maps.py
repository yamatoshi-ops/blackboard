"""Public LUT generation and diagnostics, starting from rounded forward nodes."""

import numpy as np
import pandas as pd
from scipy.spatial import Delaunay, QhullError

from .flux_map_model import _ScatteredPairInterpolator
from .inverse_rbf import _target_normalization, _fit_rbf, InverseComponentFit


def write_map(path, x, y, values, *, inverse=False):
    frame = pd.DataFrame(values, index=y, columns=x)
    frame.index.name = r"pq\pd" if inverse else None
    frame.to_csv(path, float_format="%.17g")


def mesh(x, y):
    grids = np.meshgrid(x, y)
    return tuple(a.ravel() for a in grids)


def evaluate_batched(model, x, y):
    fields = {}
    for start in range(0, len(x), 2048):
        result = model.evaluate(x[start:start+2048], y[start:start+2048])
        for key in result.__dataclass_fields__:
            fields.setdefault(key, []).append(np.asarray(getattr(result, key)))
    return {key: np.concatenate(values) for key, values in fields.items()}


def statistics(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return {"count": len(values), "rmse": float(np.sqrt(np.mean(values**2))) if len(values) else None,
            "max_abs": float(np.max(abs(values))) if len(values) else None}


class PublicLut:
    """One direction only: no hidden inverse built from flux samples."""

    def __init__(self, x, y, d, q, valid=None):
        xx, yy = mesh(x, y)
        self.interpolator = _ScatteredPairInterpolator(xx, yy, d, q, name="public LUT", source_kind="public_lut")
        self.valid = None if valid is None else np.asarray(valid, bool).ravel()

    def evaluate(self, x, y):
        x, y = np.broadcast_arrays(x, y)
        d, q, supported, fallback = self.interpolator.evaluate(x, abs(y))
        valid = np.asarray(supported) & ~np.asarray(fallback)
        if self.valid is not None:
            tri = self.interpolator._triangulation
            simplex = tri.find_simplex(np.column_stack([x.ravel(), abs(y).ravel()]))
            valid &= self.valid[tri.simplices[np.maximum(simplex, 0)]].all(axis=1).reshape(x.shape)
        return np.asarray(d), np.asarray(q)*np.sign(y), valid, np.asarray(fallback)


def forward_maps(model, axes, output):
    x, y = axes
    xx, yy = mesh(x, y)
    value = evaluate_batched(model, xx, yy)
    shape = (len(y), len(x))
    d, q = [np.round(value[f"psi_{axis}_Wb"], 8).reshape(shape) for axis in ("d", "q")]
    for axis, data in (("d", d), ("q", q)):
        write_map(output/f"forward_flux_map_psi_{axis}.csv", x, y, data)
    samples = pd.DataFrame({"id_A": xx, "iq_A": yy, "psi_d_Wb": d.ravel(), "psi_q_Wb": q.ravel()})
    samples.to_csv(output/"inverse_fit_samples.csv", index=False, float_format="%.17g")
    hessian = np.stack([value["l_dd_H"], value["l_dq_H"], value["l_qd_H"], value["l_qq_H"]], axis=-1).reshape(-1, 2, 2)
    eigenvalues = np.linalg.eigvalsh(hessian)
    diagnostics = {"grid_shape": list(shape), "hessian_min_eigenvalue_H": float(eigenvalues.min()),
                   "nonpositive_hessian_nodes": int((eigenvalues[:, 0] <= 0).sum()),
                   "node_rounding_error_Wb": {axis: statistics(samples[f"psi_{axis}_Wb"]-value[f"psi_{axis}_Wb"]) for axis in ("d", "q")}}
    return samples, diagnostics


class DirectInverse:
    def __init__(self, samples, smoothing):
        # Sorting and normalization follow the source inverse fit. Exact rounded
        # flux collisions are not averaged: distinct LUT nodes are distinct currents.
        samples = samples.sort_values(["psi_d_Wb", "psi_q_Wb", "id_A", "iq_A"], kind="mergesort")
        points = samples[["psi_d_Wb", "psi_q_Wb"]].to_numpy(float)
        if not np.isfinite(points).all() or (points[:, 1] < 0).any():
            raise ValueError("inverse positive-half flux must be finite with psi_q >= 0")
        if len(np.unique(points, axis=0)) != len(points):
            raise ValueError("published forward flux collision: distinct currents share a flux node")
        self.mean = points.mean(axis=0)
        self.scale = points.std(axis=0, ddof=0)
        if not np.isfinite(self.scale).all() or (self.scale <= 0).any():
            raise ValueError("inverse flux coordinates must span both axes")
        normalized = (points-self.mean)/self.scale
        try:
            self.hull = Delaunay(normalized)
        except QhullError as error:
            raise ValueError("inverse flux hull could not be constructed") from error
        self.fits = []
        for axis, smooth in zip(("d", "q"), smoothing):
            target = samples[f"i{axis}_A"].to_numpy(float)
            mean, scale = _target_normalization(target, 0)
            rbf = _fit_rbf(normalized, (target-mean)/scale, smooth)
            self.fits.append(InverseComponentFit(axis, self.mean, self.scale, mean, scale, smooth, rbf, axis == "q"))

    def evaluate(self, d, q):
        return self.fits[0](d, abs(q)), self.fits[1](d, abs(q))*np.sign(q)

    def supported(self, d, q):
        d, q = np.broadcast_arrays(d, q)
        points = np.column_stack([d.ravel(), abs(q).ravel()])
        return (self.hull.find_simplex((points-self.mean)/self.scale, tol=1e-12) >= 0).reshape(d.shape)


def inverse_maps(samples, forward_axes, axes, smoothing, output):
    direct = DirectInverse(samples, smoothing)
    x, y = axes
    xx, yy = mesh(x, y)
    currents = direct.evaluate(xx, yy)
    shape = (len(y), len(x))
    d, q = [np.round(a, 6).reshape(shape) for a in currents]
    inside_hull = direct.supported(xx, yy).reshape(shape)
    fx, fy = forward_axes
    inside_current = (d >= fx[0]) & (d <= fx[-1]) & (q >= fy[0]) & (q <= fy[-1])
    valid = inside_hull & inside_current
    for axis, data in (("id", d), ("iq", q)):
        write_map(output/f"inverse_flux_map_{axis}.csv", x, y, data, inverse=True)
    write_map(output/"inverse_validity.csv", x, y, valid.astype(int), inverse=True)
    pd.DataFrame({"psi_d_Wb": xx, "psi_q_Wb": yy, "inside_training_flux_hull": inside_hull.ravel(),
                  "recovered_current_inside_forward_grid": inside_current.ravel(), "valid": valid.ravel()}).to_csv(
                      output/"inverse_domain.csv", index=False, float_format="%.17g")
    model = PublicLut(x, y, d, q, valid)
    metrics = {"grid_shape": list(shape), "valid_nodes": int(valid.sum()), "extrapolated_nodes": int((~inside_hull).sum()),
               "current_outside_forward_grid_nodes": int((~inside_current).sum()),
               "normalization_mean_Wb": direct.mean, "normalization_scale_Wb": direct.scale,
               "smoothing_d": smoothing[0], "smoothing_q": smoothing[1]}
    return direct, model, metrics


def forward_lut(samples, axes):
    return PublicLut(*axes, samples.psi_d_Wb.to_numpy(), samples.psi_q_Wb.to_numpy())


def lut_jacobian(forward):
    tri = forward.interpolator.triangulation()
    points = tri.points[tri.simplices]
    flux = np.stack([tri.output_d, tri.output_q], axis=-1)[tri.simplices]
    det = np.linalg.det(flux[:, 1:]-flux[:, :1])/np.linalg.det(points[:, 1:]-points[:, :1])
    return {"triangle_count": len(det), "min_determinant_H2": float(det.min()), "nonpositive_triangles": int((det <= 0).sum())}


def roundtrip(model, forward, inverse, direct, axes, output):
    nx, ny = mesh(*axes)
    cx, cy = mesh((axes[0][1:]+axes[0][:-1])/2, (axes[1][1:]+axes[1][:-1])/2)
    x, y = np.r_[nx, cx], np.r_[ny, cy]
    value = evaluate_batched(model, x, y)
    fd, fq, fvalid, ffallback = forward.evaluate(x, y)
    rd, rq, ivalid, ifallback = inverse.evaluate(fd, fq)
    bd, bq, bvalid, bfallback = forward.evaluate(rd, rq)
    dd, dq = direct.evaluate(fd, fq)
    hull = direct.supported(fd, fq)
    valid = fvalid & ivalid & bvalid & hull
    frame = pd.DataFrame({"location": ["node"]*len(nx)+["cell_center"]*len(cx), "id_A": x, "iq_A": y,
        "model_psi_d_Wb": value["psi_d_Wb"], "model_psi_q_Wb": value["psi_q_Wb"],
        "lut_psi_d_Wb": fd, "lut_psi_q_Wb": fq, "recovered_id_A": rd, "recovered_iq_A": rq,
        "lut_minus_model_d_Wb": fd-value["psi_d_Wb"], "lut_minus_model_q_Wb": fq-value["psi_q_Wb"],
        "roundtrip_id_error_A": rd-x, "roundtrip_iq_error_A": rq-y,
        "roundtrip_psi_d_error_Wb": bd-fd, "roundtrip_psi_q_error_Wb": bq-fq,
        "inverse_lut_minus_rbf_id_A": rd-dd, "inverse_lut_minus_rbf_iq_A": rq-dq,
        "inverse_training_hull_supported": hull, "inverse_lut_valid": ivalid,
        "forward_nearest_fallback": ffallback, "inverse_nearest_fallback": ifallback,
        "return_forward_nearest_fallback": bfallback, "valid_roundtrip": valid})
    frame.to_csv(output/"roundtrip.csv", index=False, float_format="%.17g")
    columns = [c for c in frame if "error" in c or "minus" in c]
    return {"query_count": len(frame), "valid_count": int(valid.sum()),
            "all_points_including_extrapolation": {c: statistics(frame[c]) for c in columns},
            "valid_only": {c: statistics(frame.loc[valid, c]) for c in columns}}
