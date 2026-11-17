# -*- coding: utf-8 -*-
"""Read-only export of the existing PrT DIS skims and the fixed 9697 distance matrix.

Run in Visum > Scripts > Execute script file after assignment and skim operations.
The script does not calculate skims or change any matrix. DIS is the route-volume
average trip distance of the saved assignment; its freshness is not certified
by reading a matrix. Output is an NPZ archive plus a small JSON/CSV audit beside
the opened version, in a new R1_DISTANCE_EXPORT_* directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np


SEGMENTS = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT',
            'NATIVE_CW', 'NATIVE_CW_NOT')
NO_PATHS_KM = 999999.0


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _items(collection):
    member = collection.GetAll
    return list(member() if callable(member) else member)


def _zone_axis(visum):
    rows = visum.Net.Zones.GetMultiAttValues('NO')
    pairs = sorted((int(index), int(no)) for index, no in rows)
    axis = np.asarray([no for _, no in pairs], dtype=np.int64)
    if len(axis) == 0 or len(set(axis.tolist())) != len(axis):
        raise RuntimeError('DIST_EXPORT_INVALID_ZONE_AXIS')
    return axis


def _inventory(visum):
    found = {}
    for matrix in _items(visum.Net.Matrices):
        code = str(matrix.AttValue('CODE')).strip().upper()
        dseg = str(matrix.AttValue('DSEGCODE')).strip().upper()
        if (code, dseg) not in ({('DIS', s) for s in SEGMENTS} | {('R1_OSRM_DIST_KM', '')}):
            continue
        key = (code, dseg)
        if key in found:
            raise RuntimeError('DIST_EXPORT_DUPLICATE_MATRIX:' + repr(key))
        found[key] = matrix
    required = {('DIS', s) for s in SEGMENTS} | {('R1_OSRM_DIST_KM', '')}
    if set(found) != required:
        raise RuntimeError('DIST_EXPORT_MISSING_MATRICES:' + repr(sorted(required - set(found))))
    if int(found['R1_OSRM_DIST_KM', ''].AttValue('NO')) != 9697:
        raise RuntimeError('DIST_EXPORT_9697_IDENTITY_CHANGED')
    return found


def _read(matrix, n, *, reference=False):
    values = np.asarray(matrix.GetValues(), dtype=np.float64)
    if values.shape != (n, n) or not np.isfinite(values).all() or (values < 0).any():
        raise RuntimeError('DIST_EXPORT_INVALID_VALUES:' + str(matrix.AttValue('NO')))
    if reference and (values >= NO_PATHS_KM).any():
        raise RuntimeError('DIST_EXPORT_9697_HAS_NO_PATH_SENTINEL')
    return values


def _compare(axis, reference, distance):
    off = ~np.eye(len(axis), dtype=bool)
    valid = off & (distance < NO_PATHS_KM) & (reference < NO_PATHS_KM)
    delta = distance - reference
    ad = np.abs(delta)
    changed = valid & (ad >= 5.0)
    top = np.flatnonzero(changed)
    if len(top) > 100:
        top = top[np.argpartition(ad.flat[top], -100)[-100:]]
    top = sorted(top, key=lambda k: (-ad.flat[k], int(k)))
    pairs = []
    for k in top:
        i, j = divmod(int(k), len(axis))
        pairs.append([int(axis[i]), int(axis[j]), float(reference[i, j]),
                      float(distance[i, j]), float(delta[i, j])])
    return {
        'valid_offdiagonal_pairs': int(valid.sum()),
        'no_path_offdiagonal_pairs': int((off & (distance >= NO_PATHS_KM)).sum()),
        'pairs_difference_at_least_5_km': int(changed.sum()),
        'max_absolute_difference_km': float(ad[valid].max()) if valid.any() else None,
        'mean_absolute_difference_km': float(ad[valid].mean()) if valid.any() else None,
    }, pairs


def export(visum, *, output_parent=None):
    source = Path(str(visum.IO.CurrentVersionFile).strip())
    if not source.is_file() or source.suffix.lower() not in ('.ver', '.verx'):
        raise RuntimeError('DIST_EXPORT_OPEN_SAVED_VERSION_FIRST:' + str(source))
    axis = _zone_axis(visum)
    matrices = _inventory(visum)
    values = {}
    provenance = {}
    for key in [('R1_OSRM_DIST_KM', '')] + [('DIS', s) for s in SEGMENTS]:
        obj = matrices[key]
        label = 'M9697' if key[0] != 'DIS' else 'DIS_' + key[1]
        a = _read(obj, len(axis), reference=(label == 'M9697'))
        values[label] = a
        provenance[label] = {'matrix_no': int(obj.AttValue('NO')), 'code': key[0],
                             'dseg': key[1], 'sum_km': float(a.sum()),
                             'sha256_float64_le': hashlib.sha256(
                                 np.ascontiguousarray(a, dtype='<f8').tobytes()).hexdigest()}
    out = Path(output_parent or source.parent) / ('R1_DISTANCE_EXPORT_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    try:
        data_path = out / 'CURRENT_VISUM_DISTANCES.npz'
        with (out / 'CURRENT_VISUM_DISTANCES.npz.tmp').open('wb') as stream:
            np.savez_compressed(stream, zone_no=axis, **values)
        (out / 'CURRENT_VISUM_DISTANCES.npz.tmp').replace(data_path)
        stats = {}
        csv_path = out / 'LARGEST_DISTANCE_DIFFERENCES.csv'
        with csv_path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, delimiter=';')
            writer.writerow(('dseg', 'origin_zone_no', 'destination_zone_no',
                             'osrm_9697_km', 'visum_dis_km', 'difference_km'))
            for seg in SEGMENTS:
                stat, pairs = _compare(axis, values['M9697'], values['DIS_' + seg])
                stats[seg] = stat
                for pair in pairs:
                    writer.writerow((seg, *pair))
        report = {
            'status': 'EXPORTED_READ_ONLY', 'source_version': str(source),
            'source_version_sha256': _sha256_file(source),
            'zone_count': len(axis), 'matrix_provenance': provenance,
            'comparison_to_9697': stats, 'npz_sha256': _sha256_file(data_path),
            'distance_semantics': 'VISUM_DIS_ROUTE_VOLUME_AVERAGE_OF_SAVED_ASSIGNMENT',
            'freshness_certified': False,
            'note': 'Run assignment and PrT skims after the latest network edits before this export. '
                    'No matrix, procedure or model version was changed.',
        }
        (out / 'RESULT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report
    except BaseException:
        (out / 'INCOMPLETE.txt').write_text('Export incomplete; ignore this directory.\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    export(Visum)
