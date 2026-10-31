"""Synthetic LIVE04 host: LIVE03 fixture + the v7 LONG matrices and their realization.

Never native PTV evidence.
* 9697 is R1_OSRM_DIST_KM (km = 2 + 0.25*|i-j|; on the cordon path OD pairs alternately
  120 km and 30 km, so the mask removes LONG volume from half of the cordon paths).
* As in the real model, 9305 is the NATIVE_CL assignment OD matrix, so the masked LONG
  vehicle demand is what the cordon paths of NATIVE_CL carry.
* TD (op 6) produces UNMASKED LONG person demand 9111..9115 (short cells included);
  the realization op 11 ('20B') produces the vehicle components 9291..9295
  (0.8 x person + a small 'repaired reverse support' leak on short cells);
  9305 is a FORMULA matrix = sum of 9291..9295 (read-only, recomputed on read).
* TG (op 5) realizes the FP_* productions as fixed per-zone units x ADD_PROD_* (AMDY:
  FP_5_SCHOOL has no ADD coefficient and stays fixed), which MOBILITY2 reads back.
* SetValues is allowed only on DATA matrices (9111..9115, 9291..9295) and is recorded.
* The start state is already masked (as a v7-saved version would be).
* Optional route choice (route_gamma > 0): the 240 station-pair OD of every mode-C
  demand segment get a second path over a bypass link that crosses no station.
  The assignment (op 20) splits the OD between the paths with
  share_cordon = clip(0.8 * (OD/OD_base)**(-route_gamma), 0.05, 0.95); demand-only
  runs leave the split unchanged.  Frozen-path predictions therefore miss the
  route-choice response exactly like in a congested native model.
"""
import numpy as np
from fake_visum_startup import Matrix
from fake_live01 import FullList
from fake_live02 import LinkObj, LinkCollection
from fake_live03 import Live03Visum
from cordon2025.common import parent_core

LONG_PERSON = tuple(range(9111, 9116))
LONG_VEHICLE = tuple(range(9291, 9296))


class Matrix4(Matrix):
    def __init__(self, host, no, values, code='', source='DATA'):
        super().__init__(host, no, values)
        self.code = code; self.source = source

    def AttValue(self, name):
        if name.upper() == 'CODE':
            return self.code
        if name.upper() == 'DATASOURCETYPE':
            return self.source
        return super().AttValue(name)

    def SetValues(self, values, add=False):
        h = self.host
        if self.source != 'DATA' or add is not False or not isinstance(values, np.ndarray):
            h.writes.append('Matrix.SetValues:%d' % self.no)
            raise AssertionError('FORBIDDEN_MATRIX_WRITE:%d' % self.no)
        if self.no in h.fail_matrix_write:      # one-shot fault, rejected before any change
            h.fail_matrix_write.discard(self.no)
            raise RuntimeError('SYNTHETIC_MATRIX_WRITE_FAILURE:%d' % self.no)
        h.allowed_writes.append(('MATRIX', self.no, float(values.sum())))
        h.matrix_writes.append(self.no)
        self.values = np.array(values, dtype=float, copy=True)


class FormulaMatrix(Matrix4):
    def __init__(self, host, no, parts):
        super().__init__(host, no, np.zeros((681, 681)), source='FORMULA')
        self.parts = parts

    @property
    def values(self):
        return sum(self.host.component[p].values for p in self.parts)

    @values.setter
    def values(self, _value):
        pass  # recomputed from the components; never stored


