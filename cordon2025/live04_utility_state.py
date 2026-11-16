"""Transactional state of the user's iterative TD utility script (9700..9715).

Each proposal starts with the accepted utility state. Recomputing/restoring the
parent suppresses the updater and uses exactly those matrices. Native TG/TD
still generates all demand; this module never restores/writes OD demand.
"""
from pathlib import Path
from contextlib import nullcontext, contextmanager
from contextvars import ContextVar
import ast
import hashlib
import json
import os
import re
import threading
import numpy as np

from .common import require, parent_module, canonical_hash, ContractError
from .io import write_json, mkdir

COMPONENTS = ('WORK_E_C', 'WORK_E_noC', 'WORK_noE_C', 'WORK_noE_noC', 'WORK_stud',
              'SERV_E_C', 'SERV_E_noC', 'SERV_noE_C', 'SERV_noE_noC', 'SERV_stud',
              'LONG_E_C', 'LONG_E_noC', 'LONG_noE_C', 'LONG_noE_noC', 'LONG_stud', 'SCHOOL')
NUMBERS = tuple(range(9700, 9716))
SPECS = tuple(zip(NUMBERS, COMPONENTS))
FLOW_NUMBERS = {'NATIVE_CW': 9301, 'NATIVE_CW_NOT': 9302, 'NATIVE_CS': 9303, 'NATIVE_CS_NOT': 9304}
INPUT_PROTOCOL = 'ACCEPTED_PARENT_INPUTS_V1'
_INPUT_SCOPE = ContextVar('r1_cordon_accepted_utility_inputs', default=None)


def transaction_inputs(visum, zone_order, live_bindings):
    """Read-only protocol called by the replacement native Run script."""
    scope = _INPUT_SCOPE.get()
    if scope is None:
        return None
    require(threading.get_ident() == scope['thread'], 'TD_UTILITY_INPUT_THREAD_CHANGED')
    owner = scope['owner']
    raw = getattr(owner.adapter, 'raw_visum', None)
    if raw is None:
        raw = getattr(owner.adapter.visum, '_obj', owner.adapter.visum)
    same = visum is raw
    if not same:
        a, b = getattr(visum, '_oleobj_', None), getattr(raw, '_oleobj_', None)
        same = a is not None and b is not None and a == b
    require(same, 'TD_UTILITY_INPUT_MODEL_CHANGED')
    require(list(zone_order) == owner.parent_record['zones'], 'TD_UTILITY_INPUT_ZONE_ORDER_CHANGED')
    times = {};bindings = {}
    for no, (dseg, code) in owner.time_specs.items():
        bindings.setdefault(dseg, {})[code] = no
    require(live_bindings == bindings, 'TD_UTILITY_INPUT_BINDINGS_CHANGED')
    for dseg, pair in bindings.items():
        times[dseg] = tuple(owner.parent[pair[code]] for code in ('TTC', 'TT0'))
    evidence = {'source': INPUT_PROTOCOL, 'parent_state_hash': owner.parent_state_hash,
                'bindings': bindings,
                'time_hashes': {d: [values_hash(a) for a in pair] for d, pair in times.items()},
                'weight_hashes': {d: values_hash(a) for d, a in owner.parent_flows.items()},
                'zone_order_sha256': hashlib.sha256(json.dumps(list(zone_order), separators=(',', ':')).encode()).hexdigest()}
    scope['reads'] += 1
    return times, owner.parent_flows, evidence


def values_hash(values):
    return hashlib.sha256(np.ascontiguousarray(values, dtype='<f8').tobytes()).hexdigest()


def parameters(state):
    return tuple(state.get(k) for k in ('generation_hash', 'td_hash', 'addval_hash'))


