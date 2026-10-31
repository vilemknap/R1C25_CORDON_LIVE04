"""Adversarial regressions discovered in the startup audit (not live Visum tests)."""
import json
import sqlite3
import numpy as np
import pytest
from cordon2025.common import ContractError, sha256
from cordon2025.fixtures import create_cache, config
from cordon2025.incidence import build_from_snapshot, aggregate_observations
from cordon2025.optimizer import solve
from test_optimizer import example, cfg


def native_cache(tmp_path):
    p=tmp_path/'native.sqlite'
    m,e=create_cache(p,[('C',10,20,1,[(101,1,2),(102,2,3)],{'NATIVE_CW':100.}),
                       ('C',30,40,1,[],{'NATIVE_CW':0.})])
    db=sqlite3.connect(p)
    db.execute('UPDATE segments SET audit_json=?',(json.dumps({'path_rows':2,'saved_path_volume_sum':100.}),))
    db.commit();db.close();e['cache_sha256']=sha256(p);e.pop('od_totals')
    return p,m,e,config(['NATIVE_CW'])


def test_native_path_rows_zero_row_loss_is_detected(tmp_path):
    p,m,e,c=native_cache(tmp_path)
    db=sqlite3.connect(p);db.execute('DELETE FROM volumes WHERE volume=0');db.commit();db.close();e['cache_sha256']=sha256(p)
    with pytest.raises(ContractError,match='INCOMPLETE_SEGMENT_VOLUME_ROWS'):
        build_from_snapshot(p,m,c,e)


def test_native_conflicting_count_keys_are_detected(tmp_path):
    p,m,e,c=native_cache(tmp_path)
    db=sqlite3.connect(p);db.execute('UPDATE segments SET audit_json=?',(json.dumps({'path_rows':3,'parent_rows':2}),));db.commit();db.close();e['cache_sha256']=sha256(p)
    with pytest.raises(ContractError,match='CONFLICTING_SEGMENT_COUNT_AUTHORITY'):
        build_from_snapshot(p,m,c,e)


def test_canonical_total_alias_collision(tmp_path):
    p,m,e,c=native_cache(tmp_path)
    e['dseg_totals']['native_cw']=100.
    with pytest.raises(ContractError,match='DUPLICATE_CANONICAL_DSEG_TOTAL'):
        build_from_snapshot(p,m,c,e)


def test_conflicting_reverse_roles_before_bidirectional_aggregation():
    inc=example();targets={(1,2):100,(2,1):100,(1,3):100,(3,1):100}
    with pytest.raises(ContractError,match='REVERSE_PAIR_CAL_VALID_LEAKAGE'):
        aggregate_observations(inc,targets,roles={(1,2):'CALIBRATION',(2,1):'VALIDATION'})


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-1.,True])
def test_nonphysical_targets_rejected_even_for_validation(bad):
    inc=example();targets={(1,2):100,(2,1):100,(1,3):bad,(3,1):100}
    with pytest.raises(ContractError,match='INVALID_OBSERVATION_TARGET'):
        aggregate_observations(inc,targets,roles={(1,2):'CALIBRATION',(1,3):'VALIDATION'})


@pytest.mark.parametrize('key,value',[('solver_max_iter',0),('solver_max_iter',-1),('solver_check_every',0),('solver_tolerance',float('nan')),('solver_tolerance',-1.),('power_iterations',0),('block_max_iter',1.5)])
def test_invalid_numeric_solver_options_fail_before_parent(key,value):
    with pytest.raises(ContractError,match='INVALID_SOLVER_SETTING'):
        solve(example(),cfg(**{key:value}))


def test_negative_fixed_flow_rejected():
    inc=example();inc.fixed[0]=-1.
    with pytest.raises(ContractError,match='INVALID_INCIDENCE'):
        solve(inc,cfg())


def test_nonfinite_operator_rejected():
    inc=example();inc.operator.values[0]=np.nan
    with pytest.raises(ContractError,match='INVALID_INCIDENCE'):
        solve(inc,cfg())
