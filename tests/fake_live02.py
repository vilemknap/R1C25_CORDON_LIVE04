"""Synthetic LIVE02 host: LIVE01 fixture + allowed TG writes + native recompute.

Never native PTV evidence.  Procedures.Execute() emulates TG(5)->TD(6)->matrix
realization->assignment with a deterministic gravity-like response:
  OD_ij(mutable work/service DSeg) = base_ij * P_i * A_j  (P/A from ADD/ZAHR)
Saved path volumes are read from ODMatrix values (as in the LIVE01 fixture), so
cordon pair volumes respond to TG parameters exactly like a fixed-route model.
"""
from types import SimpleNamespace
import numpy as np
from fake_live01 import Live01Visum, Attr, All, MatrixCollection
from fake_visum_startup import Guarded, Collection, Matrix, BusyError
from cordon2025.common import parent_core

WORK = ('NATIVE_CW', 'NATIVE_CW_NOT')
SERVICE = ('NATIVE_CS', 'NATIVE_CS_NOT')


class ZoneCollection(Collection):
    """Visum attribute IDs are case-insensitive (E_noC == E_NOC)."""
    def _key(self, name):
        if self.rows and name not in self.rows[0]:
            for k in self.rows[0]:
                if k.upper() == str(name).upper():
                    return k
        return name

    def GetMultiAttValues(self, name, *args):
        return super().GetMultiAttValues(self._key(name), *args)

    def SetMultiAttValues(self, attr, rows, *flag):
        attr = self._key(attr)
        h = self.host; h.touch('SetMultiAttValues:' + attr)
        h.allowed_writes.append(('ZONE', attr, len(rows)))
        if attr in h.fail_zone_write_attrs:
            raise RuntimeError('SYNTHETIC_ZONE_WRITE_FAILURE:' + attr)
        for index, value in rows:
            self.rows[int(index) - 1][attr] = float(value)
        if attr in h.zone_readback_corrupt:
            self.rows[0][attr] += 1.0


class LinkObj(Guarded):
    def __init__(self, host, row):
        super().__init__(host); self.row = row
    def AttValue(self, name):
        return self.row[name]


class LinkCollection(Collection):
    @property
    def GetAll(self):
        return [LinkObj(self.host, r) for r in self.rows]
    @property
    def Count(self):
        return len(self.rows)


class DSegCollection(Collection):
    @property
    def GetAll(self):
        return list(self.host.dsegs.values())
    @property
    def Count(self):
        return len(self.host.dsegs)


class Operation(Attr):
    def SetAttValue(self, name, value):
        h = self.host
        if name.upper() != 'ACTIVE':
            h.writes.append('SetAttValue:' + name)
            raise AssertionError('FORBIDDEN_MODEL_WRITE:SetAttValue:' + name)
        h.allowed_writes.append(('ACTIVE', id(self), int(value)))
        self.values['ACTIVE'] = bool(int(value))


class QualityList(Guarded):
    def __init__(self, host):
        super().__init__(host); self.columns = []
    def AddColumn(self, c):
        self.columns.append(c)
    @property
    def NumActiveElements(self):
        return len(self.host.quality_rows)
    def SaveToArray(self, first, last):
        return [tuple(r) for r in self.host.quality_rows[first - 1:last]]


class Procedures(Guarded):
    def __init__(self, host, ops):
        super().__init__(host); self.Operations = All(host, ops)
    def Execute(self):
        self.host.execute()


class IO(Guarded):
    def __init__(self, host, source):
        super().__init__(host); self.CurrentVersionFile = str(source)
    def SaveVersion(self, path):
        from pathlib import Path
        Path(path).write_bytes(b'SYNTHETIC_SAVED_VERSION:' + repr(self.host.zone_vector('ADD_PROD_W')[:16]).encode())
        self.host.saved_versions.append(str(path))
        self.CurrentVersionFile = str(path)