class UtilityState:
    def __init__(self, adapter):
        self.adapter = adapter
        self.com = parent_module('r1_15a2_com_compat')
        self.parent = None
        self.parent_record = None
        self.parent_parameters = None
        self.parent_state_hash = None
        self.parent_flows = None
        self.update_script_path = None
        self.update_script_sha256 = None
        self.update_script_attribute = None
        self.update_script_reference = None
        self.time_specs = {}
        self.specs = SPECS
        self.position = int((adapter.live02.get('evaluation') or {}).get('td_utility_update_position', 15))
        collection = self.call(lambda: adapter.visum.Net.Matrices.GetAll, 'INVENTORY')
        items = self.call(collection, 'INVENTORY_ITEMS') if callable(collection) else collection
        items = list(items)
        found = {self.com.exact_int(self.call(lambda m=m: m.AttValue('NO'), 'NO'), 'Matrix.NO') for m in items}
        self.enabled = bool(found.intersection(NUMBERS))
        if self.enabled:
            require(set(NUMBERS) <= found, 'TD_UTILITY_STATE_INCOMPLETE_9700_9715')
            required = ('NATIVE_CW', 'NATIVE_CW_NOT', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CL')
            bindings = {}
            od_numbers = set()
            flow_bindings = {}
            dsegs = self.call(lambda: adapter.visum.Net.DemandSegments.GetAll, 'DSEGS')
            for ds in (self.call(dsegs, 'DSEG_ITEMS') if callable(dsegs) else dsegs):
                try:
                    od = self.call(lambda: ds.ODMatrix, 'OD_OBJECT')
                except Exception as exc:
                    # A DSeg without an allocated OD matrix raises in Visum COM instead of
                    # returning None (as rt.list_dsegs treats it). It binds no OD number.
                    if 'NO OD DEMAND MATRIX' not in str(exc).upper():
                        raise
                    od = None
                if od is not None:
                    no = self.com.exact_int(self.call(lambda: od.AttValue('NO'), 'OD_BINDING'), 'ODMatrix.NO')
                    od_numbers.add(no)
                    code = str(self.call(lambda: ds.AttValue('CODE'), 'DSEG_CODE')).strip().upper()
                    if code in FLOW_NUMBERS:
                        require(code not in flow_bindings and no == FLOW_NUMBERS[code], 'TD_UTILITY_WEIGHT_BINDING_CHANGED')
                        flow_bindings[code] = no
            require(flow_bindings == FLOW_NUMBERS, 'TD_UTILITY_WEIGHT_BINDINGS_MISSING')
            for obj in items:
                code = str(self.call(lambda: obj.AttValue('CODE'), 'SKIM_CODE')).strip().upper()
                if code not in ('TTC', 'TT0'):
                    continue
                dseg = str(self.call(lambda: obj.AttValue('DSEGCODE'), 'SKIM_DSEG')).strip().upper()
                if dseg not in required:
                    continue
                no = self.com.exact_int(self.call(lambda: obj.AttValue('NO'), 'SKIM_NO'), 'NO')
                require((dseg, code) not in bindings and no not in NUMBERS + (9002,) and no not in od_numbers,
                        'TD_UTILITY_INPUT_SKIM_OVERLAP_OR_DUPLICATE')
                bindings[dseg, code] = no
                self.time_specs[no] = (dseg, code)
            require(len(bindings) == 10 and len(self.time_specs) == 10,
                    'TD_UTILITY_INPUT_SKIMS_MISSING')
            self.specs = SPECS + tuple((no, ':'.join(spec)) for no, spec in sorted(self.time_specs.items()))
            self.validate_operation()
            self.read()  # validate identity, DATA source, shape and positivity before any write

    def call(self, func, label):
        evaluator = getattr(self.adapter, 'evaluator', None)
        control = getattr(evaluator, 'control', None)
        def attempt():
            if control is not None:
                control.checkpoint('TD_UTILITY_STATE_' + label)
            return func()
        return self.com.com_call_with_retry(attempt, label='TD_UTILITY_STATE_' + label,
                                            retry_policy=getattr(self.adapter, 'com_retry_policy', None) or {})

    def validate_operation(self):
        rows = self.com.operation_rows(self.adapter.visum)
        types = {int(r['no']): int(r['type']) for r in rows}
        td = [p for p, t in types.items() if t == self.com.TD and rows[p-1]['active']]
        require(len(td) == 1 and types.get(self.position) == 65 and self.position < td[0],
                'TD_UTILITY_UPDATE_POSITION_MUST_BE_RUN_SCRIPT_BEFORE_TD')
        self.validate_script(rows[self.position-1])
        params = rows[td[0]-1]['object'].TripDistributionParameters
        for no, component in SPECS:
            prefix = '1_' if component.startswith('WORK_') else '2_' if component.startswith('SERV_') else '3_' if component.startswith('LONG_') else '5_'
            obj = self.call(lambda: params.TripDistributionDStratParameters(prefix + component), 'STRATUM')
            candidates = [obj]
            for field in ('GravitationParameters', 'GravityParameters', 'DistributionParameters'):
                try:
                    candidates.append(self.call(lambda: getattr(obj, field), field))
                except Exception as exc:
                    if self.com.is_retryable_com_error(exc):
                        raise
            value = None
            for candidate in candidates:
                for field in ('UTILITYFUNCTION', 'UtilityFunction', 'UTILITYMATRIX', 'UtilityMatrix',
                              'UTILITYMATRIXREF', 'IMPEDANCEMATRIX', 'IMPEDANCEMATRIXREF', 'SKIMMATRIXREF'):
                    try:
                        value = self.call(lambda: candidate.AttValue(field), 'UTILITY_REFERENCE')
                        break
                    except Exception as exc:
                        if self.com.is_retryable_com_error(exc):
                            raise
                if value is not None:
                    break
            token = str(value).strip()
            match = re.fullmatch(r'Matrix\(\s*\[NO\]\s*=\s*(\d+)\s*\)', token, re.I)
            target = int(match.group(1)) if match else int(token) if token.isdigit() else None
            require(target == no, 'TD_UTILITY_REFERENCE_CHANGED:' + component)

    def _read_opt(self, obj, names, label):
        """First readable AttValue of names (non-retryable read errors mean 'not available')."""
        for name in names:
            try:
                return name, self.call(lambda: obj.AttValue(name), label)
            except Exception as exc:
                if self.com.is_retryable_com_error(exc):
                    raise
        return None, None

    def script_source(self, row):
        """(reference, bytes) of the Run-script code of operation row.

        Visum 2026 keeps the script parameters on Operation.ExecuteScriptParameters
        (procedure XML: <EXECUTESCRIPTPARA FILENAME=.. USEINTERNALSCRIPTCODE=..>), and the
        R1 procedure embeds every script (USEINTERNALSCRIPTCODE=1, FILENAME=""). Embedded
        code is read from INTERNALSCRIPTCODE; otherwise FILENAME (relative to the .ver).
        The legacy Operation.SCRIPTFILE reference is still accepted.
        """
        op = row['object']; tried = []
        for accessor in ('ExecuteScriptParameters', 'RunScriptParameters', 'ScriptParameters'):
            try:
                params = self.call(lambda: getattr(op, accessor), 'SCRIPT_PARAMETERS')
            except Exception as exc:
                if self.com.is_retryable_com_error(exc):
                    raise
                tried.append(accessor + ':NONE'); continue
            if params is None:
                tried.append(accessor + ':NONE'); continue
            _, internal = self._read_opt(params, ('USEINTERNALSCRIPTCODE', 'UseInternalScriptCode'), 'SCRIPT_INTERNAL_FLAG')
            code_attr, code = self._read_opt(params, ('INTERNALSCRIPTCODE', 'InternalScriptCode', 'SCRIPTCODE'), 'SCRIPT_CODE')
            file_attr, filename = self._read_opt(params, ('FILENAME', 'FileName', 'SCRIPTFILE', 'ScriptFile'), 'SCRIPT_FILE')
            tried.append('%s:internal=%r,code=%s,file=%r' % (accessor, internal, code_attr if code is not None else None, filename))
            use_internal = internal is not None and str(internal).strip().lower() not in ('0', 'false', '0.0', '')
            self.script_read_trace = list(tried)
            if use_internal and isinstance(code, str) and code.strip():
                return ('INTERNAL', accessor), code.encode('utf-8')
            if not use_internal and isinstance(filename, str) and filename.strip():
                path = Path(os.path.expandvars(filename.strip().strip('"')))
                if not path.is_absolute():
                    source = self.call(lambda: self.adapter.visum.IO.CurrentVersionFile, 'MODEL_FILE')
                    path = Path(source).parent / path
                require(path.is_file(), 'TD_UTILITY_UPDATE_SCRIPT_FILE_MISSING:' + str(path))
                return ('FILE', accessor, str(path)), path.read_bytes()
        from .live01_visum import script_references
        source = self.call(lambda: self.adapter.visum.IO.CurrentVersionFile, 'MODEL_FILE')
        refs = script_references([row], source)
        self.script_read_trace = tried + ['legacy:%d' % len(refs)]
        if len(refs) == 1:
            return ('FILE', refs[0]['attribute'], refs[0]['path']), Path(refs[0]['path']).read_bytes()
        raise ContractError('TD_UTILITY_UPDATE_SCRIPT_REFERENCE_UNREADABLE:' + ';'.join(tried))

    def script_diagnostic(self, row, reference, data, markers, parse_error):
        """Short text for the error + full copy of the code actually read (run folder)."""
        text = data.decode('utf-8', 'replace')
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        info = {'operation_no': row.get('no'), 'operation_type': row.get('type'),
                'operation_comment': str(row.get('comment', ''))[:120], 'reference': list(reference),
                'read_trace': list(getattr(self, 'script_read_trace', [])), 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(), 'lines': len(text.splitlines()),
                'first_lines': lines[:3], 'markers_found': markers, 'parse_error': parse_error,
                'contains_protocol_text': INPUT_PROTOCOL in text,
                'expected_marker': "R1_TD_INPUT_PROTOCOL = '%s'" % INPUT_PROTOCOL}
        folder = getattr(self.adapter, 'folder', None)
        if folder is not None:
            try:
                out = Path(folder) / 'TD_UTILITY_OPERATION_SCRIPT_DIAG'
                mkdir(out)
                (out / 'OPERATION_SCRIPT_AS_READ.py.txt').write_bytes(data)
                write_json(out / 'OPERATION_SCRIPT_DIAG.json', info)
                info['saved_to'] = str(out)
            except Exception as exc:
                info['save_error'] = repr(exc)[:120]
        return json.dumps(info, ensure_ascii=False)

    def validate_script(self, row):
        reference, data = self.script_source(row)
        require(self.update_script_reference is None or reference == self.update_script_reference,
                'TD_UTILITY_UPDATE_SCRIPT_REFERENCE_CHANGED')
        self.update_script_reference = reference
        self.update_script_path = reference[-1] if reference[0] == 'FILE' else 'INTERNAL_SCRIPT_CODE'
        try:
            tree = ast.parse(data)
            markers = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                       and any(isinstance(t, ast.Name) and t.id == 'R1_TD_INPUT_PROTOCOL' for t in n.targets)]
            parse_error = None
        except SyntaxError as exc:
            markers, parse_error = [], repr(exc)[:200]
        if markers != [INPUT_PROTOCOL]:
            raise ContractError('TD_UTILITY_REPLACE_OPERATION_SCRIPT_WITH_RUN_R1_TD_UTILITY_TRANSACTIONAL:'
                                + self.script_diagnostic(row, reference, data, markers, parse_error))
        digest = hashlib.sha256(data).hexdigest()
        require(self.update_script_sha256 is None or digest == self.update_script_sha256,
                'TD_UTILITY_SCRIPT_CHANGED_DURING_CALIBRATION')
        self.update_script_sha256 = digest

    def matrix(self, no, component):
        obj = self.call(lambda: self.adapter.visum.Net.Matrices.ItemByKey(no), 'OBJECT_%d' % no)
        require(self.com.exact_int(self.call(lambda: obj.AttValue('NO'), 'IDENTITY'), 'NO') == no,
                'TD_UTILITY_STATE_NUMBER_CHANGED')
        expected_code = self.time_specs[no][1] if no in self.time_specs else 'R1_TD_U_' + component
        actual_code = str(self.call(lambda: obj.AttValue('CODE'), 'CODE')).strip()
        require((actual_code.upper() if no in self.time_specs else actual_code) == expected_code,
                'TD_UTILITY_STATE_CODE_COLLISION:%d' % no)
        if no in self.time_specs:
            require(str(self.call(lambda: obj.AttValue('DSEGCODE'), 'DSEGCODE')).strip().upper() == self.time_specs[no][0],
                    'TD_UTILITY_SKIM_BINDING_CHANGED:%d' % no)
        def enum(field, tokens):
            value = self.call(lambda: obj.AttValue(field), field)
            token = ''.join(c for c in str(value).upper() if c.isalnum())
            expected = {'DATASOURCETYPE': 1, 'OBJECTTYPEREF': 2, 'MATRIXTYPE': 4}[field]
            try:
                numeric = float(value) == expected
            except (TypeError, ValueError, OverflowError):
                numeric = False
            require(not isinstance(value, (bool, np.bool_)) and (token in tokens or numeric),
                    'TD_UTILITY_STATE_INVALID_' + field)
        enum('DATASOURCETYPE', {'DATA', 'DATASOURCETYPEDATA', '1'})
        enum('OBJECTTYPEREF', {'ZONE', 'ZONES', 'OBJECTTYPEREFZONE', '2'})
        enum('MATRIXTYPE', {'SKIM', 'MATRIXTYPESKIM', '4'})
        return obj

    def axis(self):
        rows = self.call(lambda: self.adapter.visum.Net.Zones.GetMultiAttValues('NO'), 'ZONE_ORDER')
        zones = tuple(self.com.exact_int(v, 'zone.NO') for _, v in rows)
        require(zones and len(set(zones)) == len(zones), 'TD_UTILITY_STATE_INVALID_ZONE_ORDER')
        return zones

    def read(self):
        if not self.enabled:
            return {}, None
        zones = self.axis(); n = len(zones); off = ~np.eye(n, dtype=bool)
        values = {}
        for no, component in self.specs:
            obj = self.matrix(no, component)
            a = np.array(self.call(obj.GetValues, 'VALUES_%d' % no), dtype=np.float64, copy=True)
            require(a.shape == (n, n) and np.isfinite(a).all()
                    and (no in self.time_specs or ((a >= 0).all() and (a[off] > 0).all())),
                    'TD_UTILITY_STATE_INVALID_VALUES:%d' % no)
            a.flags.writeable = False
            values[no] = a
        for dseg in {spec[0] for spec in self.time_specs.values()}:
            pair = {code: values[no] for no, (ds, code) in self.time_specs.items() if ds == dseg}
            require(np.any((pair['TTC'] > 0) & (pair['TT0'] > 0) & off),
                    'TD_UTILITY_REQUIRES_COMPLETED_TIME_SKIMS:' + dseg)
        record = {'schema': 'LIVE04_TD_UTILITY_STATE_V1', 'zones': list(zones),
                  'update_script_sha256': self.update_script_sha256,
                  'input_skims': {str(no): list(spec) for no, spec in self.time_specs.items()},
                  'matrix_sha256': {str(no): values_hash(a) for no, a in values.items()}}
        record['sha256'] = canonical_hash(record)
        return values, record

    def augment_snapshot(self, snapshot):
        if not self.enabled:
            return snapshot
        # Like the native snapshot, finish bounded readback even during STOP.
        # A partial observation must not turn a successful recovery into UNKNOWN.
        with self.readback_scope():
            self.validate_operation()
            _, record = self.read()
        result = dict(snapshot, td_utility_state=record)
        result['state_hash'] = canonical_hash({'native_state_hash': snapshot['state_hash'], 'td_utility_state': record})
        return result

    def set_parent(self, state, folder):
        if not self.enabled:
            return
        with self.readback_scope():
            values, record = self.read()
            expected = {int(r['matrix_no']): r['sha256_float64_le'] for r in state.get('matrices', [])}
            flows = {}
            for code, no in FLOW_NUMBERS.items():
                matrix = self.call(lambda: self.adapter.visum.Net.Matrices.ItemByKey(no), 'WEIGHT_MATRIX')
                a = np.array(self.call(matrix.GetValues, 'PARENT_WEIGHT'), dtype=np.float64, copy=True)
                require(a.shape == (len(record['zones']),)*2 and np.isfinite(a).all() and (a >= 0).all()
                        and expected.get(no) == values_hash(a), 'TD_UTILITY_PARENT_WEIGHT_SNAPSHOT_CHANGED')
                a.flags.writeable = False
                flows[code] = a
        require(record == state.get('td_utility_state'), 'TD_UTILITY_PARENT_SNAPSHOT_CHANGED')
        self.parent, self.parent_record = values, record
        self.parent_flows = flows
        self.parent_parameters = parameters(state)
        self.parent_state_hash = state['state_hash']
        folder = Path(folder); mkdir(folder)
        write_json(folder / 'TD_UTILITY_PARENT.json', dict(record, state_hash=state['state_hash'],
                   weight_sha256={d: values_hash(a) for d, a in flows.items()}))

    @contextmanager
    def input_scope(self, plan):
        if not self.enabled:
            yield
            return
        require(_INPUT_SCOPE.get() is None, 'TD_UTILITY_NESTED_INPUT_SCOPE')
        scope = {'owner': self, 'thread': threading.get_ident(), 'reads': 0}
        token = _INPUT_SCOPE.set(scope)
        try:
            yield
        except BaseException:
            raise
        else:
            if self.position in plan['selected_operation_positions']:
                require(scope['reads'] == 2, 'TD_UTILITY_NATIVE_SCRIPT_MUST_USE_PARENT_INPUTS_ONCE')
        finally:
            _INPUT_SCOPE.reset(token)

    def readback_scope(self):
        control = getattr(getattr(self.adapter, 'evaluator', None), 'control', None)
        recovery = getattr(control, 'recovery', None)
        return recovery('TD_AUXILIARY_STATE_READBACK') if callable(recovery) else nullcontext()

    def restore(self):
        require(self.parent is not None, 'TD_UTILITY_PARENT_NOT_CAPTURED')
        current, record = self.read()
        require(record['zones'] == self.parent_record['zones'], 'TD_UTILITY_PARENT_ZONE_ORDER_CHANGED')
        audit = getattr(self.adapter.visum, '_audit', None)
        require(audit is not None, 'TD_UTILITY_RESTORE_REQUIRES_WRITE_GUARD')
        previous = getattr(audit, 'td_utility_restore_expected', None)
        previous_times = getattr(audit, 'td_time_restore_numbers', None)
        audit.td_utility_restore_expected = {no: values_hash(a) for no, a in self.parent.items()}
        audit.td_time_restore_numbers = frozenset(self.time_specs)
        changed = []
        try:
            for no, component in self.specs:
                if record['matrix_sha256'][str(no)] == self.parent_record['matrix_sha256'][str(no)]:
                    continue
                obj = self.matrix(no, component)
                changed.append(no)  # the setter can mutate and then raise
                self.call(lambda: obj.SetValues(np.array(self.parent[no], copy=True), False), 'RESTORE_%d' % no)
                got = np.asarray(self.call(obj.GetValues, 'READBACK_%d' % no), dtype=np.float64)
                require(got.shape == self.parent[no].shape and values_hash(got) == self.parent_record['matrix_sha256'][str(no)],
                        'TD_UTILITY_RESTORE_READBACK:%d' % no)
        finally:
            audit.td_utility_restore_expected = previous
            audit.td_time_restore_numbers = previous_times
            if changed:
                invalidate = getattr(self.adapter, 'invalidate_candidate_readback', None)
                if invalidate is not None:
                    invalidate('TD_UTILITY_PARENT_RESTORED', mutation=True)
        if changed:
            require(self.read()[1] == self.parent_record, 'TD_UTILITY_FINAL_RESTORE_DIFFERS')
        return changed

    def prepare(self, plan, folder, current):
        if not self.enabled:
            return plan
        require(self.parent is not None, 'TD_UTILITY_PARENT_NOT_CAPTURED')
        self.validate_operation()
        is_parent = parameters(current) == self.parent_parameters
        if plan.get('restore_parent_state_hash') is not None:
            require(plan['restore_parent_state_hash'] == self.parent_state_hash and is_parent,
                    'TD_UTILITY_RESTORE_WRONG_PARENT')
        changed = self.restore()
        result = dict(plan)
        if is_parent:
            result['selected_operation_positions'] = [p for p in plan['selected_operation_positions'] if int(p) != self.position]
        result['td_utility_transaction'] = {'parent_state_hash': self.parent_state_hash,
                 'input_protocol': INPUT_PROTOCOL,
                 'weight_sha256': {d: values_hash(a) for d, a in self.parent_flows.items()},
                 'parent_utility_sha256': self.parent_record['sha256'], 'restored_matrices': changed,
                 'update_position': self.position, 'updater_suppressed': is_parent,
                 'reason': 'PARENT_RECOMPUTE_NO_SECOND_DAMPING' if is_parent else 'CANDIDATE_FROM_ACCEPTED_UTILITY'}
        folder = Path(folder); mkdir(folder)
        write_json(folder / 'TD_UTILITY_TRANSACTION.json', result['td_utility_transaction'])
        return result

    def finish(self, plan, folder):
        """Parent recompute may calculate skims again; reinstate its original epoch.

        All demand has already been regenerated natively using those inputs.
        The existing assignment/path-equivalence proof is still mandatory.
        """
        if self.enabled and plan.get('td_utility_transaction', {}).get('updater_suppressed'):
            changed = self.restore()
            write_json(Path(folder) / 'TD_UTILITY_POST_RECOMPUTE_RESTORE.json',
                       {'restored_matrices': changed, 'parent_state_hash': self.parent_state_hash,
                        'parent_auxiliary_sha256': self.parent_record['sha256']})
