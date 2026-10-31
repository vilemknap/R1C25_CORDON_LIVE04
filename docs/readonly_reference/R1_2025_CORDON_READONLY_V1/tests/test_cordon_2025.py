from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1_cordon_2025 import (EvidenceError, METHODS, build_baseline_rows, c17_budgets,
                            extract_pairs, observations, route_diagnostic,
                            static_preflight, station_mapping)


def data_csv(path, columns, rows):
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,delimiter=';');w.writeheader();w.writerows(rows)


def create_fixture(tmp):
    mp=tmp/'map.csv'
    edges=[(1,1001,1,2),(2,1002,2,1),(3,2001,2,3),(4,2002,3,2),
           (5,3001,3,4),(6,3002,4,3),(7,4001,4,5),(8,4002,2,6),
           (9,4003,6,3),(10,4004,3,7),(11,4005,7,2)]
    data_csv(mp,['station_id','link_no','from_node_no','to_node_no'],
       [dict(station_id=sid,link_no=e[1],from_node_no=e[2],to_node_no=e[3])
        for sid,eids in ((1,(1,2)),(2,(3,4)),(3,(5,6))) for i in eids for e in edges if e[0]==i])
    target=tmp/'target.csv'
    data_csv(target,['category','trip_type','level','origin_station_id','destination_station_id','rpdi_value'],
       [dict(category='OA',trip_type='ALL',level='RPDI',origin_station_id=i,destination_station_id=j,rpdi_value=9.0 if i!=j else 0)
        for i in range(1,4) for j in range(1,4)])
    budget=tmp/'c17.csv'
    data_csv(budget,['category','station','D3_RPDI_station_to_C17','D3_RPDI_C17_to_station'],
       [dict(category='OA',station='SDP%d'%i,D3_RPDI_station_to_C17=i*20,D3_RPDI_C17_to_station=i*20) for i in range(1,4)])
    db=tmp/'TWO_MODE_PATH_STORE.sqlite'
    con=sqlite3.connect(db)
    con.executescript('''
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE segments(dseg TEXT PRIMARY KEY,mode TEXT NOT NULL,audit_json TEXT NOT NULL);
      CREATE TABLE edges(eid INTEGER PRIMARY KEY,link_no INT,from_no INT,to_no INT);
      CREATE TABLE geometry(gid INTEGER PRIMARY KEY,mode TEXT,orig INT,dest INT,path_index INT,edge_ids BLOB,edge_count INT,sequence_sha256 TEXT,geometry_kind TEXT);
      CREATE TABLE volumes(gid INT,dseg TEXT,volume REAL,PRIMARY KEY(gid,dseg));
    ''')
    con.executemany('INSERT INTO metadata VALUES (?,?)', [('schema','R1_15A2_TWO_MODE_PATH_STORE_V238'),
       ('geometry_identity','PROVISIONAL_SAME_MODE_GEOMETRY_NOT_FULLY_VERIFIED'),
       ('apply_permitted','false'),('parent_hash','FROZEN_SYNTHETIC_TEST')])
    con.executemany('INSERT INTO edges VALUES(?,?,?,?)',edges)
    con.executemany('INSERT INTO segments VALUES(?,?,?)',[(x,'C','{}') for x in ('NATIVE_CW','EXOG_EE_CF')])
    seqs=[(1,[1,3,5], [('NATIVE_CW',10.0),('EXOG_EE_CF',5.0)]),
          (2,[1,8,9,5], [('NATIVE_CW',7.0)]),
          (3,[6,10,11,2],[('EXOG_EE_CF',4.0)]),
          (4,[1,3,4,2,1,8,9,5],[('NATIVE_CW',3.0)]),
          (5,[],[('NATIVE_CW',2.0)])]
    for gid,seq,vols in seqs:
        blob=struct.pack('<%dI'%len(seq),*seq)
        con.execute('INSERT INTO geometry VALUES (?,?,?,?,?,?,?,?,?)',
          (gid,'C',1,2,gid,blob,len(seq),hashlib.sha256(blob).hexdigest(),'LINK_SEQUENCE' if seq else 'ZERO_LINK'))
        con.executemany('INSERT INTO volumes VALUES (?,?,?)',[(gid,c,v) for c,v in vols])
    con.commit();con.close()
    return mp,target,budget,db


