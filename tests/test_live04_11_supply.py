"""LIVE04.11: production floor 0.25 and the integer SupplyMix design.
Synthetic mock only - not native PTV Visum evidence."""
from types import SimpleNamespace
import pytest
from fake_live04 import Live04Visum
from cordon2025.common import ROOT, read_json, ContractError, parent_module
from cordon2025.live04_config import load_config
from cordon2025.live04_supply import integer_design_steps, options, supply_policy
from cordon2025 import live04_v7 as v7
from test_live04_4 import go, folder_of, merged, GEN_ONLY, SUPPLY_FROM_C1, SUPPLY_HOST, lock_station_links


def test_production_floor_is_025_everywhere():
    cfg = load_config()
    assert cfg['v7']['coefficient_envelope']['PROD'] == [0.25, 3.15]
    assert cfg['v7']['run_options']['mg_min_ratio'] == 0.25 and v7.CORDON_DEVIATIONS['mg_min_ratio'] == 0.25
    pol = v7.targeted_policy(cfg)
    assert pol['envelope']['domestic_hard_by_role']['PROD'] == [0.25, 3.15]
    assert pol['envelope']['refine_domestic_soft_by_role']['PROD'] == [0.25, 3.15]
    assert v7.mobility_options(cfg)['lo'] == 0.25
    assert read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')['v7'] == cfg['v7']
    with pytest.raises(ContractError, match='LIVE04_PROD_ENVELOPE_MUST_EQUAL_MOBILITY_BAND'):
        load_config(overrides={'v7': {'coefficient_envelope': {'PROD': [0.5, 3.15]}}})


def _adapter(value_type):
    attr = SimpleNamespace(ValueType=value_type)
    attrs = SimpleNamespace(ItemByKey=lambda k: attr)
    return SimpleNamespace(visum=SimpleNamespace(Net=SimpleNamespace(Links=SimpleNamespace(Attributes=attrs))))


def test_integer_design_drops_half_unit_steps():
    o = options(load_config())
    assert o['integer_design'] is True
    policy, _, steps, _ = supply_policy(o)
    assert steps == [16, 8, 6, 4, 2, 1]
    a = integer_design_steps(_adapter(1), policy, steps, o)
    assert a['design_step_units'] == [16, 8, 6, 4, 2] and a['removed'] == [1]
    assert integer_design_steps(_adapter(2), policy, steps, o)['design_step_units'] == steps     # double ADDVAL1
    assert integer_design_steps(_adapter(1), policy, steps, dict(o, integer_design=False))['design_step_units'] == steps


def test_integer_design_config_validation():
    with pytest.raises(ContractError, match='LIVE04_SUPPLY_MIX_INTEGER_DESIGN'):
        load_config(overrides={'supply_mix': {'integer_design': 'yes'}})


def test_supply_mix_designs_only_whole_addval1_changes(tmp_path, monkeypatch):
    lock_station_links(monkeypatch)
    v = Live04Visum(tmp_path / 'model', **SUPPLY_HOST)
    go(tmp_path, v, merged(GEN_ONLY, SUPPLY_FROM_C1))
    f = folder_of(tmp_path)
    rec = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'SUPPLYMIX_BLOCK_RESULT.json')
    assert rec['integer_design']['design_step_units'] == [16, 8, 6, 4, 2]
    design = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'DESIGN' / 'SUPPLY_PATH_SEQUENCE_DESIGN.json')
    assert design['candidates']
    for c in design['candidates']:
        assert int(c['step_units']) % 2 == 0
        assert all(float(ch['new']).is_integer() for ch in c['changes'])
    rejected = [t.get('rejected_reasons', {}) for t in rec['costfix1']['trials']]
    assert not any('INTEGER_ADDVAL1_FRACTIONAL_STEP' in r for r in rejected)
    assert rec['status'] == 'ACCEPTED'
