"""Synthetic LIVE03 host: LIVE02 fixture + single-hit/cyclic paths + TD response.

Never native PTV evidence.
* Each station a gets an interior zone (one cordon hit) and a 'return' zone
  whose path enters and leaves through station a (cyclic, hits [a, a]).
* Procedures.Execute() recomputes demand whenever the TD operation is active
  (TG parameters enter through P/A exactly as in LIVE02), with a production-
  constrained distance response per family:
      Q_ij = P_i-total * base_ij * D_ij^(b-b0) * exp((c-c0) D_ij) / row normalizer
  (b, c = mean of the family's TD components; D = matrix 9697).
* Matrices 9111-9115 (LONG) and 9117 (SCHOOL) are positive so the FineCDF IDP
  metrics are defined; 9117 responds to the SCHOOL b/c.
"""
import numpy as np
from fake_live01 import Attr
from fake_live02 import Live02Visum, WORK, SERVICE
from cordon2025.common import parent_core

FAMILIES = {'WORK': ['1_WORK_E_C', '1_WORK_E_noC', '1_WORK_noE_C', '1_WORK_noE_noC', '1_WORK_stud'],
            'SERVICE': ['2_SERV_E_C', '2_SERV_E_noC', '2_SERV_noE_C', '2_SERV_noE_noC', '2_SERV_stud'],
            'SCHOOL': ['5_SCHOOL']}


class GravAttr(Attr):
    def SetAttValue(self, name, value):
        h = self.host
        if str(name).upper() not in ('PARA_B', 'PARA_C'):
            h.writes.append('TD_SetAttValue:' + name)
            raise AssertionError('FORBIDDEN_TD_WRITE:' + name)
        h.allowed_writes.append(('TD', name, float(value)))
        self.values[name] = float(value)