def test_pair_methods_separate_and_repeat_holdout():
    p,amb=extract_pairs([1,2,3]);assert not amb
    assert p['ALL_ORDERED_UNIQUE_PAIRS']=={(1,2),(1,3),(2,3)}
    assert p['EXACT_TWO_HITS']==set()
    p,amb=extract_pairs([1,2,1,3]);assert amb
    assert all(not s for s in p.values())


def test_static_preflight_does_not_authorize_calibration(tmp_path):
    mp,target,budget,db=create_fixture(tmp_path)
    p=static_preflight(mp,target,budget,expected_station_count=3)
    assert p['target_offdiag_pairs']==6 and p['target_offdiag_sum']==54
    assert p['c17_symmetric_one_margin']==120
    assert p['allowed_to_calibrate'] is False and p['year_alignment_approved'] is False


def test_real_sqlite_geometry_and_volume_stream(tmp_path):
    mp,target,budget,db=create_fixture(tmp_path)
    result=route_diagnostic(db,station_mapping(mp,expected_station_count=3),selected_dsegs=['NATIVE_CW','EXOG_EE_CF'])
    assert result['complete']
    assert result['metadata']['apply_permitted']=='false'
    assert result['metrics']['route_groups']==5
    assert result['metrics']['repeated_station_route_groups_excluded']==1
    assert result['metrics']['zero_link_route_groups']==1
    assert result['metrics']['positive_volume']==31.0
    assert result['counts']['ALL_ORDERED_UNIQUE_PAIRS']['1>2']==15.0
    assert result['counts']['ALL_ORDERED_UNIQUE_PAIRS']['2>3']==15.0
    assert result['counts']['ALL_ORDERED_UNIQUE_PAIRS']['1>3']==22.0
    assert result['counts']['ALL_ORDERED_UNIQUE_PAIRS']['3>1']==4.0
    assert result['counts']['EXACT_TWO_HITS']=={'1>3':7.0, '3>1':4.0}
    assert result['ds_counts']['ALL_ORDERED_UNIQUE_PAIRS:EXOG_EE_CF']['1>2']==5.0
    baseline=build_baseline_rows(observations(target,expected_station_count=3),result)
    assert sum(r['model_routes'] for r in baseline['EXACT_TWO_HITS'])==11


def test_bounded_smoke_is_explicitly_partial(tmp_path):
    mp,target,budget,db=create_fixture(tmp_path)
    result=route_diagnostic(db,station_mapping(mp,expected_station_count=3),selected_dsegs=['NATIVE_CW'],max_geometry_routes=1)
    assert result['complete'] is False
    assert result['metrics']['truncated_by_max_geometry_routes']==1


def test_missing_dseg_fails_closed(tmp_path):
    mp,target,budget,db=create_fixture(tmp_path)
    with pytest.raises(EvidenceError,match='REQUESTED_DSEG_NOT_IN_CACHE'):
        route_diagnostic(db,station_mapping(mp,expected_station_count=3),selected_dsegs=['NATIVE_CL'])


def test_corrupted_hash_fails_closed(tmp_path):
    mp,target,budget,db=create_fixture(tmp_path)
    c=sqlite3.connect(db)
    c.execute("UPDATE geometry SET sequence_sha256='wrong' WHERE gid=1");c.commit();c.close()
    with pytest.raises(EvidenceError,match='GEOMETRY_BLOB_HASH_MISMATCH'):
        route_diagnostic(db,station_mapping(mp,expected_station_count=3),selected_dsegs=['NATIVE_CW'])


def test_mapping_missing_direction_fails(tmp_path):
    mp,target,budget,db=create_fixture(tmp_path)
    rows=list(csv.DictReader(mp.open(encoding='utf-8-sig'),delimiter=';'))
    data_csv(mp,list(rows[0]),rows[:-1])
    with pytest.raises(EvidenceError,match='STATION_DOES_NOT_HAVE_EXACTLY_TWO'):
        station_mapping(mp,expected_station_count=3)


def test_real_2026_survey_static_authority_if_present():
    base=Path(__file__).resolve().parents[1]/'data'
    p=static_preflight(base/'R1_2026_KORDON_STATION_LINK_MAPPING_CONFIRMED_V1.csv',
        base/'R1_2026_KORDON_OD_RPDI_PRIMARY_ALL_NONVIRTUAL.csv',
        base/'C17_STATION_BY_CATEGORY_RPDI.csv')
    assert p['mapped_directed_edges']==32
    assert p['target_offdiag_pairs']==240
    assert p['target_offdiag_sum']==76522.0
    assert p['c17_symmetric_one_margin']==48645.0
