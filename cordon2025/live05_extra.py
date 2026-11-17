"""LIVE05 extra observations (NDS profiles, ASD profiles, K1/K2 movements): network check.

The rows themselves live in the observation contract (live03_observations) and in the
incidence (live03_incidence.extra_contributions).  This module only proves at the run
start that every directed link the extra rows use exists in the open network and is
open for cars; a missing link would make its row unmatchable (model 0) and stops a
native run before the first write.
"""
import csv
from pathlib import Path

from .common import canonical_hash, require
from .io import write_json

SCHEMA = 'LIVE05_EXTRA_OBSERVATION_LINKS_V1'


def check_links(visum, contract, folder=None, *, native=True, source_version=None):
    links = sorted(contract.extra_links()) if getattr(contract, 'extra_rows', None) else []
    out = {'schema': SCHEMA, 'links': len(links), 'missing': [], 'closed_for_car': [], 'status': 'NOT_USED',
           'read_only': True, 'source_version': source_version}
    net = {}
    if links:
        try:
            coll = visum.Net.Links
            # all network objects (OnlyActive=False); columns joined by the object index, not by order
            cols = {a: dict(coll.GetMultiAttValues(a, False)) for a in ('NO', 'FROMNODENO', 'TONODENO', 'TSYSSET')}
        except Exception as exc:
            require(not native, 'LIVE05_EXTRA_LINKS_UNREADABLE:%s' % exc)
            cols = {a: {} for a in ('NO', 'FROMNODENO', 'TONODENO', 'TSYSSET')}
        indices = set(cols['NO'])
        require(all(set(c) == indices for c in cols.values()), 'LIVE05_EXTRA_LINK_COLUMN_COVERAGE_MISMATCH')
        for i, no in cols['NO'].items():
            key = (int(no), int(cols['FROMNODENO'][i]), int(cols['TONODENO'][i]))
            require(min(key) > 0 and key not in net, 'LIVE05_EXTRA_DUPLICATE_OR_INVALID_LINK_KEY')
            net[key] = {x.strip().upper() for x in str(cols['TSYSSET'][i] or '').split(',') if x.strip()}
        out['network_links'] = len(net)
        out['network_key_modes_sha256'] = canonical_hash([(k, sorted(v)) for k, v in sorted(net.items())])
        out['network_fingerprint_scope'] = 'DIRECTED_LINK_KEYS_AND_TSYS_ONLY'
        for k in links:
            if k not in net:
                out['missing'].append(list(k))
            elif not net[k] & {'C', 'C_NOT'}:
                out['closed_for_car'].append(list(k))
        out['status'] = 'PASS' if not out['missing'] and not out['closed_for_car'] else 'FAIL'
        out['counts'] = contract.audit['extra_observations']['counts']
        out['row_weights'] = contract.audit['extra_observations']['row_weights']
        bad = {tuple(k) for k in out['missing'] + out['closed_for_car']}
        out['affected_observations'] = [
            {'obs_id': r.get('obs_id'), 'group': r.get('group'), 'role': role, 'link': list(r[role])}
            for r in contract.extra_rows if isinstance(r, dict)
            for role in ('in_link', 'out_link') if r.get(role) and tuple(r[role]) in bad]
        # Candidate keys are evidence for a reviewed remap, never an automatic substitution.
        out['missing_link_candidates'] = []
        for missing in map(tuple, out['missing']):
            groups = {
                'same_link_no': [k for k in net if k[0] == missing[0]],
                'same_endpoints': [k for k in net if k[1:] == missing[1:]],
                'incident_to_old_endpoints': [k for k in net if set(k[1:]) & set(missing[1:])]}
            out['missing_link_candidates'].append(dict(link=list(missing), **{
                name: {'count': len(keys), 'keys': [list(k) for k in sorted(keys)[:24]]}
                for name, keys in groups.items()}))
    if folder is not None:
        if out['status'] == 'FAIL':
            folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
            roster = folder / 'EXTRA_OBSERVATION_NETWORK_KEYS.csv'
            with roster.open('w', encoding='utf-8', newline='') as f:
                w = csv.writer(f)
                w.writerow(('NO', 'FROMNODENO', 'TONODENO', 'TSYSSET'))
                w.writerows((*k, ','.join(sorted(v))) for k, v in sorted(net.items()))
            out['network_key_export'] = roster.name
        write_json(Path(folder) / 'EXTRA_OBSERVATION_LINKS.json', out)
    if native and links:
        require(out['status'] == 'PASS', 'LIVE05_EXTRA_OBSERVATION_LINKS_NOT_IN_NETWORK:missing=%d,closed=%d'
                % (len(out['missing']), len(out['closed_for_car']))
                + ';observations=' + ','.join(sorted({str(r['obs_id']) for r in out['affected_observations']}))
                + ';see=EXTRA_OBSERVATION_LINKS.json')
    return out
