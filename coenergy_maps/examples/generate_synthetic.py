"""Reproduce the bundled synthetic VI fixtures (no simulator/real motor data).

W/(I_base*Psi_base) = .7*u + .15*u^2 + .325*v^2 + .05*u*v^2 + .02*u^2*v^2.
Voltages obey vd = R*id - omega*psi_q, vq = R*iq + omega*psi_d.
"""

import csv
import math
from pathlib import Path


def flux(id_A, iq_A, i_base, psi_base):
    u, v = id_A/i_base, iq_A/i_base
    return (psi_base*(.7+.3*u+.05*v*v+.04*u*v*v),
            psi_base*(.65*v+.1*u*v+.04*u*u*v))


def generate(root):
    for name, ib, pb, poles, rpm, resistance in (
        ("motor_a", 100.0, .12, 3, 1500, .04),
        ("motor_b", 40.0, .035, 7, -800, .12),
    ):
        rows = []
        for j in range(13):
            id_A = ib*(-1+j/6)
            for k in range(9):
                for sign in ((1,) if k == 0 else (1, -1)):
                    iq_A = ib*k/8*sign
                    pd, pq = flux(id_A, iq_A, ib, pb)
                    omega = poles*2*math.pi*rpm/60
                    rows.append(dict(PTN_No=len(rows)+1, Arms_moni=math.hypot(id_A, iq_A)/math.sqrt(3),
                                     Adeg_moni=math.degrees(math.atan2(-id_A, iq_A)), Vac_moni=0,
                                     Iac_moni=math.hypot(id_A, iq_A)/math.sqrt(3), RPM_moni=rpm,
                                     Trq_1st=poles*(pd*iq_A-pq*id_A), Idref_moni=id_A, Iqref_moni=iq_A,
                                     Id0_1st=id_A, Iq0_1st=iq_A, Vd_1st=resistance*id_A-omega*pq,
                                     Vq_1st=resistance*iq_A+omega*pd, pair_group=f"{j}_{k}"))
        with (root/f"{name}_vi.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent)
