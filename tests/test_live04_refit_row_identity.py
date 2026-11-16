"""Zonal refit with the actual LIVE05 key space; no native Visum or COM writes."""
from types import SimpleNamespace
import numpy as np
import pytest
from test_optimizer import example
from cordon2025.common import parent_module,ContractError
from cordon2025 import live02_v24917 as v17
from cordon2025 import live04_generation as generation
from cordon2025.live03_observations import Contract
from cordon2025.live04_config import load_config


@pytest.mark.station_profiles
def test_actual_default_298_observations_have_unique_fit_keys():
    contract=Contract(load_config()['observations'])
    # Directional station targets are resolved only after path-side evidence;
    # their 32 semantic row keys are already fixed by the 16-station roster.
    pairs={tuple(sorted(k)) for k in contract.pair_cells}
    pairs.update(tuple(sorted(k)) for k in contract.station_cells)
    pairs.update(tuple(sorted(k)) for k in contract.extra_cells)
    assert contract.profile_row_count('FIRST_LAST')==32
    pairs.update((s,p) for s in range(1,17) for p in (18,19))
    assert len(pairs)==298
    assert len({v17.pair_key(*p) for p in pairs})==len(pairs)


def test_legacy_station_ids_stay_compatible_and_extra_ids_are_distinct():
    assert v17.pair_key(1,2)==102 and v17.pair_key(3,19)==319
    pairs=[(a,b) for a in range(23) for b in list(range(23))+list(range(1000,1130))]
    assert len({v17.pair_key(*p) for p in pairs})==len(pairs)
    assert v17.pair_key(21,1000)!=v17.pair_key(20,1100)


@pytest.fixture
def measured(monkeypatch):
    primary=example(matrix=[[100.,0.],[0.,200.]],base=[100.,200.],targets=[120.,180.])
    secondary=example(matrix=[[90.,0.],[0.,150.]],base=[90.,150.],targets=[100.,140.])
    for inc,keys in [(primary,[(21,1000),(20,1100)]),(secondary,[(1,2),(1,3)])]:
        for row,key,model in zip(inc.rows,keys,inc.model):
            row.update(origin_station=key[0],destination_station=key[1],model=float(model))
    incs={'FIRST_LAST':primary,'EXACT_TWO_HITS':secondary}
    before={'valid':True,'observed_hash':'OBS','_incidence':incs,
            'methods':{m:{'model':inc.model.tolist()} for m,inc in incs.items()}}
    before['_terms']={m:{'w':np.array([r['weight'] for r in inc.rows])/np.sqrt(np.maximum(1.,[r['observed'] for r in inc.rows])),
                         'y':np.array([r['observed'] for r in inc.rows]),'eps':np.zeros(len(inc.rows))}
                      for m,inc in incs.items()}
    changes={'FIRST_LAST':np.array([7.,-4.]),'EXACT_TWO_HITS':np.array([3.,-2.])}
    after={'valid':True,'observed_hash':'OBS',
           'methods':{m:{'model':(inc.model+changes[m]).tolist()} for m,inc in incs.items()}}
    zones=[1,3,4]
    bounds={('WORK',role,z):(-.4,.4) for role in ('PROD','ATT') for z in zones}
    cfg={'calibration_role':'CALIBRATION','min_add_log_step':1e-5}
    adapter=SimpleNamespace(zones=zones,cfg=cfg,evaluator=SimpleNamespace(method='FIRST_LAST',methods=tuple(incs)))
    mods=generation._mods()
    monkeypatch.setattr(mods.bdgen,'active',lambda:False)
    monkeypatch.setattr(mods.tg,'policy_of',lambda c:{'fit':{'max_iter':4000}})
    monkeypatch.setattr(mods.zguard,'guard_projection',lambda rows,authority:(rows,{'passes':True}))
    monkeypatch.setattr(mods.mguard,'guard',lambda rows,zones,options:(rows,{'passes':True}))
    problem=mods.zf.build_problem(v17.incidence_contract(primary),zones,bounds,cfg)
    problems=generation.effect_problems(adapter,before,bounds,cfg)
    context={'_genfix2_effect_model':{'problem':problem,'problems':problems,'bd':None},
             '_mobilityzone1':{},'_genfix2_mobility':{'zone_rows':[],'options':{}},'v24917':{}}
    preview={'effect_rows':[{'family':f,'role':r,'zone_no':z,'implemented_total_log_effect':.03*(i+1)}
                            for i,(f,r,z) in enumerate(problem.var_keys)]}
    return adapter,context,preview,before,after,changes,bounds,mods