class Live04Visum(Live03Visum):
    def __init__(self, folder, *, masked_start=True, long_leak=1.0e-3, route_gamma=0.0, **kwargs):
        super().__init__(folder, **kwargs)
        self.route_gamma = float(route_gamma)
        self.Net.Links = WritableLinkCollection(self, self.Net.Links.rows, 'Links')
        self.origin = 'MOCK_LIVE04_681_ZONES_NOT_NATIVE'
        src = folder / 'R1_2025_SYNTHETIC_LIVE04_COPY.ver'; src.write_bytes(b'SYNTHETIC_NOT_A_VISUM_VERSION')
        self.source = src; self.IO.CurrentVersionFile = str(src)
        self.matrix_writes = []; self.fail_matrix_write = set(); self.long_leak = float(long_leak)
        self.realizations = 0
        # The LIVE03 gravity response keeps its own smooth distance; 9697 below is the
        # mask authority with the 120/30 km cordon pairs.
        self.td_distance = np.array(self.component[9697].values, copy=True)
        i = np.arange(681)
        self.km = 2.0 + 0.25 * np.abs(i[:, None] - i[None, :])
        self.long_base = np.full((681, 681), 0.01) * (1.0 + 0.001 * (i[:, None] % 7))
        self.path_cells = np.zeros((681, 681), dtype=bool)
        for n, (o, d) in enumerate(self.path_keys):
            a, b = self.axis[o], self.axis[d]
            self.km[a, b] = 120.0 if n % 2 == 0 else 30.0
            self.long_base[a, b] = 0.5
            self.path_cells[a, b] = True
        self.support = self.km >= 80.0
        items = self.Net.Matrices.items
        replaced = []
        for m in items:
            if m.no in LONG_PERSON:
                start = self.long_base * self.support if masked_start else self.long_base.copy()
                replaced.append(Matrix4(self, m.no, start, code='LONG_%d' % m.no))
            elif m.no == 9697:
                replaced.append(Matrix4(self, 9697, self.km, code='R1_OSRM_DIST_KM'))
            elif m.no == 9116:
                replaced.append(Matrix4(self, 9116, m.values, code='FOREIGN'))
            else:
                replaced.append(m)
        for k, no in enumerate(LONG_VEHICLE):
            person = replaced[[x.no for x in replaced].index(9111 + k)].values
            replaced.append(Matrix4(self, no, self._vehicle(person, leak=0.0), code='LONG_VEH_%d' % no))
        formula = FormulaMatrix(self, 9305, LONG_VEHICLE)
        cl = next(ds for code, ds in self.dsegs.items() if code.upper() == 'NATIVE_CL')
        replaced = [formula if m.no == 9305 else m for m in replaced]
        cl.ODMatrix = formula
        self.Net.Matrices.items = replaced
        self.component = {m.no: m for m in replaced}
        self.fp_units = {}
        self._capture_fp_units()
        self._init_routes()
        self.executions = 0; self.writes.clear(); self.allowed_writes.clear()

    FP = {'ADD_PROD_W': 'FP_1_WORK_', 'ADD_PROD_S': 'FP_2_SERVICE_', 'ADD_PROD_L': 'FP_3_LONG_'}

    def _capture_fp_units(self):
        for r in self.Net.Zones.rows:
            for coef, prefix in self.FP.items():
                c = float(r.get(coef, 0.0) or 0.0)
                for k in [k for k in r if k.startswith(prefix)]:
                    self.fp_units[(r['NO'], k)] = (coef, float(r[k]) / c if c > 0 else 0.0)

    def _realize_fp(self):
        for r in self.Net.Zones.rows:
            for k in list(r):
                spec = self.fp_units.get((r['NO'], k))
                if spec is not None:
                    r[k] = spec[1] * float(r[spec[0]])

    def _td_factor(self, fam, base):
        if not hasattr(self, 'td_distance'):
            return super()._td_factor(fam, base)
        b0, c0 = self.base_td[fam]; b, c = self.td_family_params()[fam]
        D = self.td_distance
        f = np.power(D, (b - b0) * self.td_response) * np.exp((c - c0) * self.td_response * D)
        out = base * f
        rs0 = base.sum(axis=1, keepdims=True); rs1 = out.sum(axis=1, keepdims=True)
        return np.where(rs1 > 0, out * rs0 / np.where(rs1 > 0, rs1, 1.0), 0.0)

    def execute(self):
        active = [bool(o.values['ACTIVE']) for o in self.ops]
        super().execute()
        if active[4]:            # TG: FP_* follow the production coefficients
            self._realize_fp()
        if active[5]:            # TD: unmasked LONG person demand (v7 masks it afterwards)
            for no in LONG_PERSON:
                self.component[no].values = self.long_base.copy()
        if active[19]:           # assignment 20: route choice reacts to the new demand
            self._assign_routes()
        if active[10]:           # 20B realization: vehicle components + repaired reverse support
            self.realizations += 1
            for k, no in enumerate(LONG_VEHICLE):
                person = self.component[9111 + k].values
                self.component[no].values = self._vehicle(person, leak=self.long_leak)

    # ------------------------------------------------------------ route choice
    BYPASS = (990001, 990001, 990002)
    SIGMA0 = 0.8

    def _mode_c_codes(self):
        return [c for c, ds in self.dsegs.items() if parent_core().norm_code(ds.mode) == 'C']

    def _route_cells(self):
        keys = self.path_keys[:240]
        return np.array([self.axis[o] for o, _ in keys]), np.array([self.axis[d] for _, d in keys])

    def _init_routes(self):
        self.sigma = {}
        if self.route_gamma <= 0:
            return
        self.Net.Links.rows.append({'NO': self.BYPASS[0], 'FROMNODENO': self.BYPASS[1], 'TONODENO': self.BYPASS[2],
                                    'TSYSSET': 'C,C_noT,LNV,NV', 'ADDVAL1': 0.0, 'T0_PRTSYS(C)': 30.0,
                                    'CAPPRT': 1800.0, 'LENGTH': 0.5, 'TYPENO': 10})
        i, j = self._route_cells()
        self.route_base = {c: np.array(self.dsegs[c].ODMatrix.values[i, j], copy=True) for c in self._mode_c_codes()}
        self.sigma = {c: np.full(len(i), self.SIGMA0) for c in self.route_base}
        geo = self.geometry_rows['C']
        for o, d in self.path_keys[:240]:
            geo.append([o, d, 2, '', '', '', ''])
            geo.append(['', '', '', 1, *self.BYPASS])
        lists = self.Workbench.Lists
        lists.CreatePrTPathList = lambda: RouteList(self, 'parent')

    def _assign_routes(self):
        if self.route_gamma <= 0:
            return
        i, j = self._route_cells()
        for c, base in self.route_base.items():
            od = np.asarray(self.dsegs[c].ODMatrix.values)[i, j]
            ratio = np.where(base > 0, od / np.where(base > 0, base, 1.0), 1.0)
            self.sigma[c] = np.clip(self.SIGMA0 * np.power(np.maximum(ratio, 1e-9), -self.route_gamma), 0.05, 0.95)

    def _vehicle(self, person, *, leak):
        """Vehicle LONG only on OD pairs that have saved paths (path/OD parity of the fixture)."""
        return np.where(self.path_cells, 0.8 * person + leak * (~self.support), 0.0)

    def enable_long_school(self):
        super().enable_long_school()
        for r in self.Net.Zones.rows:
            r['FP_5_SCHOOL'] = 5.0
        for no in LONG_PERSON:
            self.component[no].values = self.long_base * self.support
        self._capture_fp_units()


