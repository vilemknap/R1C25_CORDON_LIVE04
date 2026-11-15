"""LIVE05 extra observations (NDS profiles, ASD profiles, K1/K2 movements): network check.

The rows themselves live in the observation contract (live03_observations) and in the
incidence (live03_incidence.extra_contributions).  This module only proves at the run
start that every directed link the extra rows use exists in the open network and is
open for cars; a missing link would make its row unmatchable (model 0) and stops a
native run before the first write.
"""
from pathlib import Path

from .common import require
from .io import write_json

SCHEMA = 'LIVE05_EXTRA_OBSERVATION_LINKS_V1'


def check_links(visum, contract, folder=None, *, native=True):
    links = sorted(contract.extra_links()) if getattr(contract, 'extra_rows', None) else []
    out = {'schema': SCHEMA, 'links': len(links), 'missing': [], 'closed_for_car': [], 'status': 'NOT_USED'}
    if links:
        try:
            coll = visum.Net.Links
            # all network objects (OnlyActive=False); columns joined by the object index, not by order
            cols = {a: dict(coll.GetMultiAttValues(a, False)) for a in ('NO', 'FROMNODENO', 'TONODENO', 'TSYSSET')}
        except Exception as exc:
            require(not native, 'LIVE05_EXTRA_LINKS_UNREADABLE:%s' % exc)
            cols = {a: {} for a in ('NO', 'FROMNODENO', 'TONODENO', 'TSYSSET')}
        net = {}
        for i, no in cols['NO'].items():
            net[(int(no), int(cols['FROMNODENO'][i]), int(cols['TONODENO'][i]))] = \
                {x.strip() for x in str(cols['TSYSSET'].get(i) or '').split(',')}
        for k in links:
            if k not in net:
                out['missing'].append(list(k))
            elif not net[k] & {'C', 'C_noT'}:
                out['closed_for_car'].append(list(k))
        out['status'] = 'PASS' if not out['missing'] and not out['closed_for_car'] else 'FAIL'
        out['counts'] = contract.audit['extra_observations']['counts']
        out['row_weights'] = contract.audit['extra_observations']['row_weights']
    if folder is not None:
        write_json(Path(folder) / 'EXTRA_OBSERVATION_LINKS.json', out)
    if native and links:
        require(out['status'] == 'PASS', 'LIVE05_EXTRA_OBSERVATION_LINKS_NOT_IN_NETWORK:missing=%d,closed=%d'
                % (len(out['missing']), len(out['closed_for_car'])))
    return out
