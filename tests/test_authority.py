import json
from pathlib import Path
import pytest
from cordon2025.common import ROOT, ContractError, read_config, deployment_gate
from cordon2025.authority import mapping, audit_workbooks

def test_actual_mapping():
    idx,rows=mapping(ROOT/'data/source/MAPPING_INPUT.csv')
    assert len(idx)==32 and len(set(idx.values()))==16
    assert {x[0] for x,s in idx.items() if s==16}=={2004231}
    assert len(rows)==32

def test_actual_lineage(tmp_path):
    r=audit_workbooks(ROOT/'data/source',tmp_path)
    assert r['source_files_unchanged']
    assert r['unknown_classification_grand_total']==1218
    assert sum(r['unknown_classification_physical'].values())==848
    assert r['physical_RPDI_by_category']['OA']==76522
    assert sum(r['physical_RPDI_by_category'].values())==97312
    assert r['C17_one_margin_by_category']['OA']==48645
    assert sum(r['C17_one_margin_by_category'].values())==56804
    assert all(all(x['checks'].values()) for x in r['checks'])
    assert not r['production_ready']

def test_incomplete_mapping_rejected(tmp_path):
    p=tmp_path/'bad.csv';p.write_text('station_id;link_no;from_node_no;to_node_no\n1;10;1;2\n')
    with pytest.raises(ContractError,match='INCOMPLETE'):mapping(p)

def test_apply_blocked_even_with_fake_approvals():
    assert deployment_gate({'approvals':{}},False)['apply_permitted'] is False

def test_config_no_live(tmp_path):
    p=tmp_path/'config.json';p.write_text(json.dumps({'apply':True}))
    with pytest.raises(ContractError,match='FORBIDDEN'):read_config(p)
