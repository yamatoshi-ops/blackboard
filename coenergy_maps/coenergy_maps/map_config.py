"""Explicit stage-three settings; no motor-specific grid or model selection."""

from dataclasses import dataclass
from pathlib import Path
import tomllib
import numpy as np

from .config import _keys, parse_fit
from .coenergy_prior_correction import CorrectionSupportSpec
from .flux_map_model import _axis


@dataclass(frozen=True)
class MapConfig:
    path: Path
    raw: dict
    inputs: dict
    output_dir: Path


def load_map_config(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    _keys(raw, ("schema_version", "input", "output", "correction", "forward", "inverse"), "root")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    names = ("prior_model", "prior_settings", "prior_samples", "flux_samples")
    _keys(raw["input"], names, "input")
    _keys(raw["output"], ("directory",), "output")
    return MapConfig(path, raw, {key: (path.parent/raw["input"][key]).resolve() for key in names},
                     (path.parent/raw["output"]["directory"]).resolve())


def correction_config(raw):
    cfg = raw["correction"]
    _keys(cfg, ("fit", "support"), "correction")
    spec, order = parse_fit(cfg["fit"])
    _keys(cfg["support"], CorrectionSupportSpec.__dataclass_fields__, "correction.support")
    return spec, order, CorrectionSupportSpec(**cfg["support"])


def map_axes(raw, *, inverse=False):
    cfg = raw["inverse" if inverse else "forward"]
    names = ("psi_d_axis_Wb", "psi_q_axis_Wb") if inverse else ("id_axis_A", "iq_axis_A")
    _keys(cfg, (*names, "smoothing_d", "smoothing_q") if inverse else names, "map")
    axes = [_axis(cfg[name], name) for name in names]
    if inverse:
        axes = [_axis(np.round(axis, 6), name+" after 6-decimal publication") for name, axis in zip(names, axes)]
    if axes[1][0] != 0:
        raise ValueError("q axis must start at exactly zero (positive half-plane)")
    return axes


def inverse_smoothing(raw):
    values = [float(raw["inverse"]["smoothing_"+axis]) for axis in ("d", "q")]
    if not np.isfinite(values).all() or min(values) < 0:
        raise ValueError("inverse smoothing must be finite and nonnegative")
    return values
