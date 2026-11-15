"""LIVE04.12.3 - guard of the node delays (Nodes VDF) of the network; READ ONLY.

User decision 2026-11-15: node delays are not a calibration lever and the predictor
stays as it is (frozen paths); the full native assignment that decides every
acceptance already contains them.  The calibrator only records the node-delay set-up
at the run start and checks at the end that nothing changed it:

* Node  TYPENO, CAPPRT, T0PRT          (node VDF type, capacity, t0)
* Link  TMODELSPECIAL                   (approach class of the node VDF)
* Turn  TSYSSET, T0PRT                  (U-turn closures)

The calibrator never writes any of them.  An attribute Visum cannot read is reported,
it does not stop the run.  A difference at the end is reported in 00_RESULT.json
(``node_vdf_guard.status = CHANGED``) and in NODE_VDF_FINAL.json.
"""
import hashlib
import json
from pathlib import Path

from .io import write_json

SCHEMA = 'LIVE04_NODE_VDF_GUARD_V1'
GROUPS = (('nodes', 'Nodes', ('NO',), ('TYPENO', 'CAPPRT', 'T0PRT')),
          ('links', 'Links', ('NO', 'FROMNODENO', 'TONODENO'), ('TMODELSPECIAL',)),
          ('turns', 'Turns', ('FROMNODENO', 'VIANODENO', 'TONODENO'), ('TSYSSET', 'T0PRT')))


def _col(coll, attr):
    """{object index: value} over all network objects (OnlyActive=False)."""
    return dict(coll.GetMultiAttValues(attr, False))


def fingerprint(visum):
    out = {'schema': SCHEMA, 'groups': {}}
    for name, coll_name, keys, attrs in GROUPS:
        rec = {'attributes': list(attrs)}
        try:
            coll = getattr(visum.Net, coll_name)
            kcols = [_col(coll, k) for k in keys]
            idx = sorted(kcols[0])
            keyof = {i: tuple(c.get(i) for c in kcols) for i in idx}
            h = hashlib.sha256()
            readable = []
            for a in attrs:
                try:
                    col = _col(coll, a)
                except Exception as exc:          # attribute not in this Visum / network
                    rec.setdefault('unreadable', {})[a] = str(exc)[:200]
                    continue
                readable.append(a)
                vals = [col.get(i) for i in idx]
                rows = sorted(zip((keyof[i] for i in idx), vals), key=lambda r: tuple(str(x) for x in r[0]))
                h.update(json.dumps([a, [[list(map(str, k)), str(v)] for k, v in rows]]).encode())
                if a == 'TYPENO':
                    counts = {}
                    for v in vals:
                        counts[str(v)] = counts.get(str(v), 0) + 1
                    rec['typeno_counts'] = counts
            rec.update(count=len(kcols[0]) if kcols else 0, readable=readable,
                       sha256=h.hexdigest() if readable else None)
        except Exception as exc:
            rec['error'] = str(exc)[:200]
        out['groups'][name] = rec
    out['sha256'] = hashlib.sha256(json.dumps({k: v.get('sha256') for k, v in out['groups'].items()},
                                              sort_keys=True).encode()).hexdigest()
    return out


def record(visum, folder, label):
    fp = fingerprint(visum)
    fp['label'] = label
    write_json(Path(folder) / ('NODE_VDF_%s.json' % label), fp)
    return fp


def compare(base, final):
    if base is None or final is None:
        return {'status': 'NOT_RECORDED'}
    changed = sorted(k for k in base['groups']
                     if base['groups'][k].get('sha256') != final['groups'].get(k, {}).get('sha256'))
    unreadable = sorted('%s.%s' % (k, a) for k, g in base['groups'].items() for a in g.get('unreadable', {}))
    return {'status': 'CHANGED' if changed else 'UNCHANGED', 'changed_groups': changed,
            'unreadable_attributes': unreadable, 'baseline_sha256': base['sha256'], 'final_sha256': final['sha256'],
            'counts': {k: g.get('count') for k, g in base['groups'].items()}}