class Live02Visum(Live01Visum):
    def __init__(self, folder):
        super().__init__(folder)
        self.origin = 'MOCK_LIVE02_681_ZONES_NOT_NATIVE'
        self.allowed_writes = []; self.saved_versions = []; self.executions = 0
        self.fail_zone_write_attrs = set(); self.zone_readback_corrupt = set()
        self.fail_execute_on = set(); self.overwrite_after_execute = None
        self.nondeterministic_assignment = False; self.gap_value = 0.001
        self.change_frozen_matrix = False; self.change_td_on_execute = False
        self.response = 1.0
        # One-shot fault hooks keyed by Procedures.Execute() ordinal (1-based).
        self.overwrite_on = set(); self.frozen_change_on = set(); self.gap_by_execution = {}
        self.response_by_execution = {}; self.on_execute = None
        self.busy_on = set()
        # Version file marked as isolated copy.
        src = folder / 'R1_2025_SYNTHETIC_LIVE02_COPY.ver'; src.write_bytes(b'SYNTHETIC_NOT_A_VISUM_VERSION')
        self.source = src; self.IO = IO(self, src)
        zones = self.Net.Zones
        self.Net.Zones = ZoneCollection(self, zones.rows, 'Zones'); self.Net.Zones.Attributes = zones.Attributes
        for i, r in enumerate(self.Net.Zones.rows):
            r['NO'] = r['NO']
        links = []
        for i, r in enumerate(self.Net.Links.rows):
            r = dict(r); r.update({'ADDVAL1': 0.0, 'T0_PRTSYS(C)': 30.0 + i % 7, 'CAPPRT': 1800.0,
                                   'LENGTH': 0.5 + (i % 3) * 0.1, 'TYPENO': 10 + i % 4})
            links.append(r)
        self.Net.Links = LinkCollection(self, links, 'Links')
        self.Net.DemandSegments = DSegCollection(self, [{'CODE': c} for c in self.dsegs], 'DSegs')
        # Base demand for the gravity-like response.
        self.base_od = {parent_core().norm_code(c): np.array(ds.ODMatrix.values, copy=True) for c, ds in self.dsegs.items()}
        self.base_params = {a: self.zone_vector(a) for a in ('ADD_PROD_W', 'ADD_ATT_W', 'ADD_PROD_S', 'ADD_ATT_S', 'ADD_SALARY',
                                                             'ZAHR_PROD_WORK', 'ZAHR_ATR_WORK', 'ZAHR_PROD_SERV', 'ZAHR_ATR_SERV')}
        # Operations: keep LIVE01 inventory, make them writable for ACTIVE, add op 21 (type 65).
        old = self.Procedures.Operations.items
        ops = []
        for o in old:
            n = Operation(self, dict(o.values))
            for k, v in o.__dict__.items():
                if k not in ('host', 'values'):
                    setattr(n, k, v)
            ops.append(n)
        ops.append(Operation(self, {'OPERATIONTYPE': 65, 'ACTIVE': True, 'NAME': '12C COUNTLOCATION GEH COLOR', 'COMMENT': '12C'}))
        self.Procedures = Procedures(self, ops)
        self.ops = ops
        assign20 = ops[19].PrTAssignmentParameters.values['DSEGSET']
        self.quality_rows = [[assign20, 1, 0.01], [assign20, 2, self.gap_value]]
        lists = self.Workbench.Lists
        lists.CreatePrTAssQualityList = lambda: QualityList(self)
        self.component = {no: m for m in self.Net.Matrices.items for no in [m.no]}
        # Consistent converged start: component matrices realized from the base demand.
        self._recompute_demand()
        self.executions = 0; self.writes.clear()

    def enable_long_school(self):
        """Optional LSGEN attributes/matrices (absent in the default fixture)."""
        for r in self.Net.Zones.rows:
            r.update(ADD_PROD_L=0.2, ADD_ATT_L=1.0, ADD_PROD_SCH=1.0, ADD_ATT_SCH=1.0)
            for g in ('E_C', 'E_noC', 'noE_C', 'noE_noC', 'stud'):
                r['FP_3_LONG_' + g] = 10.0
        work = sum(np.array(ds.ODMatrix.values) for c, ds in self.dsegs.items()
                   if parent_core().norm_code(c) in WORK)
        self.Net.Matrices.items += [Matrix(self, 9226, work), Matrix(self, 9225, work * 0.1)]
        cl = sum(np.array(ds.ODMatrix.values) for c, ds in self.dsegs.items() if parent_core().norm_code(c) == 'NATIVE_CL')
        for m in self.Net.Matrices.items:
            if 9111 <= m.no <= 9115:
                m.values = cl / 5.0
        self.component = {m.no: m for m in self.Net.Matrices.items}

    def zone_vector(self, attr):
        return np.array([float(r[attr]) for r in self.Net.Zones.rows])

    def execute(self):
        self.executions += 1
        self.touch('Procedures.Execute')
        if self.executions in self.fail_execute_on:
            raise RuntimeError('SYNTHETIC_PROCEDURE_FAILURE')
        if self.executions in self.busy_on:
            raise BusyError('Volany odmitl volani (synthetic RPC_E_CALL_REJECTED)')
        if self.on_execute is not None:
            self.on_execute(self)
        self.response = self.response_by_execution.get(self.executions, self.response)
        active = [bool(o.values['ACTIVE']) for o in self.ops]
        if active[4] and active[5]:
            self._recompute_demand()
        self._post_execute()

    def _recompute_demand(self):
        if True:
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
                    v = self.base_od[norm] * np.outer(pw, aw); work_total += v
                elif norm in SERVICE:
                    v = self.base_od[norm] * np.outer(ps, as_); serv_total += v
                else:
                    continue
                if self.nondeterministic_assignment:
                    v = v * (1 + 1e-9 * self.executions)
                ds.ODMatrix.values = v
            for k, no in enumerate(range(9101, 9106)):
                self.component[no].values = work_total / 5.0
            for k, no in enumerate(range(9106, 9111)):
                self.component[no].values = serv_total / 5.0

    def _post_execute(self):
        if self.change_frozen_matrix or self.executions in self.frozen_change_on:
            self.component[9116].values = self.component[9116].values + 1.0
        if self.change_td_on_execute:
            td = self.ops[5].TripDistributionParameters
            g = next(iter(td.strata.values())).GravitationParameters
            g.values['PARA_B'] = g.values['PARA_B'] + 0.01
        if self.overwrite_after_execute and (not self.overwrite_on or self.executions in self.overwrite_on):
            attr, zone_index, value = self.overwrite_after_execute
            self.Net.Zones.rows[zone_index][attr] = value
        it = self.quality_rows[-1][1] + 1
        self.quality_rows.append([self.quality_rows[-1][0], it, self.gap_by_execution.get(self.executions, self.gap_value)])