class RouteList(FullList):
    """Parent path list with the cordon/bypass split of mode-C station-pair OD."""
    def SetObjects(self, origin, code, routefilter):
        super().SetObjects(origin, code, routefilter)
        h = self.host
        sigma = h.sigma.get(code)
        if sigma is None:
            return
        index = {key: n for n, key in enumerate(h.path_keys[:240])}
        rows = []
        for r in self.rows:
            n = index.get((r[0], r[1]))
            if n is None:
                rows.append(r); continue
            rows.append([r[0], r[1], 1, r[3] * sigma[n]])
            rows.append([r[0], r[1], 2, r[3] * (1.0 - sigma[n])])
        self.rows = rows


class WritableLinkObj(LinkObj):
    """ADDVAL1 is the only writable link attribute (integer value type, as in R1)."""
    def SetAttValue(self, name, value):
        h = self.host
        if str(name).upper() != 'ADDVAL1' or float(value) != int(value):
            h.writes.append('Link.SetAttValue:' + str(name))
            raise AssertionError('FORBIDDEN_LINK_WRITE:' + str(name))
        h.allowed_writes.append(('ADDVAL1', self.row['NO'], float(value)))
        self.row['ADDVAL1'] = float(value)


class WritableLinkCollection(LinkCollection):
    @property
    def GetAll(self):
        return [WritableLinkObj(self.host, r) for r in self.rows]
