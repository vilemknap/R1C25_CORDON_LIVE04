"""Offline forensic parity replay. Never completes or modifies an input cache."""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3
import numpy as np
from cordon2025.common import sha256
from cordon2025.parity import ParityPolicy,compare_database
from cordon2025.io import write_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cache',type=Path,required=True)
    ap.add_argument('--matrix',type=Path,required=True)
    ap.add_argument('--dseg',default='NATIVE_CW')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    inputs={'cache':args.cache,'matrix':args.matrix}
    if args.output.resolve() in [p.resolve() for p in inputs.values()]:
        raise ValueError('OUTPUT_INPUT_COLLISION')
    before={k:sha256(p) for k,p in inputs.items()}
    with np.load(args.matrix,allow_pickle=False) as a:
        with closing(sqlite3.connect(args.cache.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            integrity=db.execute('PRAGMA quick_check').fetchone()[0]
            new,_=compare_database(db,args.dseg,a['values'],a['zone_nos'],ParityPolicy())
            old,_=compare_database(db,args.dseg,a['values'],a['zone_nos'],ParityPolicy.legacy())
            complete=dict(db.execute('SELECT key,value FROM metadata')).get('capture_complete')
            nulls=db.execute('SELECT COUNT(*) FROM geometry WHERE edge_ids IS NULL').fetchone()[0]
    after={k:sha256(p) for k,p in inputs.items()}
    if before!=after:raise ValueError('INPUT_CHANGED_DURING_REPLAY')
    report={'status':'FORENSIC_PARITY_REPLAY_COMPLETE','inputs_sha256':before,'inputs_unchanged':True,
            'sqlite_integrity':integrity,'old_parity':old,'new_parity':new,
            'original_capture_complete':complete=='true','null_geometries':nulls,
            'cache_promoted_or_resealed':False,'actual_visum_rerun':False,'apply_permitted':False}
    write_json(args.output,report)
    print(json.dumps({'old':old['status'],'new':new['status'],'capture_complete':complete=='true',
                      'output':str(args.output)},indent=2))

if __name__=='__main__':main()
