"""Mirror VI equations extracted from identification/dense_jmag_rt_flux_identification.

Pair identity is explicit or based on exact command coordinates. Actual current
and speed deviations are diagnostics, never acceptance thresholds.
"""

import math
import numpy as np
import pandas as pd


def read_vi(config):
    raw = pd.read_csv(config.input_csv, encoding=config.encoding, dtype=str,
                      keep_default_na=False)
    missing = set(config.columns.values()) - set(raw.columns)
    if missing:
        raise ValueError(f"VI CSV missing columns: {sorted(missing)}")
    result = pd.DataFrame({key: raw[value] for key, value in config.columns.items()})
    result.insert(0, "source_row_index", np.arange(len(raw)))
    if "source_no" not in result:
        result["source_no"] = result.source_row_index.astype(str)
    for column in set(result.columns) - {"source_no", "source_row_index", "pair_id"}:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def identify_flux(rows, config):
    groups = {}
    for i, row in rows.iterrows():
        if "pair_id" in rows:
            key = ("pair", str(row.pair_id).strip())
            if not key[1]:
                key = ("invalid", i)
        elif np.isfinite([row.id_ref_A, row.iq_ref_A]).all():
            # Repeated speeds / acquisitions need explicit pair_id to disambiguate.
            key = (float(row.id_ref_A), abs(float(row.iq_ref_A)))
        else:
            key = ("invalid", i)
        groups.setdefault(key, []).append(i)
    observations = []
    diagnostics = rows.copy()
    diagnostics["observation_id"] = ""
    diagnostics["status"] = ""
    diagnostics["reason"] = ""
    for number, (key, indices) in enumerate(groups.items()):
        group = rows.loc[indices]
        oid = f"obs_{number:06d}"
        out = dict(observation_id=oid, source_row_indices=";".join(map(str, group.source_row_index)),
                   source_nos=";".join(map(str, group.source_no)),
                   observation_type="unresolved", id_A=math.nan, iq_A=math.nan,
                   psi_d_Wb=math.nan, psi_q_Wb=math.nan,
                   psi_d_observed=False, psi_q_observed=False, psi_q_structural=False,
                   weight_d=0.0, weight_q=0.0, status="NOT_CALCULATED", reason="",
                   rpm_formula=math.nan, rpm_partner=math.nan, rpm_difference=math.nan,
                   mirror_id_difference_A=math.nan, mirror_iq_sum_A=math.nan,
                   single_iq_achieved_A=math.nan, resistance_applied=False)
        reason = ""
        pos = group[group.iq_ref_A > 0]
        neg = group[group.iq_ref_A < 0]
        single = len(group) == 1 and group.iloc[0].iq_ref_A == 0
        mirror = len(group) == 2 and len(pos) == len(neg) == 1
        if key[0] == "invalid" or not np.isfinite(group.iq_ref_A).all():
            reason = "MISSING_PAIR_ID_OR_COMMAND"
        elif not single and not mirror:
            reason = "PAIR_INCOMPLETE_OR_AMBIGUOUS"
        else:
            required = ["id_A", "iq_A", "rpm", "vq_V"] + (["vd_V"] if mirror else [])
            if not np.isfinite(group[required].to_numpy(float)).all():
                reason = "REQUIRED_VALUE_NONFINITE"
            elif (group.rpm == 0).any():
                reason = "ZERO_SPEED_PRESENT"
            elif single and config.resistance is None:
                reason = "SINGLE_REQUIRES_STATOR_RESISTANCE"
            else:
                p = pos.iloc[0] if mirror else group.iloc[0]
                omega = config.pole_pairs * 2 * math.pi * p.rpm / 60
                out.update(rpm_formula=p.rpm, observation_type="mirror_pair" if mirror else "iq_zero_single")
                if mirror:
                    n = neg.iloc[0]
                    out.update(id_A=(p.id_A+n.id_A)/2, iq_A=(p.iq_A-n.iq_A)/2,
                               psi_d_Wb=(p.vq_V+n.vq_V)/(2*omega),
                               psi_q_Wb=(n.vd_V-p.vd_V)/(2*omega),
                               psi_q_observed=True, weight_q=1.0,
                               rpm_partner=n.rpm, rpm_difference=n.rpm-p.rpm,
                               mirror_id_difference_A=p.id_A-n.id_A,
                               mirror_iq_sum_A=p.iq_A+n.iq_A)
                    # Fold measured negative-Iq coordinates using the same symmetry.
                    if out["iq_A"] < 0:
                        out["iq_A"] *= -1
                        out["psi_q_Wb"] *= -1
                else:
                    out.update(id_A=p.id_A, iq_A=abs(p.iq_A),
                               psi_d_Wb=(p.vq_V-config.resistance*p.iq_A)/omega,
                               psi_q_Wb=0.0, psi_q_structural=bool(p.iq_A == 0),
                               single_iq_achieved_A=p.iq_A, resistance_applied=True)
                if np.isfinite([out[c] for c in ("id_A", "iq_A", "psi_d_Wb", "psi_q_Wb")]).all():
                    out.update(status="CALCULATED", psi_d_observed=True, weight_d=1.0)
                else:
                    reason = "IDENTIFICATION_NONFINITE"
                    out.update(psi_q_observed=False, weight_q=0.0)
        out["reason"] = reason
        diagnostics.loc[indices, ["observation_id", "status", "reason"]] = [oid, out["status"], reason]
        observations.append(out)
    if not observations:
        raise ValueError("VI CSV contains no rows")
    return pd.DataFrame(observations), diagnostics
