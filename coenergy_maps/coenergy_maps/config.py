"""TOML settings; all paths are relative to the settings file."""

from dataclasses import dataclass
from pathlib import Path
import math
import tomllib

from .coenergy_forward_fit import CoenergyFitSpec, _validated_spec


JMAG_COLUMNS = {
    "source_no": "PTN_No", "rpm": "RPM_moni",
    "id_ref_A": "Idref_moni", "iq_ref_A": "Iqref_moni",
    "id_A": "Id0_1st", "iq_A": "Iq0_1st",
    "vd_V": "Vd_1st", "vq_V": "Vq_1st",
}


@dataclass(frozen=True)
class Config:
    path: Path
    raw: dict
    input_csv: Path
    output_dir: Path
    columns: dict
    encoding: str
    pole_pairs: int
    resistance: float | None
    fit_spec: CoenergyFitSpec | None
    quadrature_order: int | None


def _keys(table, allowed, name):
    if not isinstance(table, dict):
        raise ValueError(f"{name} must be a TOML table")
    unknown = set(table) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {name} keys: {sorted(unknown)}")


def parse_fit(cfg):
    cfg = dict(cfg)
    _keys(cfg, (*CoenergyFitSpec.__dataclass_fields__, "quadrature_order", "selection"), "fit")
    if cfg.pop("selection") != "explicit":
        raise ValueError("fit.selection must be explicit; no automatic DEN selection")
    order = cfg.pop("quadrature_order")
    if type(order) is not int or order not in (4, 8):
        raise ValueError("quadrature_order must be 4 or 8")
    cfg.setdefault("solver_tolerance", None)
    cfg.setdefault("solver_max_iterations", None)
    cfg.setdefault("rank_tolerance", None)
    spec = CoenergyFitSpec(**cfg)
    _validated_spec(spec)
    return spec, order


def load_config(path, *, fit=False):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    _keys(raw, ("schema_version", "input", "output", "motor", "fit"), "root")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    inp, out, motor = raw["input"], raw["output"], raw["motor"]
    _keys(inp, ("csv", "format", "encoding", "columns"), "input")
    _keys(out, ("directory",), "output")
    _keys(motor, ("name", "pole_pairs", "dq_convention", "stator_resistance_ohm",
                  "temperature_degC", "stator_resistance_temperature_degC"), "motor")
    pairs = motor["pole_pairs"]
    if type(pairs) is not int or pairs <= 0:
        raise ValueError("motor.pole_pairs must be a positive integer")
    if motor["dq_convention"] not in ("power_invariant", "amplitude_invariant"):
        raise ValueError("dq_convention must be power_invariant or amplitude_invariant")
    resistance = motor.get("stator_resistance_ohm")
    if resistance is not None:
        resistance = float(resistance)
        if not math.isfinite(resistance) or resistance < 0:
            raise ValueError("stator_resistance_ohm must be finite and nonnegative")
    fmt = inp["format"]
    if fmt not in ("jmag_vi", "mapped_dq"):
        raise ValueError("input.format must be jmag_vi or mapped_dq")
    columns = dict(JMAG_COLUMNS if fmt == "jmag_vi" else {})
    overrides = inp.get("columns", {})
    _keys(overrides, (*JMAG_COLUMNS, "pair_id"), "input.columns")
    columns.update(overrides)
    required = {"rpm", "id_A", "iq_A", "vd_V", "vq_V", "iq_ref_A"}
    if "pair_id" not in columns:
        required.add("id_ref_A")
    if required - columns.keys():
        raise ValueError(f"missing column mappings: {sorted(required - columns.keys())}")
    if any(not isinstance(v, str) or not v for v in columns.values()):
        raise ValueError("column mappings must be nonempty strings")
    spec = order = None
    if fit:
        spec, order = parse_fit(raw["fit"])
    return Config(path, raw, (path.parent / inp["csv"]).resolve(),
                  (path.parent / out["directory"]).resolve(), columns,
                  inp.get("encoding", "utf-8-sig"), pairs, resistance, spec, order)