def test_effect_prediction_keeps_asd_and_nds_on_their_own_rows(measured):
    adapter,context,preview,before,after,changes,bounds,mods=measured
    p=context['_genfix2_effect_model']['problems']['FIRST_LAST']
    by={('WORK','ATT',3):.1}
    x=np.array([by.get(tuple(k),0.) for k in p['var_keys']])
    expected=p['G']@x
    assert not np.isclose(expected[0],expected[1])
    np.testing.assert_allclose(generation._delta(p,by),expected)


def test_refit_consumes_separate_measured_changes_for_colliding_legacy_ids(measured,tmp_path):
    adapter,context,preview,before,after,changes,bounds,mods=measured
    result,audit=generation.refine(adapter,context,1.,preview,before,after,tmp_path)
    assert result is not None and audit['status']=='ZONAL_DIRECTION_REFITTED'
    for method,p in result['_genfix2_effect_model']['problems'].items():
        x=generation.implemented_vector(p['var_keys'],preview,1.,None)
        np.testing.assert_allclose(p['G']@x,changes[method],atol=1e-10)
        assert audit['cordon_effect_operators'][method]['prediction_error_l2_after']<1e-10


def test_real_parent_mismatch_still_blocks_refit(measured,tmp_path):
    adapter,context,preview,before,after,changes,bounds,mods=measured
    before['methods']['FIRST_LAST']['model'][0]+=1.
    with pytest.raises(ValueError,match='REFIT_PARENT_DIAGNOSTICS_MISMATCH'):
        generation.refine(adapter,context,1.,preview,before,after,tmp_path)


def test_supplymix_profiles_preserve_all_130_real_extra_observation_identities():
    from cordon2025.live04_supply import row_semantics
    contract=Contract(load_config()['observations'])
    extra=contract.mathcfg_extension()['extra_observation_rows']
    pairs=sorted(tuple(sorted((r['row_id'],r['group_id']))) for r in extra)
    index={p:i for i,p in enumerate(pairs)}
    inc=SimpleNamespace(audit={'directed_to_row':[index[tuple(sorted((r['row_id'],r['group_id'])))] for r in extra],
                               'selected_dsegs':[]})
    local=SimpleNamespace(station_rows=lambda m:False,profile_rows=lambda m:False,
                          mathcfg_extension=lambda:{'extra_observation_rows':extra})
    evaluator=SimpleNamespace(method='FIRST_LAST',station_map={},contract=local)
    data={'pairs':pairs,'model':[float(100+i) for i in range(len(pairs))],'observed':[200.]*len(pairs)}
    sem=row_semantics(evaluator,{'_incidence':{'FIRST_LAST':inc},'methods':{'FIRST_LAST':data}})
    table=parent_module('r1_15a2_supply_mix_v24917').profile_table(sem['profiles'])
    assert len(table)==len(extra)==130
    for i,pair in enumerate(pairs):
        assert table[str(v17.pair_key(*pair))]['model']==data['model'][i]


def test_duplicate_observation_rows_are_rejected_before_building_a_fit(measured):
    adapter,context,preview,before,after,changes,bounds,mods=measured
    inc=before['_incidence']['FIRST_LAST']
    inc.rows[1]=dict(inc.rows[0])
    with pytest.raises(ContractError,match='DUPLICATE_OBSERVATION_ID'):v17.incidence_contract(inc)


def test_refit_rejects_an_incomplete_measured_row_vector(measured,tmp_path):
    adapter,context,preview,before,after,changes,bounds,mods=measured
    after['methods']['FIRST_LAST']['model']=[100.]
    with pytest.raises(ContractError,match='REFIT_INVALID_MEASUREMENT'):
        generation.refine(adapter,context,1.,preview,before,after,tmp_path)


def test_negative_observation_identifiers_are_rejected():
    with pytest.raises(ContractError,match='NEGATIVE_OBSERVATION_ID'):v17.pair_key(-1,1000)
