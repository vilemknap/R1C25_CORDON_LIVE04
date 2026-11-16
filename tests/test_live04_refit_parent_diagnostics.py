"""Detailed parent mismatch evidence, preserving the same-capture identity limit."""
import json
import numpy as np
import pytest
from test_live04_refit_row_identity import measured
from cordon2025 import live04_fit_objective as fo, live04_generation as gen


def rows(*values):
    return [{'countlocation_no':100+i, 'model':v} for i,v in enumerate(values)]


def test_exact_values_and_double_precision_noise_pass():
    check = fo.parent_row_check(rows(1000.,20.,0.), {100:0,101:1,102:2}, [1000.,20.,0.])
    assert check['passes'] and check['rows_exact'] == 3
    check = fo.parent_row_check(rows(1000.,20.,0.), {100:0,101:1,102:2}, [1000.+1e-10,20.-1e-10,1e-12])
    assert check['passes'] and check['max_abs_difference'] > 0
    assert (check['atol'],check['rtol']) == (1e-9,1e-12)


def test_the_claude_rollback_tolerance_would_hide_a_same_capture_difference():
    check = fo.parent_row_check(rows(1000.), {100:0}, [1001.5])
    assert 1.5 <= 1. + 1e-3 * 1001.5  # proposed patch's tolerance
    assert not check['passes'] and check['rows_outside'] == 1
    assert check['worst_key'] == 100 and check['max_abs_difference'] == 1.5


@pytest.mark.parametrize('damage',['missing','negative_index','duplicate','nan','inf'])
def test_invalid_identity_is_rejected_and_report_is_strict_json(damage):
    data, index, parent = rows(1000.,20.), {100:0,101:1}, [1000.,20.]
    if damage=='missing':index.pop(101)
    elif damage=='negative_index':index[101]=-1
    elif damage=='duplicate':data.append(dict(data[0]))
    elif damage=='nan':data[0]['model']=np.nan
    else:parent[0]=np.inf
    check = fo.parent_row_check(data,index,parent)
    assert not check['passes']
    json.dumps(check,allow_nan=False)


@pytest.mark.parametrize('damage',['incidence_parent','fit_parent'])
def test_refit_writes_every_parent_difference_before_refusing_the_measurement(measured,tmp_path,damage):
    adapter,context,preview,before,after,*_ = measured
    if damage=='incidence_parent':before['methods']['FIRST_LAST']['model'][0] += 1.
    else:context['_genfix2_effect_model']['problem'].profile_rows[0]['model'] += .1
    with pytest.raises(ValueError,match='REFIT_PARENT_DIAGNOSTICS_MISMATCH:method=FIRST_LAST'):
        gen.refine(adapter,context,1.,preview,before,after,tmp_path)
    report=json.loads((tmp_path/'MEASURED_ZONAL_REFIT_PARENT_MISMATCH.json').read_text())
    assert not report['passes'] and report['rows_checked']==2 and report['rows_outside']==1
    assert report['worst_key']==int(context['_genfix2_effect_model']['problem'].profile_rows[0]['countlocation_no'])
    expected='CAPTURED_INCIDENCE_VS_PARENT_DIAGNOSTIC' if damage=='incidence_parent' else 'FIT_ROWS_VS_CAPTURED_PARENT'
    assert report['comparison']==expected and len(report['rows'])==2


def test_successful_refit_audits_identity_without_loosening_the_guard(measured,tmp_path):
    adapter,context,preview,before,after,*_ = measured
    out,audit=gen.refine(adapter,context,1.,preview,before,after,tmp_path)
    assert out is not None and audit['parent_row_check']['passes']
    assert audit['parent_row_check']['rows_exact']==2
    assert audit['parent_row_check']['atol']==1e-9
    assert not (tmp_path/'MEASURED_ZONAL_REFIT_PARENT_MISMATCH.json').exists()
