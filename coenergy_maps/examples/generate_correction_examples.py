"""Synthetic stage-two VI with a known nonzero delta, sampled inside the core.

delta_W/(I_base*Psi_base) = .002*u + .0015*u**2 - .001*v**2 + .0004*u**2*v**2.
These are software fixtures, not measurements or recommended motor settings.
"""

import csv
import math
from pathlib import Path
from generate_synthetic import flux


def generate(root):
    for name, ib, pb, poles, rpm, resistance in (
        ("a", 100., .12, 3, 1500, .04), ("b", 40., .035, 7, -800, .12),
    ):
        rows = []
        for j in range(11):
            u = -.6+j*.12
            for k in range(8):
                for sign in ((1,) if k == 0 else (1, -1)):
                    v = k*.6/7*sign
                    id_A, iq_A = ib*u, ib*v
                    pd, pq = flux(id_A, iq_A, ib, pb)
                    pd += pb*(.002+.003*u+.0008*u*v*v)
                    pq += pb*(-.002*v+.0008*u*u*v)
                    omega = poles*2*math.pi*rpm/60
                    rows.append(dict(PTN_No=len(rows)+1, RPM_moni=rpm, Idref_moni=id_A, Iqref_moni=iq_A,
                        Id0_1st=id_A, Iq0_1st=iq_A, Vd_1st=resistance*id_A-omega*pq, Vq_1st=resistance*iq_A+omega*pd))
        with (root/f"motor_{name}_correction_vi.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        (root/f"identify_correction_{name}.toml").write_text(f'''schema_version = 1
[input]
csv = "motor_{name}_correction_vi.csv"
format = "jmag_vi"
[output]
directory = "../output/correction_{name}"
[motor]
name = "synthetic_motor_{name}_correction"
pole_pairs = {poles}
dq_convention = "power_invariant"
stator_resistance_ohm = {resistance}
''', encoding="utf-8")
        def axis(lo, hi, n):
            return [round(lo+(hi-lo)*i/(n-1), 9) for i in range(n)]
        (root/f"build_maps_{name}.toml").write_text(f'''schema_version = 1
[input]
prior_model = "../output/motor_{name}/prior_model.npz"
prior_settings = "../output/motor_{name}/prior_settings.json"
prior_samples = "../output/motor_{name}/jmag_flux_samples.csv"
flux_samples = "../output/correction_{name}/flux_samples.csv"
[output]
directory = "../output/maps_{name}"

[correction.fit]
selection = "explicit"
i_base_A = {ib}
psi_base_Wb = {pb}
u_breakpoints = [-1.0, 0.0, 1.0]
v_breakpoints = [0.0, 0.5, 1.0]
roughness_weight = 0.0
ridge_weight = 0.0
solver = "dense_gelsd"
active_basis_tolerance = 1e-14
rank_tolerance = 1e-12
quadrature_order = 4

[correction.support]
id_outer_A = {[-.95*ib, .95*ib]}
id_core_A = {[-.7*ib, .7*ib]}
iq_outer_abs_A = {[0., .95*ib]}
iq_core_abs_A = {[0., .7*ib]}
reference_id_A = 0.0
reference_iq_A = 0.0

[forward]
id_axis_A = {axis(-ib, ib, 25)}
iq_axis_A = {axis(0, ib, 17)}

[inverse]
psi_d_axis_Wb = {axis(.35*pb, 1.12*pb, 31)}
psi_q_axis_Wb = {axis(0, .85*pb, 31)}
smoothing_d = 0.0
smoothing_q = 0.0
''', encoding="utf-8")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent)
