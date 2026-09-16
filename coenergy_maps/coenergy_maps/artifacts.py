"""Float64 model serialization; no pickle and no source repository required."""

from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
from .coenergy_forward_fit import CoenergyModel


def save_json(path, value):
    def clean(item):
        if isinstance(item, np.ndarray):
            return clean(item.tolist())
        if isinstance(item, np.generic):
            return clean(item.item())
        if isinstance(item, dict):
            return {str(k): clean(v) for k, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [clean(v) for v in item]
        if isinstance(item, float) and not np.isfinite(item):
            return None
        return item
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                    allow_nan=False)+"\n", encoding="utf-8")


def save_model(path, model):
    from .coenergy_prior_correction import PriorCorrectedCoenergyModel
    if isinstance(model, PriorCorrectedCoenergyModel):
        values = {f"prior_{key}": value for key, value in asdict(model.prior_model).items()}
        values.update({f"delta_{key}": value for key, value in asdict(model.correction_model).items()})
        values["support_json"] = json.dumps(asdict(model.support))
        values["model_kind"] = "prior_corrected_v1"
        np.savez_compressed(path, **values)
    else:
        np.savez_compressed(path, **asdict(model))


def load_model(path):
    with np.load(path, allow_pickle=False) as data:
        def read(prefix=""):
            values = {key: data[prefix+key] for key in CoenergyModel.__dataclass_fields__}
            for key in ("i_base_A", "psi_base_Wb", "gauge_offset_bar"):
                values[key] = float(values[key])
            values["degree"] = int(values["degree"])
            return CoenergyModel(**values)
        if "model_kind" in data:
            from .coenergy_prior_correction import PriorCorrectedCoenergyModel, CorrectionSupportSpec
            if str(data["model_kind"]) != "prior_corrected_v1":
                raise ValueError("unknown saved model kind")
            model = PriorCorrectedCoenergyModel(read("prior_"), read("delta_"),
                CorrectionSupportSpec(**json.loads(str(data["support_json"]))))
        else:
            model = read()
    return model


def prepare_output(path):
    path = Path(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"output must be an empty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path