class Live03Visum(Live02Visum):
    def __init__(self, folder, *, single_hit_weight=3.0, cyclic_weight=0.4):
        super().__init__(folder)
        self.origin = 'MOCK_LIVE03_681_ZONES_NOT_NATIVE'
        src = folder / 'R1_2025_SYNTHETIC_LIVE03_COPY.ver'; src.write_bytes(b'SYNTHETIC_NOT_A_VISUM_VERSION')
        self.source = src; self.IO.CurrentVersionFile = str(src)
        self.td_response = 1.0
        zones = [10 * i + 5 for i in range(681)]
        from cordon2025.authority import mapping
        from cordon2025.common import ROOT
        stations, _ = mapping(ROOT / 'data/audited/STATION_MAPPING.csv')
        by = {}
        for key, s in stations.items():
            by.setdefault(s, []).append(key)
        new_keys = []
        for a in range(1, 17):
            new_keys += [(zones[a - 1], zones[100 + a]), (zones[100 + a], zones[a - 1]), (zones[a - 1], zones[200 + a])]
        for mi, mode in enumerate(('C', 'C_NOT')):
            data = self.geometry_rows[mode]
            for a in range(1, 17):
                x, y = sorted(by[a])
                skip = mode == 'C_NOT' and a in (1, 3, 15, 16)
                cyc = [x, y]
                if x[2] != y[1]:
                    bridge = (900000 + mi * 1000 + a, x[2], y[1])
                    if not any((r['NO'], r['FROMNODENO'], r['TONODENO']) == bridge for r in self.Net.Links.rows):
                        self.Net.Links.rows.append({'NO': bridge[0], 'FROMNODENO': bridge[1], 'TONODENO': bridge[2],
                                                    'TSYSSET': 'C,C_noT,LNV,NV', 'ADDVAL1': 0.0, 'T0_PRTSYS(C)': 30.0,
                                                    'CAPPRT': 1800.0, 'LENGTH': 0.5, 'TYPENO': 10})
                    cyc = [x, bridge, y]
                for (o, d), edges in (((zones[a - 1], zones[100 + a]), [x]), ((zones[100 + a], zones[a - 1]), [y]),
                                      ((zones[a - 1], zones[200 + a]), cyc)):
                    data.append([o, d, 1, '', '', '', ''])
                    if skip:
                        continue
                    for j, k in enumerate(edges, 1):
                        data.append(['', '', '', j, *k])
        self.path_keys = list(self.path_keys) + new_keys
        for ix, (code, ds) in enumerate(self.dsegs.items()):
            if code in ('LNV', 'NV'):
                continue
            arr = np.array(ds.ODMatrix.values, copy=True)
            for n, (o, d) in enumerate(new_keys):
                w = cyclic_weight if n % 3 == 2 else single_hit_weight
                arr[self.axis[o], self.axis[d]] = w * (2. + ix * .1 + (n % 5) * .01)
            ds.ODMatrix.values = arr
        self.base_od = {parent_core().norm_code(c): np.array(ds.ODMatrix.values, copy=True) for c, ds in self.dsegs.items()}
        i = np.arange(681)
        self.component[9697].values = 2.0 + 0.25 * np.abs(i[:, None] - i[None, :])
        for no in range(9111, 9116):
            self.component[no].values = np.full((681, 681), 0.01)
        self.base_school = np.full((681, 681), 0.02)
        td = self.ops[5].TripDistributionParameters
        for code, st in td.strata.items():
            st.GravitationParameters = GravAttr(self, dict(st.GravitationParameters.values))
        self.base_td = self.td_family_params()
        self._recompute_demand()
        self.executions = 0; self.writes.clear(); self.allowed_writes.clear()

    def td_family_params(self):
        td = self.ops[5].TripDistributionParameters
        out = {}
        for fam, codes in FAMILIES.items():
            g = [td.strata[c].GravitationParameters.values for c in codes]
            out[fam] = (float(np.mean([x['PARA_B'] for x in g])), float(np.mean([x['PARA_C'] for x in g])))
        return out

    def _td_factor(self, fam, base):
        if not hasattr(self, 'base_td'):
            return base
        b0, c0 = self.base_td[fam]; b, c = self.td_family_params()[fam]
        D = self.component[9697].values
        f = np.power(D, (b - b0) * self.td_response) * np.exp((c - c0) * self.td_response * D)
        out = base * f
        rs0 = base.sum(axis=1, keepdims=True); rs1 = out.sum(axis=1, keepdims=True)
        return np.where(rs1 > 0, out * rs0 / np.where(rs1 > 0, rs1, 1.0), 0.0)

    def execute(self):
        self.executions += 1
        self.touch('Procedures.Execute')
        if self.executions in self.fail_execute_on:
            raise RuntimeError('SYNTHETIC_PROCEDURE_FAILURE')
        if self.on_execute is not None:
            self.on_execute(self)
        self.response = self.response_by_execution.get(self.executions, self.response)
        active = [bool(o.values['ACTIVE']) for o in self.ops]
        if active[5]:            # native TD active (TG outputs follow the current TG parameters)
            self._recompute_demand()
        self._post_execute()

    def _recompute_demand(self):
        dom = self.zone_vector('NOT_ZAHR') >= 0.5

        def ratio(a_dom, a_zahr):
            cur = np.where(dom, self.zone_vector(a_dom), self.zone_vector(a_zahr))
            base = np.where(dom, self.base_params[a_dom], self.base_params[a_zahr])
            return np.where(base > 0, cur / np.where(base > 0, base, 1.0), 1.0) ** self.response
        pw = ratio('ADD_PROD_W', 'ZAHR_PROD_WORK'); aw = ratio('ADD_ATT_W', 'ZAHR_ATR_WORK')
        aw = aw * (self.zone_vector('ADD_SALARY') / np.maximum(self.base_params['ADD_SALARY'], 1e-12)) ** 0.2
        ps = ratio('ADD_PROD_S', 'ZAHR_PROD_SERV'); as_ = ratio('ADD_ATT_S', 'ZAHR_ATR_SERV')
        work_total = np.zeros((681, 681)); serv_total = np.zeros((681, 681))
        for code, ds in self.dsegs.items():
            norm = parent_core().norm_code(code)
            if norm in WORK:
                v = self._td_factor('WORK', self.base_od[norm]) * np.outer(pw, aw); work_total += v
            elif norm in SERVICE:
                v = self._td_factor('SERVICE', self.base_od[norm]) * np.outer(ps, as_); serv_total += v
            else:
                continue
            ds.ODMatrix.values = v
        for no in range(9101, 9106):
            self.component[no].values = work_total / 5.0
        for no in range(9106, 9111):
            self.component[no].values = serv_total / 5.0
        if hasattr(self, 'base_school'):
            self.component[9117].values = self._td_factor('SCHOOL', self.base_school)
